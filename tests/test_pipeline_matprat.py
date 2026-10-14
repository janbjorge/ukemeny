import json
from collections.abc import Callable

import httpx2
import pytest

from core.errors import SourceUnavailableError
from core.models import RecipeRef
from pipeline.matprat import MatpratRecipeSource, parse_recipe, parse_sitemap
from pipeline.pages import Pages

URL = "https://www.matprat.no/oppskrifter/familien/stekt-laks-med-kokosris/"

SITEMAP = f"""<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{URL}</loc><lastmod>2026-10-01</lastmod></url>
  <url><loc>https://www.matprat.no/oppskrifter/familien/s/laks/steg/steg-1/</loc></url>
  <url><loc>https://www.matprat.no/artikler/noe/</loc><lastmod>2026-10-01</lastmod></url>
</urlset>"""

INGREDIENTS: list[dict[str, object]] = [
    {
        "name": "laksefilet",
        "middleText": "skinn- og beinfri",
        "amount": 800,
        "unit": "g",
        "category": "/fisk og sjømat",
    },
    {
        "name": "rapsolje",
        "postText": "eller annen smaksnøytral matolje",
        "amount": 2,
        "unit": "ss",
        "category": "/margarin/olje/majones",
    },
    {"name": "Salt", "amount": None, "unit": None, "category": "/krydder"},
]
PAGE_DATA: dict[str, object] = {
    "isRecipe": True,
    "name": "Stekt laks med kokosris",
    "portions": 4,
    "preparationTime": "20\u201340 min",
    "ratingPrecise": 4.8,
    "ratingCount": 21,
    "gtmDimensions": {"dimension1": "Fisk og sjømat", "dimension8": "Middagsrett"},
    "ingredients": INGREDIENTS,
}


def page(data: dict[str, object]) -> str:
    props = {"props": {"pageProps": {"pageData": data}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(props)}</script>'


def test_parse_sitemap_keeps_recipe_pages() -> None:
    assert parse_sitemap(SITEMAP) == [RecipeRef(URL, "2026-10-01")]


def test_parse_recipe() -> None:
    recipe = parse_recipe(page(PAGE_DATA), URL)
    assert recipe is not None
    assert recipe.is_dinner
    assert recipe.main == "Fisk og sjømat"
    assert recipe.rating == 4.8
    laks, olje, salt = recipe.ingredients
    assert (laks.name, laks.amount, laks.unit, laks.category) == (
        "laksefilet",
        800.0,
        "g",
        "/fisk og sjømat",
    )
    assert laks.text == "800 g skinn- og beinfri laksefilet"
    assert olje.text == "2 ss rapsolje eller annen smaksnøytral matolje"
    assert (salt.name, salt.amount, salt.unit) == ("salt", None, "")


def test_parse_recipe_reads_ingredient_groups() -> None:
    grouped = PAGE_DATA | {
        "ingredients": [],
        "ingredientGroups": [{"ingredients": INGREDIENTS[:1]}],
    }
    recipe = parse_recipe(page(grouped), URL)
    assert recipe is not None and [i.name for i in recipe.ingredients] == ["laksefilet"]


def test_pages_without_a_recipe() -> None:
    assert parse_recipe("<html></html>", URL) is None
    assert parse_recipe(page({"isRecipe": False}), URL) is None


def source(handle: Callable[[httpx2.Request], httpx2.Response]) -> MatpratRecipeSource:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    return MatpratRecipeSource(Pages(client, "matprat.no", workers=2, tries=2))


async def test_fetch_and_index() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/sitemap.xml":
            return httpx2.Response(200, text=SITEMAP)
        return httpx2.Response(200, text=page(PAGE_DATA))

    matprat = source(handle)
    assert await matprat.index() == [RecipeRef(URL, "2026-10-01")]
    recipe = await matprat.fetch(URL)
    assert recipe is not None and recipe.name == "Stekt laks med kokosris"


async def test_gone_page_is_none_and_errors_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    gone = source(lambda request: httpx2.Response(404))
    assert await gone.fetch(URL) is None

    calls = 0

    def busy(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(503)

    async def no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("pipeline.pages.asyncio.sleep", no_sleep)
    with pytest.raises(SourceUnavailableError):
        await source(busy).fetch(URL)
    assert calls == 2


async def test_a_missing_sitemap_is_an_error() -> None:
    with pytest.raises(SourceUnavailableError):
        await source(lambda request: httpx2.Response(404)).index()
