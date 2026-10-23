"""The offline build (src/app/build.py) with in-memory ports."""

from app import build
from core.dishes import dish
from core.matching import CATEGORIES
from core.models import LABELS, Onion, Part
from tests.fakes import (
    FakeCategories,
    FakeClassifier,
    FakeMatcher,
    FakeOffers,
    FakeSource,
    ingredient,
    offer,
    recipe,
    snapshot,
    traits,
)

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
BROCCOLI = ingredient("brokkoli", 300, "g", "/grønnsaker")
SALT = ingredient("salt", 1, "ts", "/krydder")
DINNER = recipe("Kyllinggryte", CHICKEN, SALT)
NOT_A_RECIPE = "https://www.matprat.no/oppskrifter/kos/ikke-en-oppskrift/"
BROCCOLI_GRATIN = recipe("Brokkoligrateng", BROCCOLI)
VOCABULARY = {
    "kyllingfilet": traits(category="/kjøtt/kylling/høns"),
    "salt": traits(category="/krydder"),
    "frosne erter": traits(category="/grønnsaker"),
}
"""The rows kept from earlier builds."""


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


async def test_a_new_name_is_filed_by_its_line_a_near_name_or_the_classifier() -> None:
    peas, thyme = ingredient("erter", 1, "dl", ""), ingredient("timian", 1, "ts", "")
    godt = recipe("Kyllingsuppe", ingredient("kyllingfilet", 400, "g", ""), peas, thyme)
    categories = FakeCategories({"timian": "/krydder"})
    classifier = FakeClassifier()
    known = await build.draft([DINNER, BROCCOLI_GRATIN, godt], VOCABULARY, categories, classifier)
    assert {name: t.category for name, t in known.items() if name not in VOCABULARY} == {
        "brokkoli": "/grønnsaker",  # matprat's line
        "erter": "/grønnsaker",  # «frosne erter» has a row
        "timian": "/krydder",  # Nothing files it: the classifier picks among every category of ours
    }
    assert categories.asked == [("timian", CATEGORIES)]
    assert classifier.context == {"brokkoli": "/grønnsaker", "erter": "/grønnsaker", "timian": "/krydder"}  # New names only
    assert known["timian"].product == "timian" and known["timian"].source == "fake"
    assert list(known) == sorted(known) and all(known[name] == t for name, t in VOCABULARY.items())


async def test_each_category_is_shown_with_the_names_the_dinners_use_most() -> None:
    oil = [
        recipe(f"Rett {n}", ingredient(name, 1, "ss", "/margarin/olje/majones")) for n, name in enumerate(["rapsolje"] + ["olivenolje"] * 2)
    ]
    vocabulary = {
        "rapsolje": traits(category="/margarin/olje/majones"),
        "olivenolje": traits(category="/margarin/olje/majones"),
        "smør": traits(category="/melk/melkeprodukter"),
    }
    shown = build.examples(oil, vocabulary)
    assert shown["/margarin/olje/majones"] == ("olivenolje", "rapsolje") and shown["/melk/melkeprodukter"] == ("smør",)
    assert tuple(shown) == CATEGORIES and shown["/egg"] == ()


async def test_a_name_with_a_row_is_not_asked_again() -> None:
    classifier = FakeClassifier({"løk": traits(onion=Onion.ONION)})
    onion = ingredient("løk", 1, "stk.", "/grønnsaker")
    kept = {"kyllingfilet": VOCABULARY["kyllingfilet"]}
    known = await build.draft([recipe("Kylling", CHICKEN, onion), recipe("Kylling igjen", CHICKEN)], kept, FakeCategories(), classifier)
    assert classifier.asked == [("løk", LABELS)]  # Every label, once, and not kyllingfilet
    assert known["løk"].onion is Onion.ONION and known["kyllingfilet"] == VOCABULARY["kyllingfilet"]


async def test_a_name_counted_in_pieces_gets_a_piece_weight_once() -> None:
    eggs = ingredient("egg", 2, "stk.", "/egg")
    whole = ingredient("kylling (ca. 1500 g)", 1, "stk", "/kjøtt/kylling/høns")
    onion = ingredient("løk", 1, "stk.", "/grønnsaker")
    kept = {**VOCABULARY, "løk": traits(category="/grønnsaker", piece_g=120)}
    classifier = FakeClassifier(weights={"egg": 60})
    known = await build.draft([recipe("Omelett", eggs, whole, onion, CHICKEN)], kept, FakeCategories(), classifier)
    # Not løk, which has one; not the chicken, whose name says its own; not kyllingfilet, which no recipe counts in stk
    assert classifier.weighed == ["egg"] and classifier.context["egg"] == "/egg"
    assert (known["egg"].piece_g, known["kylling (ca. 1500 g)"].piece_g, known["løk"].piece_g) == (60, 1500, 120)
    assert known["kyllingfilet"].piece_g is None and known["egg"].source == "fake"


async def test_reweigh_weighs_the_names_the_dishes_count_in_stk_without_reading_anything() -> None:
    eggs = ingredient("egg", 2, "stk.", "/egg")
    base = snapshot(recipe("Omelett", eggs, CHICKEN), known={"egg": traits(category="/egg"), "kyllingfilet": VOCABULARY["kyllingfilet"]})
    classifier = FakeClassifier(weights={"egg": 60})
    seen: list[tuple[str, int, int]] = []
    s = await build.reweigh(base, classifier, lambda step, done, due: seen.append((step, done, due)))
    assert classifier.weighed == ["egg"] and classifier.context["egg"] == "/egg"
    assert s.traits["egg"].piece_g == 60 and s.traits["kyllingfilet"].piece_g is None
    assert s.dishes == base.dishes and s.offers == base.offers
    assert seen == [("weights", 0, 1), ("weights", 1, 1)]
    again = await build.reweigh(s, classifier)
    assert classifier.weighed == ["egg"] and again.traits == s.traits  # Asked once


def test_every_part_is_filed_as_the_vocabulary_has_it() -> None:
    (dinner,) = build.filed([recipe("Kyllinggryte", ingredient("kyllingfilet", 600, "g", "/kjøtt/pålegg"))], VOCABULARY)
    assert dinner.ingredients[0].category == "/kjøtt/kylling/høns"


async def test_meat_and_fish_are_asked_about_per_dinner_and_the_rest_by_name() -> None:
    raw = recipe("Nigiri", ingredient("tunfisk", 200, "g", "/fisk og sjømat"))
    tomato = ingredient("tomat", 400, "g", "/grønnsaker")
    salad = recipe("Tunfisksalat", ingredient("tunfisk", 1, "boks", "/fisk og sjømat"), tomato)
    soup = recipe("Tomatsuppe", tomato)
    offers = [
        offer("Tunfisk", 15, pre_price=23.9, id="tin", description="85 g, boks"),
        offer("TUNFISKFILET", 99, id="loin"),  # No discount: never asked about
        offer("TUNFISKPÅLEGG", 20, pre_price=30, id="pålegg"),  # Never an ingredient
        offer("TOMATER", 20, pre_price=30, id="tomat"),
    ]
    matcher = FakeMatcher({"tunfisk": "tunfisk", "tomat": "tomat"}, wrong={"Nigiri": "boks"})
    matched, served = await build.match([dish(r) for r in (raw, salad, soup)], offers, matcher, {})
    assert matched == {"tomat": ("tomat",)}
    assert served == {salad.url: {"tunfisk": ("tin",)}}  # The tin is no tuna for nigiri
    # Meat and fish with the form the line asks for («1 boks tunfisk») and the dinner; the rest by name
    assert sorted(matcher.asked) == [("tomat", 1, "", ""), ("tunfisk", 1, "", "Nigiri"), ("tunfisk", 1, "hermetisk", "Tunfisksalat")]


async def test_two_names_of_one_product_are_asked_once_and_both_written() -> None:
    tomatoes = ingredient("tomater", 400, "g", "/grønnsaker")
    cherry = ingredient("cherrytomater", 200, "g", "/grønnsaker")
    vocabulary = {"tomater": traits(product="tomat"), "cherrytomater": traits(product="tomat"), "tomat": traits()}
    matcher = FakeMatcher({"tomat": "tomat"})
    matched, _ = await build.match(
        [dish(recipe("Salat", tomatoes, cherry))], [offer("TOMATER", 20, pre_price=30, id="t")], matcher, vocabulary
    )
    assert matched == {"cherrytomater": ("t",), "tomater": ("t",)}
    assert matcher.asked == [("tomat", 1, "", "")]


async def test_a_dinner_without_a_discount_costs_nothing() -> None:
    matcher = FakeMatcher({"kyllingfilet": "kylling"})
    assert await build.match([dish(DINNER)], [offer("KYLLINGBRYST", 99, id="bryst")], matcher, {}) == ({}, {})
    assert matcher.asked == []


async def test_snapshot_holds_every_dinner_and_the_shoppable_matches() -> None:
    source = FakeSource({DINNER.url: DINNER, BROCCOLI_GRATIN.url: BROCCOLI_GRATIN})
    current = [offer("KYLLINGBRYST", 99, pre_price=135, id="bryst"), offer("SALTSTANG", id="snack")]
    places = {"Tromsø": ("KIWI",), "Bergen": ("KIWI",)}
    s, report = await build.snapshot(
        [source],
        VOCABULARY,
        FakeCategories(),
        FakeClassifier(),
        FakeOffers(current, places),
        FakeMatcher({"kyllingfilet": "kylling", "salt": "salt"}),
    )
    assert [d.name for d in s.dishes] == ["Brokkoligrateng", "Kyllinggryte"]
    assert s.dishes[1].parts[0] == Part("kyllingfilet", "/kjøtt/kylling/høns", 150, "g")  # Per portion
    assert set(s.traits) == {*VOCABULARY, "brokkoli"} and s.traits["brokkoli"].category == "/grønnsaker"
    assert s.served == {DINNER.url: {"kyllingfilet": ("bryst",)}}  # Salt is pantry: never looked up
    assert s.matches == {} and len(s.offers) == 2 and report.dinners == 2
    assert list(s.places.items()) == [("Bergen", ("KIWI",)), ("Tromsø", ("KIWI",))]  # sorted, as datasets/ has them


async def test_reprice_keeps_the_dinners_and_takes_this_weeks_offers() -> None:
    base = snapshot(DINNER, offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="old")], matches={"kyllingfilet": ["old"]})
    seen: list[tuple[str, int, int]] = []
    matcher = FakeMatcher({"kyllingfilet": "kylling"})
    s = await build.reprice(
        base,
        FakeOffers([offer("KYLLINGFILET", 89, pre_price=120, id="new")], {"Bergen": ("KIWI",)}),
        matcher,
        lambda step, done, due: seen.append((step, done, due)),
    )
    assert s.dishes == base.dishes and s.traits == base.traits
    assert [o.id for o in s.offers] == ["new"] and s.places == {"Bergen": ("KIWI",)}
    assert s.served == {DINNER.url: {"kyllingfilet": ("new",)}} and s.matches == {}
    assert matcher.asked == [("kyllingfilet", 1, "", "Kyllinggryte")]
    assert [step for step, _, _ in seen] == ["catalogs", "catalogs", "offers", "offers"]


async def test_snapshot_reports_each_step() -> None:
    seen: list[tuple[str, int, int]] = []
    await build.snapshot(
        [FakeSource({DINNER.url: DINNER})],
        {},
        FakeCategories(),
        FakeClassifier(),
        FakeOffers([offer("KYLLINGBRYST", 99, pre_price=135, id="bryst")]),
        FakeMatcher(),
        progress=lambda step, done, due: seen.append((step, done, due)),
    )
    assert seen == [
        ("recipes", 0, 1),
        ("recipes", 1, 1),
        ("categories", 0, 0),
        ("ingredients", 0, 2),
        ("ingredients", 1, 2),
        ("ingredients", 2, 2),
        ("weights", 0, 0),
        ("catalogs", 0, 1),
        ("catalogs", 1, 1),
        ("offers", 0, 1),
        ("offers", 1, 1),
    ]
