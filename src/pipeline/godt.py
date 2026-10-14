"""Recipes from godt.no.

The recipe sitemap lists every recipe page with its last change. Each page embeds its data as Next.js page props
(`__NEXT_DATA__`): ingredients with amount and unit, portions, minutes, rating, and tags, where «Middag» marks a dinner.
godt.no names no grocery department, so the build gives each ingredient one (app.build.fill_departments). robots.txt asks
for no crawl delay and shuts out only a list of AI crawlers (GPTBot, ClaudeBot, CCBot, ...), which matris is not.

godt.no is behind AWS WAF. Read 8 at a time on 2026-10-14, it served 2 681 pages in about 70 s and answered the other
1 215 with a challenge (202, no body, `x-amzn-waf-action: challenge`), and still did minutes later. So the pages are
read at most PER_SECOND a second, and a challenge counts as a failed page.
"""

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self, TypedDict

from core.errors import SourceUnavailableError
from core.models import DINNER, Ingredient, Recipe, RecipeRef
from pipeline.pages import Pages

BASE = "https://www.godt.no"
SITEMAP = f"{BASE}/sitemap-recipes.xml"
DINNER_TAG = "middag"
PER_SECOND = 4
"""Pages a second: 3 896 pages in about 16 minutes, about as long as matprat.no's crawl."""

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
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def parse_sitemap(xml: str) -> list[RecipeRef]:
    refs = []
    for url in ET.fromstring(xml).iter(f"{_SITEMAP_NS}url"):
        loc = (url.findtext(f"{_SITEMAP_NS}loc") or "").strip()
        if _RECIPE_URL.match(loc):
            refs.append(RecipeRef(loc, (url.findtext(f"{_SITEMAP_NS}lastmod") or "").strip()))
    return refs


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

    @classmethod
    @asynccontextmanager
    async def open(cls, workers: int = 4, fetching: Callable[[str], None] | None = None) -> AsyncGenerator[Self]:
        """`fetching` hears the URL of every request as it goes out."""
        async with Pages.open("godt.no", workers, fetching, per_second=PER_SECOND) as pages:
            yield cls(pages)

    async def index(self) -> list[RecipeRef]:
        sitemap = await self.pages.get(SITEMAP)
        if sitemap is None:
            raise SourceUnavailableError("godt.no", f"no sitemap at {SITEMAP}")
        return parse_sitemap(sitemap)

    async def fetch(self, url: str) -> Recipe | None:
        html = await self.pages.get(url)
        return None if html is None else parse_recipe(html, url)
