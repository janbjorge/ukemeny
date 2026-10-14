"""The offline build (src/app/build.py) with in-memory ports."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app import build
from core.models import LABELS, Item, Level, Onion, Part
from tests.fakes import (
    FakeClassifier,
    FakeDepartments,
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
    dinners, report = await build.recipes([source], lambda d, n: seen.append((d, n)))
    assert dinners == [DINNER]
    assert (report.listed, report.fetched, report.failed, report.dinners) == (3, 2, 1, 1)
    assert seen[0] == (0, 3) and seen[-1] == (3, 3)


async def test_recipes_come_from_every_source() -> None:
    soup = recipe("Tomatsuppe", ingredient("tomat", 500, "g", ""))
    godt = FakeSource({"https://www.godt.no/oppskrifter/suppe/9662/tomatsuppe": soup})
    dinners, report = await build.recipes([FakeSource({DINNER.url: DINNER}), godt])
    assert sorted(r.name for r in dinners) == ["Kyllinggryte", "Tomatsuppe"]
    assert (report.listed, report.dinners) == (2, 2)
    assert godt.fetched == ["https://www.godt.no/oppskrifter/suppe/9662/tomatsuppe"]


async def test_an_ingredient_without_a_department_is_filed_as_elsewhere_or_asked() -> None:
    godt = recipe("Kyllingsuppe", ingredient("kyllingfilet", 400, "g", ""), ingredient("timian", 1, "ts", ""))
    classifier = FakeDepartments({"timian": "/krydder"})
    dinners, _ = await build.fill_departments([DINNER, BROCCOLI_GRATIN, godt], classifier, {})
    assert [i.category for i in dinners[2].ingredients] == ["/kjøtt/kylling/høns", "/krydder"]
    assert dinners[:2] == [DINNER, BROCCOLI_GRATIN]  # Those with departments are kept as they are
    # Only the unknown name, with a dinner it is in
    assert classifier.asked == [("timian", ("/grønnsaker", "/kjøtt/kylling/høns", "/krydder"), "Kyllingsuppe")]


async def test_a_department_is_offered_with_the_names_filed_there_most() -> None:
    oil = [
        recipe(f"Rett {n}", ingredient(name, 1, "ss", "/margarin/olje/majones")) for n, name in enumerate(["olivenolje"] * 2 + ["rapsolje"])
    ]
    godt = recipe("Salat", ingredient("sesamolje", 1, "ss", ""))

    @dataclass
    class Shown:
        departments: Mapping[str, Sequence[str]] = field(default_factory=dict)

        async def department(self, ingredient: str, departments: Mapping[str, Sequence[str]], dish: str = "") -> str:
            self.departments = departments
            return "/margarin/olje/majones"

    shown = Shown()
    await build.fill_departments([*oil, godt], shown, {})
    assert shown.departments == {"/margarin/olje/majones": ("olivenolje", "rapsolje")}


async def test_a_picked_protein_department_needs_the_traits_to_agree_or_they_say_maybe() -> None:
    godt = recipe("Grillspyd", ingredient("grillspyd", 8, "stk", ""), ingredient("breiflabb", 600, "g", ""))
    picks = FakeDepartments({"grillspyd": "/kjøtt/pølser", "breiflabb": "/fisk og sjømat"})
    known = {"grillspyd": traits(), "breiflabb": traits(contains={Item.FISH: Level.YES})}
    (_, dinner), settled = await build.fill_departments([DINNER, godt], picks, known)
    assert [i.category for i in dinner.ingredients] == ["/diverse", "/fisk og sjømat"]
    assert settled["grillspyd"].contains[Item.MEAT] is Level.MAYBE  # «vegetar» leaves it out all the same
    assert settled["breiflabb"] == known["breiflabb"]


async def test_a_name_goes_to_jev_with_its_department_or_else_a_dinner_it_is_in() -> None:
    classifier = FakeClassifier()
    soup = recipe("Løksuppe", ingredient("løk", 1, "stk", ""), ingredient("timian", 1, "ts", ""))
    await build.classify([soup, recipe("Stekt løk", ingredient("løk", 1, "stk", "/grønnsaker"))], classifier)
    assert classifier.context == {"løk": ("/grønnsaker", ""), "timian": ("", "Løksuppe")}  # timian only on godt.no


async def test_every_ingredient_gets_every_label() -> None:
    classifier = FakeClassifier({"løk": traits(onion=Onion.ONION)})
    onion = ingredient("løk", 1, "stk.", "/grønnsaker")
    known = await build.classify([recipe("Kylling", CHICKEN, onion), recipe("Kylling igjen", CHICKEN)], classifier)
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
        [source],
        FakeDepartments(),
        FakeClassifier(),
        FakeOffers(current, places),
        FakeMatcher({"kyllingfilet": "kylling", "salt": "salt"}),
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
        [FakeSource({DINNER.url: DINNER})],
        FakeDepartments(),
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
        ("departments", 0, 0),
        ("catalogs", 0, 1),
        ("catalogs", 1, 1),
        ("offers", 0, 1),
        ("offers", 1, 1),
    ]
