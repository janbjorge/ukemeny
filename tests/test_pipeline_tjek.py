from datetime import UTC, date, datetime, timedelta

import httpx2
import pytest

from adapters.profile import GROCERS as STORES
from core.errors import SourceUnavailableError
from pipeline.tjek import (
    API,
    Quantity,
    RawCatalog,
    RawOffer,
    TjekOfferSource,
    before_price,
    parse_offer,
    per_kg,
)

KG = {
    "unit": {"symbol": "g", "si": {"symbol": "kg", "factor": 0.001}},
    "size": {"from": 400, "to": 400},
}


@pytest.mark.parametrize(
    ("price", "description", "quantity", "expected"),
    [
        (99.0, "700 g, Prior, pr. kg 141,43", None, 141.43),
        (49.9, "6 x 47 g, Freia, pr. kg 176,95", None, 176.95),
        (26.9, "150-300 g, assortert, pr. kg 89,67-179,33", None, 89.67),
        (199.0, "Ca. 3 kg, fryst, Gilde, pr. kg", None, 199.0),
        (69.9, "400 g, Folkets", KG, 174.75),
        (89.9, "CLP 40 klar, dim, E14, Osram", None, None),
        (1299.0, "Pr. kg 1 299,00", None, 1299.0),
        (20.0, "skivet, Gilde, 140 g Enh.pris 142,86 pr. kg Førpris 39,90", None, 142.86),
        (50.3, "Gode hav, 250 g, 201,20 pr. kg", None, 201.2),
        (10.0, "Ukens Beste norske, løsvekt pr. kg Se oppskrift på joker.no", None, 10.0),
    ],
)
def test_per_kg(price: float, description: str, quantity: Quantity | None, expected: float | None) -> None:
    result = per_kg(price, description, quantity)
    assert result == pytest.approx(expected) if expected is not None else result is None


def _raw(id: str, heading: str, dealer: str = "KIWI", pre_price: float | None = None) -> RawOffer:
    return {
        "id": id,
        "heading": heading,
        "description": "700 g,\nPrior, pr. kg 141,43",
        "pricing": {"price": 99, "pre_price": pre_price},
        "quantity": None,
        "run_till": "2026-10-18T21:59:59+0000",
        "dealer": {"name": dealer},
    }


def test_parse_offer() -> None:
    offer = parse_offer(_raw("a", "KYLLINGFILET", pre_price=123))
    assert offer.store == "KIWI"
    assert offer.description == "700 g, Prior, pr. kg 141,43"
    assert offer.per_kg == pytest.approx(141.43)
    assert offer.discount == pytest.approx((123 - 99) / 123)
    assert offer.valid_until == date(2026, 10, 18)


def _catalog(id: str, dealer: str, offers: int = 2, days_left: int = 3) -> RawCatalog:
    now = datetime.now(UTC)
    return {
        "id": id,
        "dealer": {"name": dealer},
        "offer_count": offers,
        "run_from": (now - timedelta(days=1)).isoformat(),
        "run_till": (now + timedelta(days=days_left)).isoformat(),
    }


async def test_current_reads_grocery_catalogs_that_run_today() -> None:
    catalogs = [
        _catalog("kiwi", "KIWI"),
        _catalog("jysk", "JYSK"),
        _catalog("old", "REMA 1000", days_left=-1),
        _catalog("empty", "Coop Mega", offers=0),
    ]
    offers = {"kiwi": [_raw("a", "KYLLINGFILET"), _raw("b", "LAKSEFILET")]}
    asked: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.url.path)
        if request.url.path.endswith("/catalogs"):
            assert request.url.params["r_radius"] == "15000"
            return httpx2.Response(200, json=catalogs)
        return httpx2.Response(200, json=offers[request.url.params["catalog_ids"]])

    async with httpx2.AsyncClient(base_url=API, transport=httpx2.MockTransport(handle)) as client:
        source = TjekOfferSource(client, 58.97, 5.73, 15, STORES)
        found = await source.current()
    assert sorted(o.heading for o in found) == ["KYLLINGFILET", "LAKSEFILET"]
    assert asked == ["/v2/catalogs", "/v2/offers"]


async def test_current_pages_through_offers() -> None:
    page = [_raw(str(i), f"VARE {i}") for i in range(100)]

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalogs"):
            return httpx2.Response(200, json=[_catalog("kiwi", "KIWI", offers=150)])
        offset = int(request.url.params["offset"])
        return httpx2.Response(200, json=page if offset == 0 else [_raw("x", "SISTE")])

    async with httpx2.AsyncClient(base_url=API, transport=httpx2.MockTransport(handle)) as client:
        found = await TjekOfferSource(client, 58.97, 5.73, 15, STORES).current()
    assert len(found) == 101


async def test_errors_become_source_unavailable() -> None:
    transport = httpx2.MockTransport(lambda request: httpx2.Response(503))
    async with httpx2.AsyncClient(base_url=API, transport=transport) as client:
        with pytest.raises(SourceUnavailableError):
            await TjekOfferSource(client, 58.97, 5.73, 15, STORES).current()


@pytest.mark.parametrize(
    ("price", "pre_price", "description", "expected"),
    [
        (99.0, 123.0, "700 g, Prior", 123.0),
        (20.0, None, "378 g Enh.pris 52,91 pr. kg Førpris 34,90 Maks 5 pk.", 34.9),
        (39.9, None, "290-338 g, kit, Toro Før 48,9", 48.9),
        (20.0, None, "70\u2013350 g Førpris 23,90\u201335,90", 23.9),
        (50.0, None, "2 for 50, Prior", None),
        (99.0, 99.0, "", None),
        (99.0, None, "Førpris 89,90", None),
    ],
)
def test_before_price(price: float, pre_price: float | None, description: str, expected: float | None) -> None:
    assert before_price(price, pre_price, description) == expected


def test_before_price_per_kg_against_a_price_per_100_g() -> None:
    ribbe = "Pr kg 299,00. Førpris 339,00 pr kg"
    assert before_price(29.9, 339.0, ribbe, per_kg(29.9, ribbe, None)) == pytest.approx(33.9)


def test_implausible_discounts_are_ignored() -> None:
    assert before_price(20.0, 99.0, "Pr pk Førpris 99,00") is None


async def test_offers_are_read_per_catalog_every_time() -> None:
    catalogs = [_catalog("kiwi", "KIWI", offers=2), _catalog("rema", "REMA 1000", offers=1)]
    offers = {
        "kiwi": [_raw("a", "KYLLINGFILET"), _raw("b", "LAKSEFILET")],
        "rema": [_raw("c", "POTETER", dealer="REMA 1000")],
    }
    fetched: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/catalogs"):
            return httpx2.Response(200, json=catalogs)
        fetched.append(request.url.params["catalog_ids"])
        return httpx2.Response(200, json=offers[request.url.params["catalog_ids"]])

    async with httpx2.AsyncClient(base_url=API, transport=httpx2.MockTransport(handle)) as client:
        source = TjekOfferSource(client, 58.97, 5.73, 15, STORES)
        first = await source.current()
        second = await source.current()
    assert sorted(fetched) == ["kiwi", "kiwi", "rema", "rema"]  # nothing kept between runs
    assert sorted(o.heading for o in first) == sorted(o.heading for o in second) == ["KYLLINGFILET", "LAKSEFILET", "POTETER"]
