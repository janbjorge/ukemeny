"""Recipes from godt.no.

The dinner list at /oppskrifter/middag pages every dinner (24 a page; 1 456 on 2026-10-22). The recipe sitemap
(`/sitemap-recipes.xml`, and `/sitemap-index.xml`, which robots.txt still names) is 404 since 2026-10-22. Each recipe
page embeds its data as Next.js page props (`__NEXT_DATA__`): ingredients with amount and unit, portions, minutes,
rating, and tags, where «Middag» marks a dinner. godt.no names no grocery department, so the build gives each
ingredient one (app.build.fill_departments). robots.txt asks for no crawl delay and shuts out only a list of AI
crawlers (GPTBot, ClaudeBot, CCBot, ...), which matris is not.

godt.no is behind AWS WAF. Read 8 at a time on 2026-10-14, it served 2 681 pages in about 70 s and answered the other
1 215 with a challenge (202, no body, `x-amzn-waf-action: challenge`), and still did minutes later. So the pages are
read at most PER_SECOND a second, and a challenge counts as a failed page.
"""

import json
import re
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self, TypedDict

from core.errors import SourceUnavailableError
from core.models import DINNER, Ingredient, Recipe, RecipeRef
from pipeline.pages import Pages

BASE = "https://www.godt.no"
LISTING = f"{BASE}/oppskrifter/middag"
"""Every dinner, 24 a page. The build keeps only dinners (app.build.recipes), and the whole catalog is 3 902 pages."""
DINNER_TAG = "middag"
PER_SECOND = 4
"""Pages a second. 1 456 dinner pages at this rate is about 6 minutes; the old full catalog (3 896) was about 16."""

UNITS: Mapping[str, str] = {
    "stykker": "stk",
    "fedd": "båt",
    "skive(r)": "skive",
    "plate(r)": "plate",
    "bokser": "boks",
    "bunter": "bunt",
    "kvister": "kvist",
    "stilker": "stilk",
    "kvaster": "kvast",
    "bl": "blad",
    "litt": "",
}
"""godt.no's units in matprat's words, which core.diet.GRAMS_PER_UNIT and the rules know."""

_RECIPE_URL = re.compile(r"^https://www\.godt\.no/oppskrifter/(?:[^/]+/)*\d+/[^/]+$")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def parse_listing(html: str) -> tuple[list[RecipeRef], int, int]:
    """Recipe pages on one list page, how many the list has, and how many a page holds.

    `changes.updated` is the old sitemap `lastmod`. A link that is not a recipe page is left out. Raises ValueError
    when the page has no list.
    """
    match = _NEXT_DATA.search(html)
    if match is None:
        raise ValueError("no page data")
    recipes = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("recipes") or {}
    pagination = recipes.get("pagination") or {}
    try:
        total, size = int(pagination["total"]), int(pagination["size"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("no pagination") from e
    refs: list[RecipeRef] = []
    for item in recipes.get("items") or []:
        links = item.get("links") if isinstance(item, dict) else None
        if not isinstance(links, dict):
            continue
        path = str(links.get("relativeUrl") or "")
        loc = path if path.startswith("https://") else f"{BASE}{path}" if path.startswith("/") else ""
        if not _RECIPE_URL.match(loc):
            continue
        changes = item.get("changes")
        updated = str(changes.get("updated") or "") if isinstance(changes, dict) else ""
        refs.append(RecipeRef(loc, updated))
    return refs, total, size


def prep_time(minutes: int) -> str:
    """matprat's bucket for godt.no's minutes: "Under 20 min", "20-40 min", "40-60 min" or "Over 60 min" (with an en
    dash, as matprat writes them). A bucket holds its upper end, so 20 minutes is "20-40 min" and 60 is "40-60 min"."""
    if not minutes:
        return ""
    if minutes < 20:
        return "Under 20 min"
    if minutes <= 40:
        return "20\u201340 min"
    if minutes <= 60:
        return "40\u201360 min"
    return "Over 60 min"


class RawIngredient(TypedDict, total=False):
    """An ingredient in a godt.no page's __NEXT_DATA__: the parts that are read."""

    name: str | None
    amount: float | None
    maxAmount: float | None
    """The upper end of «1 - 2 ss»."""
    unit: str | None
    description: str | None


def _ingredient(raw: RawIngredient) -> Ingredient:
    name = (raw.get("name") or "").strip().lower()
    low, high = raw.get("amount"), raw.get("maxAmount")
    written = (raw.get("unit") or "").strip().lower()
    unit = UNITS.get(written, written)
    if low is None:
        amount, line = None, name
    elif high:
        amount, line = (low + high) / 2, f"{low:g}-{high:g} {written} {name}"
    else:
        amount, line = float(low), f"{low:g} {written} {name}"
    line = line.replace("  ", " ")
    if description := (raw.get("description") or "").strip():
        line = f"{line}, {description}"
    return Ingredient(name=name, text=line, amount=amount, unit=unit, category="")


def parse_recipe(html: str, url: str) -> Recipe | None:
    """The recipe on a godt.no page, or None when the page holds no recipe."""
    match = _NEXT_DATA.search(html)
    if match is None:
        return None
    recipe = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("recipe") or {}
    items = recipe.get("items") or {}
    props = recipe.get("clientProperties") or {}
    name = (((items.get("recipe-top") or {}).get("data") or {}).get("title") or {}).get("value") or ""
    if not name.strip():
        return None
    raw = [i for item in items.values() if item.get("type") == "ingredient-group" for i in item.get("ingredients") or []]
    tags = props.get("tags") or []
    rating = props.get("rating") or {}
    votes = int(rating.get("votes") or 0)
    minutes = sum(int(props.get(key) or 0) for key in ("preCookTime", "cookingTime", "postCookTime"))
    return Recipe(
        url=url,
        name=name.strip(),
        dish_types=(DINNER,) if any(t.get("slug") == DINNER_TAG for t in tags) else (),
        main_categories=tuple(t.get("title") or "" for t in tags if t.get("isPrimary")),
        portions=int((items.get("portions-select") or {}).get("defaultValue") or 4),
        prep_time=prep_time(minutes),
        rating=rating.get("rating") if votes else None,
        rating_count=votes,
        ingredients=tuple(_ingredient(i) for i in raw if (i.get("name") or "").strip()),
    )


@dataclass
class GodtRecipeSource:
    """Implements core.ports.RecipeSource, at most `workers` pages at a time (pipeline.pages). A page answered in about
    0.25 s (2026-10-14)."""

    pages: Pages
    known: tuple[str, ...] = ()
    """The pages to read instead of the dinner list's: the godt.no dinners already in datasets/ (pipeline.datasets
    --known). Dinners added on godt.no since that file was written are missed."""

    @classmethod
    @asynccontextmanager
    async def open(cls, workers: int = 4, fetching: Callable[[str], None] | None = None, known: Sequence[str] = ()) -> AsyncGenerator[Self]:
        """`fetching` hears the URL of every request as it goes out."""
        async with Pages.open("godt.no", workers, fetching, per_second=PER_SECOND) as pages:
            yield cls(pages, tuple(known))

    async def index(self) -> list[RecipeRef]:
        if self.known:
            return [RecipeRef(url, "") for url in self.known]
        found: dict[str, RecipeRef] = {}
        page = 1
        expected = 0
        while True:
            url = f"{LISTING}?page={page}"
            html = await self.pages.get(url)
            if html is None:
                raise SourceUnavailableError("godt.no", f"no recipe list at {url}")
            try:
                refs, total, size = parse_listing(html)
            except ValueError as e:
                raise SourceUnavailableError("godt.no", f"recipe list at {url}: {e}") from e
            if page == 1:
                expected = total  # Later pages under-counted on 2026-10-22 (METHOD.md §7).
            for ref in refs:
                found.setdefault(ref.url, ref)
            if page == 1 and not found:
                raise SourceUnavailableError("godt.no", f"empty recipe list at {url}")
            if not refs or size < 1 or page * size >= expected:
                break
            page += 1
        if len(found) < expected:
            raise SourceUnavailableError("godt.no", f"recipe list has {len(found)} of {expected}")
        return list(found.values())

    async def fetch(self, url: str) -> Recipe | None:
        html = await self.pages.get(url)
        return None if html is None else parse_recipe(html, url)
