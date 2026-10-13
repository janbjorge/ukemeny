"""Build datasets/ with Jev. Run on a laptop, then commit datasets/ and push (which deploys).

    uv run python -m pipeline.datasets            # this week's offers and any new ingredients
    uv run python -m pipeline.datasets --refresh  # also new and changed recipes from matprat.no

Needs TYPESAFE_API_KEY. Caches live in data/ (gitignored): the recipes and Jev's answers in
data/matris.sqlite3, the offers per catalog in data/tjek/. The site reads only datasets/.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient

from adapters import datasets, profile
from app import build
from core.models import RefreshReport, Snapshot
from pipeline.jev import Jev, JevIngredientClassifier, JevOfferMatcher
from pipeline.matprat import MatpratRecipeSource
from pipeline.store import Sqlite, SqliteOfferMatchStore, SqliteRecipeStore, SqliteTraitsStore
from pipeline.tjek import TjekOfferSource

DATA = Path(os.environ.get("MATRIS_DATA", Path(__file__).parents[2] / "data"))
JEV_MODEL = os.environ.get("JEV_MODEL", "jev-latest")
JEV_IN_FLIGHT = 8
"""Requests to Jev at a time."""
CRAWL_WORKERS, CRAWL_DELAY = 3, 0.5
"""matprat.no: at most 3 pages at a time, each followed by half a second."""


class SetupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Result:
    snapshot: Snapshot
    refreshed: RefreshReport | None
    sizes: dict[str, int]
    jev: str


STEPS = {
    "recipes": "matprat.no: {due} pages to fetch",
    "ingredients": "Jev: {due} ingredients to label",
    "catalogs": "mattilbud.no: reading this week's catalogs",
    "offers": "Jev: {due} ingredients to match with offers",
}
"""What each step of the build says as it starts (app.build.Progress)."""


def reporter(steps: Mapping[str, str], echo: Callable[[str], None]) -> build.Progress:
    """Light output: a line as each step starts, then done/due about every tenth."""

    def report(step: str, done: int, due: int) -> None:
        if done == 0:
            echo(steps[step].format(due=f"{due:,}"))
        elif due > 1 and (done == due or done % max(1, due // 10) == 0):
            echo(f"  {done:,}/{due:,}")

    return report


async def run(refresh: bool = False, limit: int | None = None, progress: build.Progress | None = None) -> Result:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise SetupError("TYPESAFE_API_KEY is not set. Get a TypeSafe API key at https://console.typesafe.ai")
    shopping = profile.load().shopping
    async with (
        Sqlite.open(DATA / "matris.sqlite3") as db,
        MatpratRecipeSource.open(CRAWL_WORKERS, CRAWL_DELAY) as recipes,
        TjekOfferSource.open(shopping.lat, shopping.lng, shopping.radius_km, shopping.stores, DATA / "tjek") as offers,
        AsyncTypeSafeClient(api_key=key, model=JEV_MODEL) as client,
    ):
        store = SqliteRecipeStore(db)
        pages = (lambda done, due: progress("recipes", done, due)) if progress else None
        refreshed = await build.refresh(recipes, store, limit, pages) if refresh else None
        jev = Jev(client, max_in_flight=JEV_IN_FLIGHT)
        snapshot = await build.snapshot(
            store, SqliteTraitsStore(db), JevIngredientClassifier(jev), offers, SqliteOfferMatchStore(db), JevOfferMatcher(jev), progress
        )
    return Result(snapshot, refreshed, datasets.write(snapshot), jev.status())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="also fetch new and changed recipes from matprat.no")
    args = parser.parse_args()

    try:
        result = asyncio.run(run(args.refresh, progress=reporter(STEPS, lambda line: print(line, file=sys.stderr, flush=True))))
    except SetupError as e:
        sys.exit(f"error: {e}")
    s = result.snapshot
    if result.refreshed:
        r = result.refreshed
        print(f"matprat.no: {r.listed:,} recipes listed, {r.fetched:,} fetched, {r.failed:,} failed")
    print(f"{len(s.dishes):,} dinners, {len(s.traits):,} ingredients, {len(s.offers):,} offers, {len(s.matches):,} ingredients on offer")
    print(", ".join(f"{name} {size / 1e6:.1f} MB" for name, size in result.sizes.items()))
    print(result.jev)


if __name__ == "__main__":
    main()
