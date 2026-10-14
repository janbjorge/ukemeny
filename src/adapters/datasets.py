"""The snapshot on disk: datasets/*.json, written by the offline build and read by the site at start-up.

dishes.json holds the facts the rules need from each matprat.no and godt.no dinner, per portion, without its wording
(docs/plan-web.md); traits.json changes when new ingredients appear; offers.json every week. offers.json also says which
catalogs reach each place (`places`).
"""

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import NotRequired, TypedDict

import orjson

from core.models import Dish, Offer, Part, Snapshot, Traits

DATASETS = Path(__file__).parents[2] / "datasets"


# The shapes of the files, as written by `write`
class PartJSON(TypedDict):
    name: str
    category: str
    grams: float | None
    unit: str


class DishJSON(TypedDict):
    url: str
    name: str
    portions: int
    prep_time: str
    rating: float | None
    rating_count: int
    parts: list[PartJSON]


class OfferJSON(TypedDict):
    id: str
    store: str
    catalog: NotRequired[str]
    """Missing in offers.json from before places (2026-10-13), as is `places`: then no place is known."""
    heading: str
    description: str
    price: float
    pre_price: float | None
    per_kg: float | None
    valid_until: str


FILES = ("dishes.json", "traits.json", "offers.json")
_JSON = orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE | orjson.OPT_SORT_KEYS


class JsonDatasets:
    """Implements core.ports.Datasets. Read once at start-up; the files only change on deploy."""

    def __init__(self, root: Path = DATASETS) -> None:
        raw = {name: orjson.loads((root / name).read_bytes()) for name in FILES}
        self._snapshot = Snapshot(
            built=datetime.fromisoformat(raw["offers.json"]["built"]),
            dishes=tuple(_dish(d) for d in raw["dishes.json"]),
            traits={name: Traits.of(t) for name, t in raw["traits.json"].items()},
            offers=tuple(_offer(o) for o in raw["offers.json"]["offers"]),
            matches={name: tuple(ids) for name, ids in raw["offers.json"]["matches"].items()},
            places={place: tuple(ids) for place, ids in raw["offers.json"].get("places", {}).items()},
        )

    def snapshot(self) -> Snapshot:
        return self._snapshot


def write(snapshot: Snapshot, root: Path = DATASETS) -> dict[str, int]:
    """Write the snapshot, formatted like `jq .` so diffs show what changed. Returns bytes per file."""
    root.mkdir(parents=True, exist_ok=True)
    documents: Mapping[str, object] = {
        "dishes.json": [asdict(d) for d in snapshot.dishes],
        "traits.json": {name: t.levels() for name, t in snapshot.traits.items()},
        "offers.json": {
            "built": snapshot.built.isoformat(),
            "offers": [asdict(o) for o in snapshot.offers],
            "matches": {name: list(ids) for name, ids in snapshot.matches.items()},
            "places": {place: list(ids) for place, ids in snapshot.places.items()},
        },
    }
    sizes = {}
    for name, document in documents.items():
        data = orjson.dumps(document, option=_JSON)
        (root / name).write_bytes(data)
        sizes[name] = len(data)
    return sizes


def _dish(d: DishJSON) -> Dish:
    return Dish(
        url=d["url"],
        name=d["name"],
        portions=d["portions"],
        prep_time=d["prep_time"],
        rating=d["rating"],
        rating_count=d["rating_count"],
        parts=tuple(Part(p["name"], p["category"], p["grams"], p["unit"]) for p in d["parts"]),
    )


def _offer(o: OfferJSON) -> Offer:
    return Offer(
        id=o["id"],
        store=o["store"],
        catalog=o.get("catalog", ""),
        heading=o["heading"],
        description=o["description"],
        price=o["price"],
        pre_price=o["pre_price"],
        per_kg=o["per_kg"],
        valid_until=date.fromisoformat(o["valid_until"]),
    )
