"""Build datasets/ from scratch: every recipe from matprat.no and godt.no, this week's offers from mattilbud.no, and
Jev's labels for every ingredient and offer. Nothing is kept between runs. Run on a laptop, then commit datasets/ and push
(which deploys).

    uv run python -m pipeline.datasets       # a progress bar per step, and under it the URL being fetched
    uv run python -m pipeline.datasets -v    # also Jev's cost after each Jev step, failures, retries, catalogs
    uv run python -m pipeline.datasets -vv   # also a line per page, ingredient, offer match and Jev call
    uv run python -m pipeline.datasets -vvv  # also every HTTP request

Needs TYPESAFE_API_KEY. The site reads only datasets/.
"""

import argparse
import asyncio
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from typing import Never, TextIO
from urllib.parse import urlsplit

from tqdm import tqdm
from typesafe_sdk import AsyncTypeSafeClient

from adapters import datasets
from app import build
from core.models import RefreshReport, Snapshot
from pipeline.godt import GodtRecipeSource
from pipeline.jev import Jev, JevDepartmentClassifier, JevIngredientClassifier, JevOfferMatcher
from pipeline.matprat import MatpratRecipeSource
from pipeline.tjek import TjekOfferSource

JEV_MODEL = os.environ.get("JEV_MODEL", "jev-latest")
JEV_IN_FLIGHT = 8
"""Requests to Jev at a time."""
CRAWL_WORKERS = 16
"""matprat.no: pages at a time (jb 2026-10-13: "Why no concucrent requets?"; it was 3, each followed by half a second)."""


class SetupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Result:
    snapshot: Snapshot
    recipes: RefreshReport
    sizes: dict[str, int]
    jev: str


STEPS = {
    "recipes": "matprat.no and godt.no pages",
    "ingredients": "Jev ingredient labels",
    "departments": "Jev departments",
    "catalogs": "mattilbud.no catalogs",
    "offers": "Jev offer matches",
}
"""What each step's bar is called (app.build.Progress)."""


class Bars:
    """A tqdm bar per step of the build (app.build.Progress), and under it the URL being fetched (jb 2026-10-13: "add
    tqdm and use that to track progress of the diffrent phases, also use to to how the current url getting fetched")."""

    def __init__(self, steps: Mapping[str, str], file: TextIO | None = None) -> None:
        self.steps = steps
        self.file = file
        self._bar: tqdm[Never] | None = None
        self._url: tqdm[Never] | None = None

    def __call__(self, step: str, done: int, due: int) -> None:
        if done == 0:
            self.close()
            self._bar = tqdm(desc=self.steps[step], total=due, file=self.file, dynamic_ncols=True)
        elif self._bar is not None:
            self._bar.update(done - self._bar.n)
        if done == due:
            self.close()

    def fetching(self, url: str) -> None:
        """Shows `url` on the line under the step's bar."""
        if self._bar is None:
            return
        if self._url is None:
            self._url = tqdm(bar_format="{desc}", file=self.file, dynamic_ncols=True, leave=False)
        self._url.set_description_str(url)

    def close(self) -> None:
        """The bar stays as the step's line; the URL goes."""
        if self._url is not None:
            self._url.close()
            self._url = None
        if self._bar is not None:
            self._bar.close()
            self._bar = None


class _AboveTheBars(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        tqdm.write(self.format(record), file=sys.stderr)


def configure(verbose: int) -> None:
    """Where the build's log lines go: above the bars, -v info, -vv debug for the build, -vvv debug for every library too."""
    handler = _AboveTheBars()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    logging.basicConfig(level=logging.DEBUG if verbose >= 3 else logging.WARNING, handlers=[handler], force=True)
    logging.getLogger("matris").setLevel(logging.WARNING if verbose == 0 else logging.INFO if verbose == 1 else logging.DEBUG)


async def run(progress: build.Progress | None = None, fetching: Callable[[str], None] | None = None) -> Result:
    """`fetching` hears every URL matprat.no, godt.no and mattilbud.no are asked for."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise SetupError("TYPESAFE_API_KEY is not set. Get a TypeSafe API key at https://console.typesafe.ai")
    async with (
        MatpratRecipeSource.open(CRAWL_WORKERS, fetching) as matprat,
        GodtRecipeSource.open(fetching=fetching) as godt,
        TjekOfferSource.open(fetching=fetching) as offers,
        AsyncTypeSafeClient(api_key=key, model=JEV_MODEL) as client,
    ):
        jev = Jev(client, max_in_flight=JEV_IN_FLIGHT)

        def step(name: str, done: int, due: int) -> None:
            if progress:
                progress(name, done, due)
            if done == due and name in ("departments", "ingredients", "offers"):
                logging.getLogger("matris.jev").info("so far: %s", jev.status())

        snapshot, report = await build.snapshot(
            (matprat, godt), JevDepartmentClassifier(jev), JevIngredientClassifier(jev), offers, JevOfferMatcher(jev), step
        )
    return Result(snapshot, report, datasets.write(snapshot), jev.status())


def main() -> None:
    parser = argparse.ArgumentParser(description="Build datasets/ from scratch: matprat.no, godt.no, mattilbud.no and Jev.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="more detail: -v, -vv or -vvv")
    verbose = parser.parse_args().verbose
    configure(verbose)
    try:
        with closing(Bars(STEPS)) as bars:
            result = asyncio.run(run(bars, bars.fetching))
    except SetupError as e:
        sys.exit(f"error: {e}")
    s, r = result.snapshot, result.recipes
    sites = Counter((urlsplit(d.url).hostname or "").removeprefix("www.") for d in s.dishes)
    print(f"recipes: {r.listed:,} pages, {r.failed:,} failed")
    print(
        f"{len(s.dishes):,} dinners ({', '.join(f'{site} {n:,}' for site, n in sorted(sites.items()))}), "
        f"{len(s.traits):,} ingredients, {len(s.offers):,} offers in {len(s.places)} places, {len(s.matches):,} ingredients on offer"
    )
    print(", ".join(f"{name} {size / 1e6:.1f} MB" for name, size in result.sizes.items()))
    print(result.jev)


if __name__ == "__main__":
    main()
