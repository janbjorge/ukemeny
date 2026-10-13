"""Build datasets/ from scratch: every recipe from matprat.no, this week's offers from mattilbud.no, and Jev's labels
for every ingredient and offer. Nothing is kept between runs. Run on a laptop, then commit datasets/ and push
(which deploys).

    uv run python -m pipeline.datasets

Needs TYPESAFE_API_KEY. The site reads only datasets/.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from typesafe_sdk import AsyncTypeSafeClient

from adapters import datasets, profile
from app import build
from core.models import RefreshReport, Snapshot
from pipeline.jev import Jev, JevIngredientClassifier, JevOfferMatcher
from pipeline.matprat import MatpratRecipeSource
from pipeline.tjek import TjekOfferSource

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
    recipes: RefreshReport
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


async def run(progress: build.Progress | None = None) -> Result:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise SetupError("TYPESAFE_API_KEY is not set. Get a TypeSafe API key at https://console.typesafe.ai")
    shopping = profile.load().shopping
    async with (
        MatpratRecipeSource.open(CRAWL_WORKERS, CRAWL_DELAY) as recipes,
        TjekOfferSource.open(shopping.lat, shopping.lng, shopping.radius_km, shopping.stores) as offers,
        AsyncTypeSafeClient(api_key=key, model=JEV_MODEL) as client,
    ):
        jev = Jev(client, max_in_flight=JEV_IN_FLIGHT)
        snapshot, report = await build.snapshot(recipes, JevIngredientClassifier(jev), offers, JevOfferMatcher(jev), progress)
    return Result(snapshot, report, datasets.write(snapshot), jev.status())


def main() -> None:
    argparse.ArgumentParser(description="Build datasets/ from scratch: matprat.no, mattilbud.no and Jev.").parse_args()
    try:
        result = asyncio.run(run(reporter(STEPS, lambda line: print(line, file=sys.stderr, flush=True))))
    except SetupError as e:
        sys.exit(f"error: {e}")
    s, r = result.snapshot, result.recipes
    print(f"matprat.no: {r.listed:,} pages, {r.failed:,} failed")
    print(f"{len(s.dishes):,} dinners, {len(s.traits):,} ingredients, {len(s.offers):,} offers, {len(s.matches):,} ingredients on offer")
    print(", ".join(f"{name} {size / 1e6:.1f} MB" for name, size in result.sizes.items()))
    print(result.jev)


if __name__ == "__main__":
    main()
