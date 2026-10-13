"""The offline build (src/app/build.py) with in-memory ports."""

from app import build
from core.models import LABELS, Item, Level, Onion, Part, Recipe, RecipeRef
from tests.fakes import (
    FakeClassifier,
    FakeMatcher,
    FakeMatches,
    FakeOffers,
    FakeRecipes,
    FakeSource,
    FakeTraits,
    ingredient,
    offer,
    recipe,
    traits,
)

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
BROCCOLI = ingredient("brokkoli", 300, "g", "/grønnsaker")
SALT = ingredient("salt", 1, "ts", "/krydder")
DINNER = recipe("Kyllinggryte", CHICKEN, SALT)
NOT_A_RECIPE = "https://www.matprat.no/oppskrifter/kos/ikke-en-oppskrift/"


async def test_refresh_fetches_new_pages_and_remembers_empty_ones() -> None:
    store = FakeRecipes()
    report = await build.refresh(FakeSource({DINNER.url: DINNER, NOT_A_RECIPE: None}), store)
    assert (report.listed, report.fetched, report.failed, report.dinners) == (2, 2, 0, 1)
    assert set(store.stored) == {DINNER.url, NOT_A_RECIPE}


async def test_refresh_skips_unchanged_pages_and_retries_failed_ones() -> None:
    source = FakeSource({DINNER.url: DINNER}, lastmod={DINNER.url: "2026-10-01"})
    store = FakeRecipes()
    store.stored[DINNER.url] = (RecipeRef(DINNER.url, "2026-10-01"), DINNER)
    await build.refresh(source, store)
    assert source.fetched == []
    source.lastmod[DINNER.url] = "2026-10-12"
    source.failing.add(DINNER.url)
    report = await build.refresh(source, store)
    assert (report.fetched, report.failed) == (0, 1)


async def test_refresh_limit_and_progress() -> None:
    pages: dict[str, Recipe | None] = {f"https://www.matprat.no/oppskrifter/rask/r{i}/": DINNER for i in range(5)}
    seen: list[tuple[int, int]] = []
    report = await build.refresh(FakeSource(pages), FakeRecipes(), limit=3, progress=lambda d, n: seen.append((d, n)))
    assert report.fetched == 3 and seen[-1] == (3, 3)


async def test_ingredients_are_classified_once() -> None:
    classifier = FakeClassifier({"løk": traits(onion=Onion.ONION)})
    store = FakeTraits()
    onion = ingredient("løk", 1, "stk.", "/grønnsaker")
    await build.classify([CHICKEN, onion, CHICKEN], store, classifier)
    known = await build.classify([CHICKEN, onion], store, classifier)
    assert sorted(name for name, _ in classifier.asked) == ["kyllingfilet", "løk"]
    assert known["løk"].onion is Onion.ONION and store.stored["løk"]["onion"] == "onion"


async def test_only_labels_not_stored_are_asked_for() -> None:
    store = FakeTraits({"løk": {"gluten": "no", "onion": "onion", "lactose": "none", "kids": "ok", "model": "old"}})
    classifier = FakeClassifier({"løk": traits(onion=Onion.ONION, contains={Item.EGG: Level.NO})})
    known = await build.classify([ingredient("løk", 1, "stk.", "/grønnsaker")], store, classifier)
    [(name, asked)] = classifier.asked
    assert name == "løk" and "onion" not in asked and set(asked) == set(LABELS) - {"gluten", "onion", "lactose", "kids"}
    assert known["løk"].contains[Item.EGG] is Level.NO and known["løk"].onion is Onion.ONION
    await build.classify([ingredient("løk")], store, classifier)
    assert len(classifier.asked) == 1  # everything is stored now


async def test_offer_answers_are_asked_once_and_obvious_ones_never() -> None:
    offers = [offer("KYLLINGBRYST", id="bryst"), offer("Kyllingfilet", id="filet"), offer("KYLLINGPÅLEGG", id="pålegg")]
    matcher = FakeMatcher({"kyllingfilet": "kylling"})
    store = FakeMatches()
    matched = await build.match(["kyllingfilet"], offers, store, matcher)
    assert matched == {"kyllingfilet": ("bryst", "filet")}
    assert matcher.asked == [("kyllingfilet", 1)]  # Only KYLLINGBRYST took judgment
    await build.match(["kyllingfilet"], offers, store, matcher)
    assert matcher.asked == [("kyllingfilet", 1)]


async def test_snapshot_holds_every_dinner_and_the_shoppable_matches() -> None:
    store = FakeRecipes().add(DINNER, recipe("Brokkoligrateng", BROCCOLI))
    current = [offer("KYLLINGBRYST", 99, pre_price=135, id="bryst"), offer("SALTSTANG", id="snack")]
    s = await build.snapshot(
        store, FakeTraits(), FakeClassifier(), FakeOffers(current), FakeMatches(), FakeMatcher({"kyllingfilet": "kylling", "salt": "salt"})
    )
    assert [d.name for d in s.dishes] == ["Brokkoligrateng", "Kyllinggryte"]
    assert s.dishes[1].parts[0] == Part("kyllingfilet", "/kjøtt/kylling/høns", 150, "g")  # Per portion
    assert set(s.traits) == {"kyllingfilet", "salt", "brokkoli"}
    assert s.matches == {"kyllingfilet": ("bryst",)}  # Salt is pantry: never looked up
    assert len(s.offers) == 2
