"""The offline build (src/app/build.py) with in-memory ports."""

from app import build
from core.models import LABELS, Onion, Part
from tests.fakes import (
    FakeClassifier,
    FakeMatcher,
    FakeOffers,
    FakeSource,
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
BROCCOLI_GRATIN = recipe("Brokkoligrateng", BROCCOLI)


async def test_recipes_are_every_dinner_listed_and_failed_pages_are_counted() -> None:
    source = FakeSource({DINNER.url: DINNER, NOT_A_RECIPE: None, "https://www.matprat.no/oppskrifter/kos/feil/": DINNER})
    source.failing.add("https://www.matprat.no/oppskrifter/kos/feil/")
    seen: list[tuple[int, int]] = []
    dinners, report = await build.recipes(source, lambda d, n: seen.append((d, n)))
    assert dinners == [DINNER]
    assert (report.listed, report.fetched, report.failed, report.dinners) == (3, 2, 1, 1)
    assert seen[0] == (0, 3) and seen[-1] == (3, 3)


async def test_every_ingredient_gets_every_label() -> None:
    classifier = FakeClassifier({"løk": traits(onion=Onion.ONION)})
    onion = ingredient("løk", 1, "stk.", "/grønnsaker")
    known = await build.classify([CHICKEN, onion, CHICKEN], classifier)
    assert sorted(name for name, _ in classifier.asked) == ["kyllingfilet", "løk"]
    assert all(asked == LABELS for _, asked in classifier.asked)
    assert known["løk"].onion is Onion.ONION


async def test_obvious_offers_are_never_asked_about() -> None:
    offers = [offer("KYLLINGBRYST", id="bryst"), offer("Kyllingfilet", id="filet"), offer("KYLLINGPÅLEGG", id="pålegg")]
    matcher = FakeMatcher({"kyllingfilet": "kylling"})
    matched = await build.match(["kyllingfilet"], offers, matcher)
    assert matched == {"kyllingfilet": ("bryst", "filet")}
    assert matcher.asked == [("kyllingfilet", 1)]  # Only KYLLINGBRYST took judgment


async def test_snapshot_holds_every_dinner_and_the_shoppable_matches() -> None:
    source = FakeSource({DINNER.url: DINNER, BROCCOLI_GRATIN.url: BROCCOLI_GRATIN})
    current = [offer("KYLLINGBRYST", 99, pre_price=135, id="bryst"), offer("SALTSTANG", id="snack")]
    places = {"Tromsø": ("KIWI",), "Bergen": ("KIWI",)}
    s, report = await build.snapshot(
        source, FakeClassifier(), FakeOffers(current, places), FakeMatcher({"kyllingfilet": "kylling", "salt": "salt"})
    )
    assert [d.name for d in s.dishes] == ["Brokkoligrateng", "Kyllinggryte"]
    assert s.dishes[1].parts[0] == Part("kyllingfilet", "/kjøtt/kylling/høns", 150, "g")  # Per portion
    assert set(s.traits) == {"kyllingfilet", "salt", "brokkoli"}
    assert s.matches == {"kyllingfilet": ("bryst",)}  # Salt is pantry: never looked up
    assert len(s.offers) == 2 and report.dinners == 2
    assert list(s.places.items()) == [("Bergen", ("KIWI",)), ("Tromsø", ("KIWI",))]  # sorted, as datasets/ has them


async def test_snapshot_reports_each_step() -> None:
    seen: list[tuple[str, int, int]] = []
    await build.snapshot(
        FakeSource({DINNER.url: DINNER}),
        FakeClassifier(),
        FakeOffers([offer("KYLLINGBRYST", id="bryst")]),
        FakeMatcher(),
        progress=lambda step, done, due: seen.append((step, done, due)),
    )
    assert seen == [
        ("recipes", 0, 1),
        ("recipes", 1, 1),
        ("ingredients", 0, 2),
        ("ingredients", 1, 2),
        ("ingredients", 2, 2),
        ("catalogs", 0, 1),
        ("catalogs", 1, 1),
        ("offers", 0, 1),
        ("offers", 1, 1),
    ]
