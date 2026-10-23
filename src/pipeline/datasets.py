"""Build datasets/: every recipe from matprat.no and godt.no, this week's offers from mattilbud.no, and Jev's offer
matches, from scratch; and a row in the vocabulary (traits.json) for each ingredient name it has not seen, drafted by Jev
once. The vocabulary is the one thing kept between runs; it is fixed by hand, never rebuilt. Run on a laptop, review
`git diff datasets/traits.json`, then commit datasets/ and push (which deploys).

    uv run python -m pipeline.datasets       # a progress bar per step, and under it the URL being fetched
    uv run python -m pipeline.datasets -v    # also Jev's cost after each Jev step, failures, retries, catalogs
    uv run python -m pipeline.datasets -vv   # also a line per page, ingredient, offer match and Jev call
    uv run python -m pipeline.datasets -vvv  # also every HTTP request
    uv run python -m pipeline.datasets --known  # godt.no's pages from the dinners in datasets/, not its list
    uv run python -m pipeline.datasets --offers  # only this week's offers and their matches, for the dinners in datasets/

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
from pathlib import Path
from typing import Never, TextIO
from urllib.parse import urlsplit

from tqdm import tqdm
from typesafe_sdk import AsyncTypeSafeClient

from adapters import datasets
from app import build
from core.models import RefreshReport, Snapshot, Traits
from pipeline.godt import BASE as GODT
from pipeline.godt import GodtRecipeSource
from pipeline.jev import Jev, JevCategoryClassifier, JevIngredientClassifier, JevOfferMatcher
from pipeline.matprat import MatpratRecipeSource
from pipeline.tjek import TjekOfferSource

JEV_MODEL = os.environ.get("JEV_MODEL", "jev-1.14.0")
"""Pinned (jb 2026-10-22: "lets pin to jev-1.14.0"): jev-latest moved from 1.13.0 to 1.14.0 under a build, which changed a
label of 596 names. JEV_MODEL in the environment names another, for a relabel on purpose (METHOD.md §2)."""
JEV_IN_FLIGHT = 8
"""Requests to Jev at a time."""
CRAWL_WORKERS = 16
"""matprat.no: pages at a time (jb 2026-10-13: "Why no concucrent requets?"; it was 3, each followed by half a second)."""


class SetupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Result:
    snapshot: Snapshot
    recipes: RefreshReport | None
    """None when only the offers were refreshed."""
    sizes: dict[str, int]
    jev: str
    drafted: tuple[str, ...] = ()
    """The names the vocabulary got a row for in this build: review them in `git diff datasets/traits.json`."""


STEPS = {
    "recipes": "matprat.no and godt.no pages",
    "categories": "Jev categories for new names",
    "ingredients": "Jev facts for new names",
    "catalogs": "mattilbud.no catalogs",
    "offers": "Jev offer matches",
}
"""What each step's bar is called (app.build.Progress)."""


class Bars:
    """A tqdm bar per step of the build (app.build.Progress), and under it the URL being fetched (jb 2026-10-13: "add
    tqdm and use that to track progress of the diffrent phases, also use to to how the current url getting fetched").
    ASCII bars (jb 2026-10-19: "Make sure we are ascii first in all our tools")."""

    def __init__(self, steps: Mapping[str, str], file: TextIO | None = None) -> None:
        self.steps = steps
        self.file = file
        self._bar: tqdm[Never] | None = None
        self._url: tqdm[Never] | None = None

    def __call__(self, step: str, done: int, due: int) -> None:
        if done == 0:
            self.close()
            self._bar = tqdm(desc=self.steps[step], total=due, file=self.file, dynamic_ncols=True, ascii=True)
        elif self._bar is not None:
            self._bar.update(done - self._bar.n)
        if done == due:
            self.close()

    def fetching(self, url: str) -> None:
        """Shows `url` on the line under the step's bar."""
        if self._bar is None:
            return
        if self._url is None:
            self._url = tqdm(bar_format="{desc}", file=self.file, dynamic_ncols=True, leave=False, ascii=True)
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


def known_godt(root: Path = datasets.DATASETS) -> tuple[str, ...]:
    """The godt.no dinners in datasets/, whose pages a build with --known reads again, instead of the dinner list
    (jb: "we need some kind of refresh option that uses the dishes we know allready")."""
    try:
        dishes = datasets.JsonDatasets(root).snapshot().dishes
    except FileNotFoundError as e:
        raise SetupError(f"--known reads {root}, which is missing: {e}") from e
    urls = tuple(d.url for d in dishes if d.url.startswith(GODT))
    if not urls:
        raise SetupError(f"--known found no godt.no dinners in {root}")
    return urls


def vocabulary(root: Path = datasets.DATASETS) -> Mapping[str, Traits]:
    """The vocabulary in datasets/, which a build reads and adds to, never rebuilds (FACTS.md §4)."""
    try:
        return datasets.JsonDatasets(root).snapshot().traits
    except FileNotFoundError as e:
        raise SetupError(f"the vocabulary in {root} is missing: {e}") from e


def _key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise SetupError("TYPESAFE_API_KEY is not set. Get a TypeSafe API key at https://console.typesafe.ai")
    return key


def _reporting(jev: Jev, progress: build.Progress | None) -> build.Progress:
    """`progress`, and Jev's cost so far after each Jev step (-v)."""

    def step(name: str, done: int, due: int) -> None:
        if progress:
            progress(name, done, due)
        if done == due and name in ("categories", "ingredients", "offers"):
            logging.getLogger("matris.jev").info("so far: %s", jev.status())

    return step


async def offers(progress: build.Progress | None = None, fetching: Callable[[str], None] | None = None) -> Result:
    """Only this week's offers and their matches, for the dinners and traits in datasets/ (app.build.reprice): no recipe
    page is read and no ingredient labelled again. `fetching` hears every URL mattilbud.no is asked for."""
    key = _key()
    try:
        base = datasets.JsonDatasets().snapshot()
    except FileNotFoundError as e:
        raise SetupError(f"--offers reads {datasets.DATASETS}, which is missing: {e}") from e
    async with (
        TjekOfferSource.open(fetching=fetching) as tjek,
        AsyncTypeSafeClient(api_key=key, model=JEV_MODEL) as client,
    ):
        jev = Jev(client, max_in_flight=JEV_IN_FLIGHT)
        snapshot = await build.reprice(base, tjek, JevOfferMatcher(jev), _reporting(jev, progress))
    return Result(snapshot, None, datasets.write(snapshot), jev.status())


async def run(progress: build.Progress | None = None, fetching: Callable[[str], None] | None = None, known: bool = False) -> Result:
    """`fetching` hears every URL matprat.no, godt.no and mattilbud.no are asked for. `known`: godt.no's pages are the
    dinners already in datasets/ (known_godt), not its dinner list's. The vocabulary in datasets/ is read first and
    written back with a row per new name (Result.drafted)."""
    key = _key()
    kept = vocabulary()
    godt_pages = known_godt() if known else ()
    async with (
        MatpratRecipeSource.open(CRAWL_WORKERS, fetching) as matprat,
        GodtRecipeSource.open(fetching=fetching, known=godt_pages) as godt,
        TjekOfferSource.open(fetching=fetching) as tjek,
        AsyncTypeSafeClient(api_key=key, model=JEV_MODEL) as client,
    ):
        jev = Jev(client, max_in_flight=JEV_IN_FLIGHT)
        snapshot, report = await build.snapshot(
            (matprat, godt),
            kept,
            JevCategoryClassifier(jev),
            JevIngredientClassifier(jev),
            tjek,
            JevOfferMatcher(jev),
            _reporting(jev, progress),
        )
    drafted = tuple(name for name in snapshot.traits if name not in kept)
    return Result(snapshot, report, datasets.write(snapshot), jev.status(), drafted)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build datasets/ from scratch: matprat.no, godt.no, mattilbud.no and Jev.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="more detail: -v, -vv or -vvv")
    only = parser.add_mutually_exclusive_group()
    only.add_argument("--known", action="store_true", help="godt.no: read the dinners in datasets/, not the dinner list")
    only.add_argument("--offers", action="store_true", help="only this week's offers and matches, for the dinners in datasets/")
    args = parser.parse_args()
    configure(args.verbose)
    try:
        with closing(Bars(STEPS)) as bars:
            result = asyncio.run(offers(bars, bars.fetching) if args.offers else run(bars, bars.fetching, args.known))
    except SetupError as e:
        sys.exit(f"error: {e}")
    s, r = result.snapshot, result.recipes
    sites = Counter((urlsplit(d.url).hostname or "").removeprefix("www.") for d in s.dishes)
    if r:
        print(f"recipes: {r.listed:,} pages, {r.failed:,} failed")
        print(f"vocabulary: {len(result.drafted):,} new names drafted by Jev: {', '.join(result.drafted) or 'none'}")
    print(
        f"{len(s.dishes):,} dinners ({', '.join(f'{site} {n:,}' for site, n in sorted(sites.items()))}), "
        f"{len(s.traits):,} ingredients, {len(s.offers):,} offers in {len(s.places)} places, "
        f"{len(s.matches):,} ingredients and {len(s.served):,} dinners' meat or fish on offer"
    )
    print(", ".join(f"{name} {size / 1e6:.1f} MB" for name, size in result.sizes.items()))
    print(result.jev)


if __name__ == "__main__":
    main()
