import json
from collections.abc import Callable

import httpx2
import pytest

from core.errors import SourceUnavailableError
from core.models import RecipeRef
from pipeline.godt import GodtRecipeSource, parse_listing, parse_recipe, prep_time
from pipeline.pages import Pages

URL = "https://www.godt.no/oppskrifter/suppe/9662/tomatsuppe"


def card(path: str, updated: str = "2026-10-13T13:29:42.000Z") -> dict[str, object]:
    return {"links": {"relativeUrl": path}, "changes": {"updated": updated}}


def listing(items: list[dict[str, object]], total: int, size: int = 2) -> str:
    props = {"props": {"pageProps": {"recipes": {"items": items, "pagination": {"total": total, "page": 1, "size": size}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(props)}</script>'


INGREDIENTS: list[dict[str, object]] = [
    {"amount": 1, "description": None, "id": "1319", "maxAmount": None, "name": "løk", "unit": "stk"},
    {"amount": 2, "description": None, "id": "1315", "maxAmount": None, "name": "hvitløk", "unit": "fedd"},
    {"amount": 1, "description": None, "id": "1346", "maxAmount": 2, "name": "tomatpuré", "unit": "ss"},
    {"amount": 500, "description": "gode, modne plomme- eller klasetomater", "id": "1596", "maxAmount": None, "name": "tomat", "unit": "g"},
]
SERVING: list[dict[str, object]] = [
    {"amount": None, "description": "revet", "id": "1226", "maxAmount": None, "name": "Parmesan", "unit": ""},
    {"amount": None, "description": None, "id": "1", "maxAmount": None, "name": " ", "unit": "litt"},
]
RECIPE: dict[str, object] = {
    "id": "9662",
    "items": {
        "recipe-top": {"type": "recipe-top", "data": {"title": {"value": "Hjemmelaget tomatsuppe"}}},
        "portions-select": {"type": "portions-select", "defaultValue": 4, "portionUnit": "PORSJONER"},
        "ingredients-group-57121": {"type": "ingredient-group", "heading": "", "ingredients": INGREDIENTS},
        "ingredients-group-57122": {"type": "ingredient-group", "heading": "Til servering", "ingredients": SERVING},
    },
    "clientProperties": {
        "metaTitle": "Tomatsuppe - Hjemmelaget, rask og skikkelig god",
        "cookingTime": 35,
        "preCookTime": None,
        "postCookTime": None,
        "rating": {"rating": 4.1375, "votes": 80},
        "tags": [
            {"id": "8", "title": "Middag", "slug": "middag", "isPrimary": False},
            {"id": "25", "title": "Suppe", "slug": "suppe", "isPrimary": True},
        ],
    },
}


def page(recipe: dict[str, object]) -> str:
    props = {"props": {"pageProps": {"recipe": recipe}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(props)}</script>'


def with_props(**changes: object) -> dict[str, object]:
    props = RECIPE["clientProperties"]
    assert isinstance(props, dict)
    return RECIPE | {"clientProperties": props | changes}


def test_parse_listing_keeps_recipe_pages() -> None:
    html = listing(
        [
            card("/oppskrifter/suppe/9662/tomatsuppe"),
            card("/oppskrifter/4731/fondue", "2026-10-01T10:00:00.000Z"),
            card("/oppskrifter/suppe"),
            card("https://www.godt.no/artikler/noe/123/noe"),
            {"links": "nope"},
        ],
        total=2,
    )
    assert parse_listing(html) == (
        [
            RecipeRef(URL, "2026-10-13T13:29:42.000Z"),
            RecipeRef("https://www.godt.no/oppskrifter/4731/fondue", "2026-10-01T10:00:00.000Z"),
        ],
        2,
        2,
    )


def test_parse_recipe() -> None:
    recipe = parse_recipe(page(RECIPE), URL)
    assert recipe is not None
    assert recipe.is_dinner and recipe.main == "Suppe"
    assert recipe.name == "Hjemmelaget tomatsuppe"  # The page's title, not the one for search engines
    assert (recipe.portions, recipe.prep_time, recipe.rating, recipe.rating_count) == (4, "20\u201340 min", 4.1375, 80)
    løk, hvitløk, puré, tomat, parmesan = recipe.ingredients  # The nameless line is left out
    assert (løk.name, løk.amount, løk.unit, løk.category) == ("løk", 1.0, "stk", "")  # The build files it
    assert (hvitløk.amount, hvitløk.unit) == (2.0, "båt")  # In matprat's words
    assert (puré.amount, puré.text) == (1.5, "1-2 ss tomatpuré")  # The middle of «1 - 2 ss»
    assert tomat.text == "500 g tomat, gode, modne plomme- eller klasetomater"
    assert (parmesan.name, parmesan.amount, parmesan.unit, parmesan.text) == ("parmesan", None, "", "parmesan, revet")


def test_a_recipe_without_the_middag_tag_is_not_a_dinner() -> None:
    recipe = parse_recipe(page(with_props(tags=[{"title": "Kaker", "slug": "kaker", "isPrimary": True}])), URL)
    assert recipe is not None and not recipe.is_dinner


def test_minutes_are_the_whole_time_and_no_votes_is_no_rating() -> None:
    recipe = parse_recipe(page(with_props(preCookTime=30, cookingTime=10, postCookTime=1440, rating={"rating": 0, "votes": 0})), URL)
    assert recipe is not None
    assert (recipe.prep_time, recipe.rating, recipe.rating_count) == ("Over 60 min", None, 0)


@pytest.mark.parametrize(
    ("minutes", "bucket"),
    [
        (0, ""),
        (15, "Under 20 min"),
        (20, "20\u201340 min"),
        (40, "20\u201340 min"),
        (45, "40\u201360 min"),
        (60, "40\u201360 min"),
        (61, "Over 60 min"),
    ],
)
def test_prep_time_is_matprats_bucket(minutes: int, bucket: str) -> None:
    assert prep_time(minutes) == bucket


def test_pages_without_a_recipe() -> None:
    assert parse_recipe("<html></html>", URL) is None
    assert parse_recipe(page({}), URL) is None


def source(handle: Callable[[httpx2.Request], httpx2.Response]) -> GodtRecipeSource:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    return GodtRecipeSource(Pages(client, "godt.no", workers=2, tries=1))


async def test_fetch_and_index() -> None:
    pages = {
        "1": listing([card("/oppskrifter/suppe/9662/tomatsuppe"), card("/oppskrifter/4731/fondue", "2026-10-01T10:00:00.000Z")], 3),
        "2": listing([card("/oppskrifter/pasta/8529/kremet-kyllingpasta", "2024-07-26T08:44:03Z")], 3),
    }

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/oppskrifter/middag":
            return httpx2.Response(200, text=pages[request.url.params["page"]])
        return httpx2.Response(200, text=page(RECIPE))

    godt = source(handle)
    assert await godt.index() == [
        RecipeRef(URL, "2026-10-13T13:29:42.000Z"),
        RecipeRef("https://www.godt.no/oppskrifter/4731/fondue", "2026-10-01T10:00:00.000Z"),
        RecipeRef("https://www.godt.no/oppskrifter/pasta/8529/kremet-kyllingpasta", "2024-07-26T08:44:03Z"),
    ]
    recipe = await godt.fetch(URL)
    assert recipe is not None and recipe.name == "Hjemmelaget tomatsuppe"


async def test_a_later_page_cannot_shrink_the_list() -> None:
    """Page 2 and page 61 reported 1 447 on 2026-10-22 while page 1 and the last page's 16 items made 1 456."""
    pages = {
        "1": listing([card("/oppskrifter/suppe/9662/tomatsuppe"), card("/oppskrifter/4731/fondue")], 5),
        "2": listing(
            [card("/oppskrifter/pasta/8529/kremet-kyllingpasta"), card("/oppskrifter/fisk/7306/fiskeboller-i-hvit-saus")],
            2,
        ),
        "3": listing([card("/oppskrifter/gryte/2169/indisk-lammegryte")], 2),
    }

    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text=pages[request.url.params["page"]])

    assert len(await source(handle).index()) == 5


async def test_a_short_list_is_an_error_and_a_gone_page_is_none() -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.params.get("page") == "2":
            return httpx2.Response(200, text=listing([], 3))
        if request.url.path == "/oppskrifter/middag":
            return httpx2.Response(200, text=listing([card("/oppskrifter/suppe/9662/tomatsuppe")], 3))
        return httpx2.Response(404)

    gone = source(handle)
    assert await gone.fetch(URL) is None
    with pytest.raises(SourceUnavailableError, match="1 of 3"):
        await gone.index()


async def test_a_missing_list_is_an_error() -> None:
    with pytest.raises(SourceUnavailableError, match="no recipe list"):
        await source(lambda request: httpx2.Response(404)).index()


async def test_known_pages_stand_in_for_the_list() -> None:
    asked: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.url.path)
        return httpx2.Response(404)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    godt = GodtRecipeSource(Pages(client, "godt.no", tries=1), known=(URL,))
    assert await godt.index() == [RecipeRef(URL, "")]
    assert asked == []  # The list is never asked for


async def test_a_firewall_challenge_is_a_failed_page_and_not_retried() -> None:
    calls = 0

    def challenged(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(202, headers={"x-amzn-waf-action": "challenge"})

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(challenged))
    with pytest.raises(SourceUnavailableError, match="firewall"):
        await GodtRecipeSource(Pages(client, "godt.no", tries=3)).fetch(URL)
    assert calls == 1


async def test_pages_keep_to_the_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 100.0
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        nonlocal now
        waits.append(round(seconds, 3))
        now += seconds

    monkeypatch.setattr("pipeline.pages.time.monotonic", lambda: now)
    monkeypatch.setattr("pipeline.pages.asyncio.sleep", sleep)
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda request: httpx2.Response(200, text=page(RECIPE))))
    pages = Pages(client, "godt.no", workers=4, per_second=4)
    for _ in range(3):
        await pages.get(URL)
    assert waits == [0.25, 0.25]  # The first goes at once, then one every quarter second
