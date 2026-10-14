"""Web pages read one by one, for the recipe sources (matprat.py, godt.py)."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Self

import httpx2

from core.errors import SourceUnavailableError

USER_AGENT = "matris/0.1 (+https://matris.app)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
log = logging.getLogger("matris.pages")


@dataclass
class Pages:
    """At most `workers` requests at a time to one site, and at most `per_second` when set; a 429 or 5xx is retried
    with a growing pause. A firewall's challenge (AWS WAF's `x-amzn-waf-action`) is not retried: it lasts minutes."""

    client: httpx2.AsyncClient
    site: str
    """For errors: "matprat.no"."""
    workers: int = 16
    tries: int = 4
    per_second: float | None = None
    _slots: asyncio.Semaphore = field(init=False)
    _turn: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _next: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self._slots = asyncio.Semaphore(self.workers)

    @classmethod
    @asynccontextmanager
    async def open(
        cls, site: str, workers: int = 16, fetching: Callable[[str], None] | None = None, per_second: float | None = None
    ) -> AsyncGenerator[Self]:
        """`fetching` hears the URL of every request as it goes out."""

        async def tell(request: httpx2.Request) -> None:
            if fetching:
                fetching(str(request.url))

        # One client for the run: its pool keeps a connection per worker alive, so 100 matprat pages took 16 TLS
        # handshakes (2026-10-13). matprat.no speaks only HTTP/1.1, so HTTP/2 would not share them further.
        async with httpx2.AsyncClient(
            timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}, event_hooks={"request": [tell]}
        ) as client:
            yield cls(client, site, workers, per_second=per_second)

    async def get(self, url: str) -> str | None:
        """The page, or None when it is gone (404, 410). Raises SourceUnavailableError."""
        async with self._slots:
            return await self._get_with_retry(url)

    async def _pace(self) -> None:
        if not self.per_second:
            return
        async with self._turn:
            if (wait := self._next - time.monotonic()) > 0:
                await asyncio.sleep(wait)
            self._next = max(self._next, time.monotonic()) + 1 / self.per_second

    async def _get_with_retry(self, url: str) -> str | None:
        for attempt in range(self.tries):
            await self._pace()
            try:
                response = await self.client.get(url)
            except httpx2.TransportError as e:
                if attempt == self.tries - 1:
                    raise SourceUnavailableError(self.site, str(e)) from e
                log.info("retry %d: %s (%s)", attempt + 1, url, e)
            else:
                if challenge := response.headers.get("x-amzn-waf-action"):
                    raise SourceUnavailableError(self.site, f"its firewall answered {challenge}: {url}")
                if response.status_code in (404, 410):
                    return None
                if response.status_code not in RETRY_STATUS:
                    if response.is_error:
                        raise SourceUnavailableError(self.site, f"{response.status_code} {url}")
                    return response.text
                if attempt == self.tries - 1:
                    raise SourceUnavailableError(self.site, f"{response.status_code} {url}")
                log.info("retry %d: %s (%d)", attempt + 1, url, response.status_code)
            await asyncio.sleep(2**attempt)
        raise AssertionError("unreachable")
