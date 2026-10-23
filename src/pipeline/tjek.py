"""This week's grocery offers from Tjek, the catalog service behind mattilbud.no.

The public v2 API needs no key for catalogs and offers. The catalogs are listed around each place in PLACES, and offers
are read once per catalog, since one location search stops at 1,000 offers and most catalogs reach many places. Nothing
is kept between runs.
"""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NotRequired, Self, TypedDict

import httpx2

from core.errors import SourceUnavailableError
from core.models import Offer, Offers

API = "https://squid-api.tjek.com/v2"
PAGE = 100
USER_AGENT = "matris/0.1 (+https://matris.app)"
log = logging.getLogger("matris.tjek")

GROCERS = (
    "Bunnpris",
    "Coop Extra",
    "Coop Marked",
    "Coop Mega",
    "Coop Prix",
    "Europris",
    "Extra",
    "Joker",
    "KIWI",
    "Matkroken",
    "MENY",
    "Obs",
    "REMA 1000",
    "SPAR",
)
"""Grocery chains on mattilbud.no. The same places also have furniture, hardware and electronics
catalogs; "Spar Kjøp" is building supplies, not SPAR."""

PLACES: Mapping[str, tuple[float, float]] = {
    "Oslo": (59.9139, 10.7522),
    "Bergen": (60.3913, 5.3221),
    "Trondheim": (63.4305, 10.3951),
    "Stavanger": (58.9700, 5.7331),
    "Kristiansand": (58.1467, 7.9956),
    "Drammen": (59.7440, 10.2045),
    "Fredrikstad": (59.2181, 10.9298),
    "Tromsø": (69.6492, 18.9553),
    "Tønsberg": (59.2675, 10.4076),
    "Ålesund": (62.4722, 6.1495),
    "Skien": (59.2096, 9.6090),
    "Bodø": (67.2804, 14.4049),
    "Haugesund": (59.4138, 5.2680),
    "Arendal": (58.4615, 8.7725),
    "Hamar": (60.7945, 11.0680),
    "Lillehammer": (61.1153, 10.4662),
    "Molde": (62.7375, 7.1591),
    "Harstad": (68.7983, 16.5417),
    "Alta": (69.9689, 23.2716),
    "Førde": (61.4520, 5.8570),
}
"""Where a visitor can say they shop (latitude, longitude): towns spread over the country, one word each, so a search
reads it (core.search). METHOD.md §4."""
RADIUS_KM = 15
"""Stores this near a place count as its stores."""


_NUMBER = r"(\d+(?:[ \u00a0]\d{3})*(?:,\d+)?)"
_KG_BEFORE = re.compile(_NUMBER + r"\s*pr\.?\s*kg", re.IGNORECASE)
_KG_AFTER = re.compile(r"pr\.?\s*kg\.?\s*" + _NUMBER, re.IGNORECASE)
_PER_KG = re.compile(r"pr\.?\s*kg", re.IGNORECASE)
_BEFORE = re.compile(r"\bfør(?:pris)?\.?:?\s*(?:kr\.?\s*)?" + _NUMBER, re.IGNORECASE)


# The parts of Tjek's JSON that are read
class _Si(TypedDict, total=False):
    symbol: str
    factor: float


class _Unit(TypedDict, total=False):
    si: _Si | None


_Size = TypedDict("_Size", {"from": float, "to": float}, total=False)


class Quantity(TypedDict, total=False):
    unit: _Unit | None
    size: _Size | None
    pieces: _Size | None


class _Pricing(TypedDict):
    price: float
    pre_price: NotRequired[float | None]


class _Dealer(TypedDict):
    name: str


class RawOffer(TypedDict):
    id: str
    heading: str
    description: NotRequired[str | None]
    pricing: _Pricing
    quantity: NotRequired[Quantity | None]
    run_till: str
    dealer: _Dealer


class RawCatalog(TypedDict):
    id: str
    dealer: _Dealer
    offer_count: NotRequired[int | None]
    run_from: str
    run_till: str


def _number(text: str) -> float:
    return float(text.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def per_kg(price: float, description: str, quantity: Quantity | None) -> float | None:
    """NOK per kg. The catalog text is most reliable, with the number on either side
    ("Enh.pris 52,91 pr. kg", "700 g, Prior, pr. kg 141,43"). Weighed goods
    ("Ca. 1,3 kg, Gilde, pr. kg") are priced per kg already. The before-price is left out:
    "Førpris 339,00 pr kg" is not today's price."""
    description = _BEFORE.sub(" ", description)
    if match := _KG_BEFORE.search(description) or _KG_AFTER.search(description):
        return _number(match.group(1))
    if _PER_KG.search(description):
        return price
    unit = (quantity or {}).get("unit") or {}
    si = unit.get("si") or {}
    size = (quantity or {}).get("size") or {}
    weight, factor = size.get("from"), si.get("factor")
    if si.get("symbol") == "kg" and weight and factor and weight == size.get("to"):
        return float(price / (weight * factor))
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


_SIZE_UNIT = r"(kg|g|ml|cl|dl|l|liter)"
_RANGE = re.compile(_NUMBER + r"\s*[-\u2013]\s*" + _NUMBER + r"\s*" + _SIZE_UNIT + r"\b", re.IGNORECASE)
_SIZE = re.compile(r"(?<![\d,.\-\u2013])" + _NUMBER + r"\s*" + _SIZE_UNIT + r"\b", re.IGNORECASE)
_TIMES = re.compile(r"\b(\d+)\s*x\s*" + _NUMBER + r"\s*" + _SIZE_UNIT + r"\b", re.IGNORECASE)
_COUNT = re.compile(r"\b(\d{1,3})\s*(?:store\s+|små\s+)?(?:stk\.?|egg)\b(?!\s*for\b)", re.IGNORECASE)
_PER_STK = re.compile(r"\bpr\.?\s*stk", re.IGNORECASE)
_FOR = re.compile(r"\b(\d)\s*(?:stk|pk)?\.?\s*for\s*(?:kr\.?\s*)?" + _NUMBER, re.IGNORECASE)
_SINGLE = re.compile(r"\b1\s*(?:pk|stk)\.?\s*(?:kr\.?\s*)?" + _NUMBER, re.IGNORECASE)
_BASE: Mapping[str, tuple[float, str]] = {
    "kg": (1000.0, "g"),
    "g": (1.0, "g"),
    "ml": (1.0, "ml"),
    "cl": (10.0, "ml"),
    "dl": (100.0, "ml"),
    "l": (1000.0, "ml"),
    "liter": (1000.0, "ml"),
    "stk": (1.0, "stk"),
    "pcs": (1.0, "stk"),
}
"""A catalog's size units in g, ml or stk (core.units): the factor and the base unit."""
SIZE_TOLERANCE = 0.10
"""A pack size the catalog's own numbers do not confirm is not used: price is the per-kilo price times size times pieces,
within this."""


def pieces(description: str, quantity: Quantity | None, price: float, pre_price: float | None) -> int:
    """Packs the price buys. Tjek's `pieces`, else «2 for 80», else a single-pack price the before-price or the price is a
    multiple of («1 pk kr 58,50» against 117,00). 1 otherwise; «2-pk» is a pack of two, not two packs."""
    counted = (quantity or {}).get("pieces") or {}
    low, high = counted.get("from"), counted.get("to")
    if low and low == high and low >= 2:
        return int(low)
    if (match := _FOR.search(description)) and abs(_number(match.group(2)) - price) <= 0.01 * price:
        return int(match.group(1))
    if match := _SINGLE.search(description):
        single = _number(match.group(1))
        for total in (pre_price, price):
            if total and single and 2 <= (n := round(total / single)) <= 6 and abs(total / single - n) <= 0.02:
                return n
    return 1


def amount(price: float, description: str, quantity: Quantity | None, kg_price: float | None) -> tuple[float | None, float | None, str]:
    """What one pack holds, as (size, the top of a range or None, unit): Offer.size, size_to and unit. Goods priced by
    weight come first («pr. kg»: 1 kg; a price a tenth of the per-kilo price: 0.1 kg), then Tjek's `quantity`, then the
    catalog text («700 g», «250-500 g», «6 x 47 g», «12 stk», «12 store egg», «pr stk»)."""
    if kg_price is not None and abs(kg_price - price) <= 0.005 * price:
        return 1.0, None, "kg"
    if kg_price is not None and abs(price * 10 - kg_price) <= 0.05 * kg_price:
        return 0.1, None, "kg"
    unit = (quantity or {}).get("unit") or {}
    si = unit.get("si") or {}
    size = (quantity or {}).get("size") or {}
    low, high, factor = size.get("from"), size.get("to"), si.get("factor")
    if low and factor and (base := _BASE.get(str(si.get("symbol", "")).lower())):
        scale, in_unit = base
        return low * factor * scale, high * factor * scale if high and high != low else None, in_unit
    if match := _RANGE.search(description):
        scale, in_unit = _BASE[match.group(3).lower()]
        return _number(match.group(1)) * scale, _number(match.group(2)) * scale, in_unit
    if match := _TIMES.search(description):
        scale, in_unit = _BASE[match.group(3).lower()]
        return int(match.group(1)) * _number(match.group(2)) * scale, None, in_unit
    if match := _SIZE.search(description):
        scale, in_unit = _BASE[match.group(2).lower()]
        return _number(match.group(1)) * scale, None, in_unit
    if match := _COUNT.search(description):
        return float(match.group(1)), None, "stk"
    if _PER_STK.search(description):
        return 1.0, None, "stk"
    return None, None, ""


def confirmed(price: float, kg_price: float | None, size: float | None, size_to: float | None, unit: str, packs: int) -> bool:
    """Whether the catalog's own numbers agree on a pack by weight: the price is the per-kilo price times size times
    pieces (every one of the 217 offers on a card with both agreed on 2026-10-23). Without a per-kilo price, with a
    range, or in another unit there is nothing to check against."""
    if unit != "g" or size is None or size_to is not None or kg_price is None:
        return True
    return abs(price / (packs * size / 1000) - kg_price) <= SIZE_TOLERANCE * kg_price


def parse_offer(raw: RawOffer, catalog: str) -> Offer:
    description = " ".join((raw.get("description") or "").split())
    price = float(raw["pricing"]["price"])
    quantity = raw.get("quantity")
    kg_price = per_kg(price, description, quantity)
    pre_price = before_price(price, raw["pricing"].get("pre_price"), description, kg_price)
    packs = pieces(description, quantity, price, pre_price)
    size, size_to, unit = amount(price, description, quantity, kg_price)
    if not confirmed(price, kg_price, size, size_to, unit, packs):
        log.info("size not confirmed: %s «%s» %s g for %s, pr. kg %s", raw["dealer"]["name"], raw["heading"], size, price, kg_price)
        size, size_to, unit = None, None, ""
    return Offer(
        id=raw["id"],
        store=raw["dealer"]["name"],
        catalog=catalog,
        heading=raw["heading"],
        description=description,
        price=price,
        pre_price=pre_price,
        per_kg=kg_price,
        valid_until=datetime.fromisoformat(raw["run_till"]).date(),
        size=size,
        size_to=size_to,
        unit=unit,
        pieces=packs,
    )


@dataclass
class TjekOfferSource:
    """Implements core.ports.OfferSource for every place."""

    client: httpx2.AsyncClient
    places: Mapping[str, tuple[float, float]]
    """Per place, its latitude and longitude (PLACES)."""
    radius_km: float
    stores: tuple[str, ...]
    """Grocery chains to read (GROCERS)."""

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        places: Mapping[str, tuple[float, float]] = PLACES,
        radius_km: float = RADIUS_KM,
        stores: tuple[str, ...] = GROCERS,
        fetching: Callable[[str], None] | None = None,
    ) -> AsyncGenerator[Self]:
        """`fetching` hears the URL of every request as it goes out."""

        async def tell(request: httpx2.Request) -> None:
            if fetching:
                fetching(str(request.url))

        # One client for the run, so connections are reused; Tjek speaks HTTP/2, so the catalogs share one
        async with httpx2.AsyncClient(
            base_url=API, timeout=30, http2=True, headers={"User-Agent": USER_AGENT}, event_hooks={"request": [tell]}
        ) as client:
            yield cls(client, places, radius_km, stores)

    async def current(self) -> Offers:
        near = await asyncio.gather(*(self._catalogs(lat, lng) for lat, lng in self.places.values()))
        catalogs = {c["id"]: c for found in near for c in found}
        places = {place: tuple(c["id"] for c in found) for place, found in zip(self.places, near, strict=True)}
        for c in catalogs.values():
            reach = [place for place, ids in places.items() if c["id"] in ids]
            log.info(
                "catalog: %s, %s offers, %s to %s, %s",
                c["dealer"]["name"],
                c["offer_count"],
                c["run_from"][:10],
                c["run_till"][:10],
                "every place" if len(reach) == len(places) else ", ".join(reach),
            )
        pages = await asyncio.gather(*(self._paged("/offers", {"catalog_ids": catalog}, RawOffer) for catalog in catalogs))
        offers = {o.id: o for catalog, page in zip(catalogs, pages, strict=True) for o in (parse_offer(raw, catalog) for raw in page)}
        return Offers(tuple(offers.values()), places)

    async def _catalogs(self, lat: float, lng: float) -> list[RawCatalog]:
        """The grocery catalogs that run today at stores near this point."""
        geo: dict[str, str | int | float] = {"r_lat": lat, "r_lng": lng, "r_radius": int(self.radius_km * 1000), "r_locale": "nb_NO"}
        now = datetime.now(UTC)
        return [
            c
            for c in await self._paged("/catalogs", geo, RawCatalog)
            if c["dealer"]["name"] in self.stores
            and c.get("offer_count")
            and datetime.fromisoformat(c["run_from"]) <= now <= datetime.fromisoformat(c["run_till"])
        ]

    async def _paged[T](self, path: str, params: Mapping[str, str | int | float], row: type[T]) -> list[T]:
        """Every row behind `path`, page by page. `row` is the shape of a row, for the type checker."""
        rows: list[T] = []
        while True:
            try:
                response = await self.client.get(path, params={**params, "limit": PAGE, "offset": len(rows)})
                response.raise_for_status()
            except httpx2.HTTPError as e:
                raise SourceUnavailableError("Tjek", str(e)) from e
            page: list[T] = response.json()
            rows.extend(page)
            if len(page) < PAGE:
                return rows
