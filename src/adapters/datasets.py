"""The snapshot on disk: datasets/*.json, written by the offline build and read by the site at start-up.

dishes.json holds the facts the rules need from each matprat.no and godt.no dinner, per portion, without its wording
(docs/plan-web.md); traits.json is the vocabulary, kept and fixed by hand, which a build adds a row to for each new name;
offers.json changes every week, and also says which catalogs reach each place (`places`).
"""

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from sys import intern
from typing import NotRequired, TypedDict

import orjson

from core.diet import GRAMS_PER_UNIT
from core.dishes import ROUND_PIECES
from core.models import Dish, Offer, Part, Snapshot, Traits
from core.units import counted

DATASETS = Path(__file__).parents[2] / "datasets"


# The shapes of the files, as written by `write`
class PartJSON(TypedDict):
    name: str
    category: str
    grams: float | None
    unit: str
    form: NotRequired[str]
    """Missing in dishes.json from before 2026-10-22."""
    pieces: NotRequired[float | None]
    """Missing in dishes.json from before 2026-10-24: then read from `grams` and the rough table (`_pieces`)."""


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
    size: NotRequired[float | None]
    """Missing in offers.json from before 2026-10-24, as are `size_to`, `unit` and `pieces`: then the catalog said nothing."""
    size_to: NotRequired[float | None]
    unit: NotRequired[str]
    pieces: NotRequired[int]


_JSON = orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE | orjson.OPT_SORT_KEYS


class JsonDatasets:
    """Implements core.ports.Datasets. Read once at start-up; the files only change on deploy."""

    def __init__(self, root: Path = DATASETS) -> None:
        # One file at a time, each let go before the next is read, and one copy of each ingredient name and department:
        # 7 MiB less on the 256 MB machine than all three at once (2026-10-14, FACTS.md §7)
        dishes = tuple(_dish(d) for d in orjson.loads((root / "dishes.json").read_bytes()))
        traits = {intern(name): Traits.of(t) for name, t in orjson.loads((root / "traits.json").read_bytes()).items()}
        offers = orjson.loads((root / "offers.json").read_bytes())
        self._snapshot = Snapshot(
            built=datetime.fromisoformat(offers["built"]),
            dishes=dishes,
            traits=traits,
            offers=tuple(_offer(o) for o in offers["offers"]),
            matches={intern(name): tuple(ids) for name, ids in offers["matches"].items()},
            places={place: tuple(ids) for place, ids in offers.get("places", {}).items()},
            served={url: {intern(name): tuple(ids) for name, ids in found.items()} for url, found in offers.get("served", {}).items()},
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
            "served": {url: {name: list(ids) for name, ids in found.items()} for url, found in snapshot.served.items()},
        },
    }
    sizes = {}
    for name, document in documents.items():
        data = orjson.dumps(document, option=_JSON)
        (root / name).write_bytes(data)
        sizes[name] = len(data)
    return sizes


def _pieces(p: PartJSON) -> float | None:
    """Part.pieces as written, or for a file from before it, back out of the grams the rough table made of the pieces:
    «2 stk» for four, 50 g, is 0.5 at 100 g a stk; a unit the table lacks (potte) gives None."""
    if "pieces" in p:
        return p["pieces"]
    per_unit = GRAMS_PER_UNIT.get(p["unit"])
    if p["grams"] is None or per_unit is None or not counted(p["unit"]):
        return None
    return round(p["grams"] / per_unit, ROUND_PIECES)


def _dish(d: DishJSON) -> Dish:
    return Dish(
        url=d["url"],
        name=d["name"],
        portions=d["portions"],
        prep_time=intern(d["prep_time"]),
        rating=d["rating"],
        rating_count=d["rating_count"],
        parts=tuple(
            Part(intern(p["name"]), intern(p["category"]), p["grams"], intern(p["unit"]), intern(p.get("form", "")), _pieces(p))
            for p in d["parts"]
        ),
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
        size=o.get("size"),
        size_to=o.get("size_to"),
        unit=intern(o.get("unit", "")),
        pieces=o.get("pieces", 1),
    )
