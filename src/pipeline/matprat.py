"""Recipes from matprat.no.

The sitemap lists every recipe page with its last change. Each page embeds its data as
Next.js page props (`__NEXT_DATA__`): ingredients with amount, unit and grocery category,
and the dish type matprat reports to analytics ("Middagsrett"). robots.txt allows
/oppskrifter/; the search API under /Services/ is disallowed, so pages are read one by one.
"""

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self, TypedDict

from core.errors import SourceUnavailableError
from core.models import Ingredient, Recipe, RecipeRef
from pipeline.pages import Pages

BASE = "https://www.matprat.no"
SITEMAP = f"{BASE}/sitemap.xml"

_RECIPE_URL = re.compile(r"^https://www\.matprat\.no/oppskrifter/[^/]+/[^/]+/$")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def parse_sitemap(xml: str) -> list[RecipeRef]:
    refs = []
    for url in ET.fromstring(xml).iter(f"{_SITEMAP_NS}url"):
        loc = (url.findtext(f"{_SITEMAP_NS}loc") or "").strip()
        if _RECIPE_URL.match(loc):
            refs.append(RecipeRef(loc, (url.findtext(f"{_SITEMAP_NS}lastmod") or "").strip()))
    return refs


def _split(value: object) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


class RawIngredient(TypedDict, total=False):
    """An ingredient in a matprat page's __NEXT_DATA__: the parts that are read."""

    preText: str | None
    middleText: str | None
    name: str | None
    postText: str | None
    postText2: str | None
    amount: float | None
    unit: str | None
    category: str | None


def _ingredient(raw: RawIngredient) -> Ingredient:
    words = [raw.get("preText"), raw.get("middleText"), raw.get("name"), raw.get("postText"), raw.get("postText2")]
    amount = raw.get("amount")
    unit = raw.get("unit") or ""
    line = " ".join(w.strip() for w in words if w and w.strip())
    if amount is not None:
        line = f"{amount:g} {unit} {line}".replace("  ", " ")
    return Ingredient(
        name=(raw.get("name") or "").strip().lower(),
        text=line,
        amount=float(amount) if amount is not None else None,
        unit=unit,
        category=raw.get("category") or "",
    )


def parse_recipe(html: str, url: str) -> Recipe | None:
    """The recipe on a matprat page, or None when the page holds no recipe."""
    match = _NEXT_DATA.search(html)
    if match is None:
        return None
    page = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("pageData") or {}
    if not page.get("isRecipe"):
        return None
    raw = page.get("ingredients") or [i for group in page.get("ingredientGroups") or [] for i in group.get("ingredients") or []]
    analytics = page.get("gtmDimensions") or {}
    return Recipe(
        url=url,
        name=page.get("name") or "",
        dish_types=_split(analytics.get("dimension8")),
        main_categories=_split(analytics.get("dimension1")),
        portions=int(page.get("portions") or 4),
        prep_time=page.get("preparationTime") or "",
        rating=page.get("ratingPrecise"),
        rating_count=int(page.get("ratingCount") or 0),
        ingredients=tuple(_ingredient(i) for i in raw if i.get("name")),
    )


@dataclass
class MatpratRecipeSource:
    """Implements core.ports.RecipeSource, at most `workers` pages at a time (pipeline.pages). matprat.no's robots.txt
    asks for no crawl delay and a page answers in about 0.2 s."""

    pages: Pages

    @classmethod
    @asynccontextmanager
    async def open(cls, workers: int = 16, fetching: Callable[[str], None] | None = None) -> AsyncGenerator[Self]:
        """`fetching` hears the URL of every request as it goes out."""
        async with Pages.open("matprat.no", workers, fetching) as pages:
            yield cls(pages)

    async def index(self) -> list[RecipeRef]:
        sitemap = await self.pages.get(SITEMAP)
        if sitemap is None:
            raise SourceUnavailableError("matprat.no", f"no sitemap at {SITEMAP}")
        return parse_sitemap(sitemap)

    async def fetch(self, url: str) -> Recipe | None:
        html = await self.pages.get(url)
        return None if html is None else parse_recipe(html, url)
