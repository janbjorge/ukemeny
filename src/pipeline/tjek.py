"""This week's grocery offers from Tjek, the catalog service behind mattilbud.no.

The public v2 API needs no key for catalogs and offers. Offers are read per catalog, since
one location search stops at 1,000 offers. A catalog does not change once published, so
its offers are kept on disk: a run only lists the catalogs (one request) and fetches the
offers of catalogs it has not seen.
"""

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import httpx2

from core.errors import SourceUnavailableError
from core.models import Offer

API = "https://squid-api.tjek.com/v2"
PAGE = 100
USER_AGENT = "matris/0.1 (+https://matris.app)"


_NUMBER = r"(\d+(?:[ \u00a0]\d{3})*(?:,\d+)?)"
_KG_BEFORE = re.compile(_NUMBER + r"\s*pr\.?\s*kg", re.IGNORECASE)
_KG_AFTER = re.compile(r"pr\.?\s*kg\.?\s*" + _NUMBER, re.IGNORECASE)
_PER_KG = re.compile(r"pr\.?\s*kg", re.IGNORECASE)
_CATALOG_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_BEFORE = re.compile(r"\bfør(?:pris)?\.?:?\s*(?:kr\.?\s*)?" + _NUMBER, re.IGNORECASE)


def _number(text: str) -> float:
    return float(text.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def per_kg(price: float, description: str, quantity: dict[str, Any] | None) -> float | None:
    """NOK per kg. The catalog text is most reliable, with the number on either side
    ("Enh.pris 52,91 pr. kg", "700 g, Prior, pr. kg 141,43"). Weighed goods
    ("Ca. 1,3 kg, Gilde, pr. kg") are priced per kg already. The before-price is left out:
    "Førpris 339,00 pr kg" is not today's price."""
    description = _BEFORE.sub(" ", description)
    if match := _KG_BEFORE.search(description) or _KG_AFTER.search(description):
        return _number(match.group(1))
    if _PER_KG.search(description):
        return price
    quantity = quantity or {}
    si = (quantity.get("unit") or {}).get("si") or {}
    size = quantity.get("size") or {}
    if si.get("symbol") == "kg" and size.get("from") and size.get("from") == size.get("to"):
        return float(price / (size["from"] * si["factor"]))
    return None


MAX_DISCOUNT = 0.75
"""Bigger discounts in the catalogs were unit mix-ups, not sales."""


def before_price(price: float, pre_price: float | None, description: str, kg_price: float | None = None) -> float | None:
    """The price before the offer, on the same basis as `price`: Tjek's field, or the
    catalog text ("Førpris 34,90", "Før 48,9"; the lower end of a range). None unless it is
    a plausible discount.

    Weighed goods can be priced per 100 g against a before-price per kg ("29,90 ... Pr kg
    299,00. Førpris 339,00 pr kg"), which read as 91% off instead of 12%.
    """
    if not pre_price and (match := _BEFORE.search(description)):
        pre_price = _number(match.group(1))
    if not pre_price:
        return None
    if kg_price and abs(price * 10 - kg_price) <= 0.05 * kg_price:
        pre_price /= 10
    if not price < pre_price <= price / (1 - MAX_DISCOUNT):
        return None
    return float(pre_price)


def parse_offer(raw: dict[str, Any]) -> Offer:
    description = " ".join((raw.get("description") or "").split())
    price = float(raw["pricing"]["price"])
    kg_price = per_kg(price, description, raw.get("quantity"))
    pre_price = before_price(price, raw["pricing"].get("pre_price"), description, kg_price)
    return Offer(
        id=raw["id"],
        store=raw["dealer"]["name"],
        heading=raw["heading"],
        description=description,
        price=price,
        pre_price=pre_price,
        per_kg=kg_price,
        valid_until=datetime.fromisoformat(raw["run_till"]).date(),
    )


@dataclass
class TjekOfferSource:
    """Implements core.ports.OfferSource for one location."""

    client: httpx2.AsyncClient
    lat: float
    lng: float
    radius_km: float
    stores: tuple[str, ...]
    """Grocery chains to read (src/adapters/profile.py GROCERS)."""
    cache_dir: Path | None = None
    """Raw offers per catalog, one JSON file each. None: always fetch."""

    def __post_init__(self) -> None:
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        lat: float,
        lng: float,
        radius_km: float,
        stores: tuple[str, ...],
        cache_dir: Path | None = None,
    ) -> AsyncGenerator[Self]:
        async with httpx2.AsyncClient(base_url=API, timeout=30, headers={"User-Agent": USER_AGENT}) as client:
            yield cls(client, lat, lng, radius_km, stores, cache_dir)

    async def current(self) -> list[Offer]:
        geo = {
            "r_lat": self.lat,
            "r_lng": self.lng,
            "r_radius": int(self.radius_km * 1000),
            "r_locale": "nb_NO",
        }
        now = datetime.now(UTC)
        catalogs = [
            c
            for c in await self._paged("/catalogs", geo)
            if c["dealer"]["name"] in self.stores
            and c.get("offer_count")
            and datetime.fromisoformat(c["run_from"]) <= now <= datetime.fromisoformat(c["run_till"])
        ]
        pages = await asyncio.gather(*(self._catalog_offers(c) for c in catalogs))
        self._prune({c["id"] for c in catalogs})
        offers = {o.id: o for page in pages for o in map(parse_offer, page)}
        return list(offers.values())

    def _cache_path(self, catalog_id: str) -> Path | None:
        if self.cache_dir is None or not _CATALOG_ID.match(catalog_id):
            return None
        return self.cache_dir / f"{catalog_id}.json"

    async def _catalog_offers(self, catalog: dict[str, Any]) -> list[dict[str, Any]]:
        """From disk when the catalog was seen with the same number of offers (Tjek's count
        changes when a catalog is corrected)."""
        path = self._cache_path(catalog["id"])
        if path and (offers := _read(path, catalog["offer_count"])) is not None:
            return offers
        offers = await self._paged("/offers", {"catalog_ids": catalog["id"]})
        if path:
            _write(path, catalog["offer_count"], offers)
        return offers

    def _prune(self, running: set[str]) -> None:
        """Forget catalogs that ended or are no longer listed."""
        if self.cache_dir:
            for path in self.cache_dir.glob("*.json"):
                if path.stem not in running:
                    path.unlink()

    async def _paged(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while True:
            try:
                response = await self.client.get(path, params={**params, "limit": PAGE, "offset": len(rows)})
                response.raise_for_status()
            except httpx2.HTTPError as e:
                raise SourceUnavailableError("Tjek", str(e)) from e
            page: list[dict[str, Any]] = response.json()
            rows.extend(page)
            if len(page) < PAGE:
                return rows


def _read(path: Path, offer_count: int) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    cached = json.loads(path.read_text())
    if cached.get("offer_count") != offer_count:
        return None
    offers: list[dict[str, Any]] = cached["offers"]
    return offers


def _write(path: Path, offer_count: int, offers: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offer_count": offer_count, "offers": offers}))
    tmp.replace(path)
