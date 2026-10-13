"""The snapshot on disk: datasets/*.json, written by the offline build and read by the site at start-up.

dishes.json holds the facts the rules need from each matprat dinner, per portion, without its wording (docs/plan-web.md);
traits.json changes when new ingredients appear; offers.json every week.
"""

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import orjson

from core.models import Dish, Ingredient, Offer, Part, Recipe, Snapshot, Traits

DATASETS = Path(__file__).parents[2] / "datasets"
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
        )

    def snapshot(self) -> Snapshot:
        return self._snapshot


def write(snapshot: Snapshot, root: Path = DATASETS) -> dict[str, int]:
    """Write the snapshot, formatted like `jq .` so diffs show what changed. Returns bytes per file."""
    root.mkdir(parents=True, exist_ok=True)
    documents: Mapping[str, Any] = {
        "dishes.json": [asdict(d) for d in snapshot.dishes],
        "traits.json": {name: t.levels() for name, t in snapshot.traits.items()},
        "offers.json": {
            "built": snapshot.built.isoformat(),
            "offers": [asdict(o) for o in snapshot.offers],
            "matches": {name: list(ids) for name, ids in snapshot.matches.items()},
        },
    }
    sizes = {}
    for name, document in documents.items():
        data = orjson.dumps(document, option=_JSON)
        (root / name).write_bytes(data)
        sizes[name] = len(data)
    return sizes


def recipe_from_dict(r: dict[str, Any]) -> Recipe:
    """A full recipe, as the offline build caches it (src/pipeline/store.py). Never in datasets/."""
    return Recipe(
        url=r["url"],
        name=r["name"],
        dish_types=tuple(r["dish_types"]),
        main_categories=tuple(r["main_categories"]),
        portions=r["portions"],
        prep_time=r["prep_time"],
        rating=r["rating"],
        rating_count=r["rating_count"],
        ingredients=tuple(Ingredient(i["name"], i["text"], i["amount"], i["unit"], i["category"]) for i in r["ingredients"]),
    )


def _dish(d: dict[str, Any]) -> Dish:
    return Dish(
        url=d["url"],
        name=d["name"],
        portions=d["portions"],
        prep_time=d["prep_time"],
        rating=d["rating"],
        rating_count=d["rating_count"],
        parts=tuple(Part(p["name"], p["category"], p["grams"], p["unit"]) for p in d["parts"]),
    )


def _offer(o: dict[str, Any]) -> Offer:
    return Offer(
        id=o["id"],
        store=o["store"],
        heading=o["heading"],
        description=o["description"],
        price=o["price"],
        pre_price=o["pre_price"],
        per_kg=o["per_kg"],
        valid_until=date.fromisoformat(o["valid_until"]),
    )
