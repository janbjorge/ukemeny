"""Recipes from matprat.no.

The sitemap lists every recipe page with its last change. Each page embeds its data as
Next.js page props (`__NEXT_DATA__`): ingredients with amount, unit and grocery category,
and the dish type matprat reports to analytics ("Middagsrett"). robots.txt allows
/oppskrifter/; the search API under /Services/ is disallowed, so pages are read one by one.
"""

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Self

import httpx2

from core.errors import SourceUnavailableError
from core.models import Ingredient, Recipe, RecipeRef

BASE = "https://www.matprat.no"
SITEMAP = f"{BASE}/sitemap.xml"
USER_AGENT = "matris/0.1 (+https://matris.app)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

_RECIPE_URL = re.compile(r"^https://www\.matprat\.no/oppskrifter/[^/]+/[^/]+/$")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
log = logging.getLogger("matris.matprat")


def parse_sitemap(xml: str) -> list[RecipeRef]:
    refs = []
    for url in ET.fromstring(xml).iter(f"{_SITEMAP_NS}url"):
        loc = (url.findtext(f"{_SITEMAP_NS}loc") or "").strip()
        if _RECIPE_URL.match(loc):
            refs.append(RecipeRef(loc, (url.findtext(f"{_SITEMAP_NS}lastmod") or "").strip()))
    return refs


def _split(value: object) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def _ingredient(raw: dict[str, Any]) -> Ingredient:
    words = [raw.get(k) for k in ("preText", "middleText", "name", "postText", "postText2")]
    amount = raw.get("amount")
    unit = raw.get("unit") or ""
    line = " ".join(w.strip() for w in words if w and w.strip())
    if amount is not None:
        line = f"{amount:g} {unit} {line}".replace("  ", " ")
    return Ingredient(
        name=(raw.get("name") or "").strip().lower(),
        text=line,
        amount=float(amount) if amount is not None else None,
        unit=unit,
        category=raw.get("category") or "",
    )


def parse_recipe(html: str, url: str) -> Recipe | None:
    """The recipe on a matprat page, or None when the page holds no recipe."""
    match = _NEXT_DATA.search(html)
    if match is None:
        return None
    page = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("pageData") or {}
    if not page.get("isRecipe"):
        return None
    raw = page.get("ingredients") or [i for group in page.get("ingredientGroups") or [] for i in group.get("ingredients") or []]
    analytics = page.get("gtmDimensions") or {}
    return Recipe(
        url=url,
        name=page.get("name") or "",
        dish_types=_split(analytics.get("dimension8")),
        main_categories=_split(analytics.get("dimension1")),
        portions=int(page.get("portions") or 4),
        prep_time=page.get("preparationTime") or "",
        rating=page.get("ratingPrecise"),
        rating_count=int(page.get("ratingCount") or 0),
        ingredients=tuple(_ingredient(i) for i in raw if i.get("name")),
    )


@dataclass
class MatpratRecipeSource:
    """Implements core.ports.RecipeSource. At most `workers` requests at a time. matprat.no's robots.txt asks for no
    crawl delay and a page answers in about 0.2 s; a 429 or 5xx is retried with a growing pause."""

    client: httpx2.AsyncClient
    workers: int = 16
    tries: int = 4
    _slots: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self._slots = asyncio.Semaphore(self.workers)

    @classmethod
    @asynccontextmanager
    async def open(cls, workers: int = 16) -> AsyncGenerator[Self]:
        async with httpx2.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            yield cls(client, workers)

    async def index(self) -> list[RecipeRef]:
        return parse_sitemap(await self._get(SITEMAP))

    async def fetch(self, url: str) -> Recipe | None:
        try:
            html = await self._get(url)
        except _GoneError:
            return None
        return parse_recipe(html, url)

    async def _get(self, url: str) -> str:
        async with self._slots:
            return await self._get_with_retry(url)

    async def _get_with_retry(self, url: str) -> str:
        for attempt in range(self.tries):
            try:
                response = await self.client.get(url)
            except httpx2.TransportError as e:
                if attempt == self.tries - 1:
                    raise SourceUnavailableError("matprat.no", str(e)) from e
                log.info("retry %d: %s (%s)", attempt + 1, url, e)
            else:
                if response.status_code in (404, 410):
                    raise _GoneError(url)
                if response.status_code not in RETRY_STATUS:
                    if response.is_error:
                        raise SourceUnavailableError("matprat.no", f"{response.status_code} {url}")
                    return response.text
                if attempt == self.tries - 1:
                    raise SourceUnavailableError("matprat.no", f"{response.status_code} {url}")
                log.info("retry %d: %s (%d)", attempt + 1, url, response.status_code)
            await asyncio.sleep(2**attempt)
        raise AssertionError("unreachable")


class _GoneError(Exception):
    pass
