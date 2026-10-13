"""Search in plain bokmål: what the words mean, and which dinners they find."""

from dataclasses import dataclass

import pytest

from core.models import Dinner, Gluten, Household, Item, Kids, Onion, Rule
from core.ranking import dinners, prepare
from core.search import (
    ANYTHING,
    MEAT,
    Clause,
    Counts,
    Diet,
    Index,
    Order,
    Search,
    Tag,
    View,
    diet_clause,
    household,
    marked,
    order_clause,
    parse,
    protein_clause,
    same,
    tag_clause,
    via,
    with_clause,
    without_clause,
)
from tests.fakes import ingredient, recipe, snapshot, traits

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
COD = ingredient("torskefilet", 600, "g", "/fisk og sjømat")
SALMON = ingredient("røkelaks", 400, "g", "/fisk og sjømat")
BACON = ingredient("bacon", 100, "g", "/kjøtt/svinekjøtt")
MUSHROOM = ingredient("sjampinjong", 200, "g", "/sopp")
PASTA = ingredient("tagliatelle", 400, "g", "/pasta/ris")
ONION = ingredient("løk", 1, "stk.", "/grønnsaker")
SPRING_ONION = ingredient("vårløk", 1, "bunt", "/grønnsaker")
CHILI = ingredient("rød chili", 1, "stk.", "/grønnsaker")
LETTUCE = ingredient("isbergsalat", 100, "g", "/grønnsaker")
HOUSEHOLD = Household(onion_substitute="vårløk")


def tags_of(text: str) -> list[str]:
    return [c.text for c in parse(text).clauses]


@pytest.mark.parametrize(
    ("text", "clauses"),
    [
        ("rask kylling uten sopp", ["under 20 min", "kylling", "uten sopp"]),
        ("Jeg vil ha noe med laks til middag", ["laks"]),
        ("laks eller torsk på tilbud", ["laks eller torsk", "på tilbud"]),
        ("kylling fisk", ["kylling eller fisk"]),
        ("uten løk og hvitløk", ["uten løk", "uten hvitløk"]),
        ("uten sopp og paprika", ["uten sopp", "uten paprika"]),
        ("uten sopp, med paprika", ["uten sopp", "paprika"]),
        ("-ost pasta", ["uten ost", "pasta"]),
        ("ikke sterk", ["barnevennlig"]),
        ("billig middag til barna", ["på tilbud", "barnevennlig"]),
        ("glutenfritt og laktosefri", ["glutenfri", "lite laktose"]),
        ("kjottdeig", ["kjøttdeig"]),
        ("lok", ["lok"]),  # Not a category without «uten», just a word
        ("uten lok", ["uten løk"]),
        ("gris og elg", ["svin eller vilt"]),
        ("uten kjøtt", ["pescetarianer"]),
        ("uten kylling", ["uten kylling"]),
        ("vegetarisk", ["vegetar"]),
        ("kjøttfri vegansk", ["vegetar", "vegansk"]),
        ("uten egg, nøtter og peanøtter", ["uten egg", "uten nøtter", "uten peanøtter"]),
        ("lav fodmap gravid lavkarbo", ["lav fodmap", "gravid", "lavkarbo"]),
        ("melkefri uten svin", ["melkefri", "uten svin"]),
        ("annet kjøtt", ["annet kjøtt"]),
        ("kylling størst rabatt", ["kylling", "rabatt i prosent"]),
        ("mest spart rabatt i prosent", ["rabatt i prosent"]),  # a later order replaces an earlier one
        ("laks laks", ["laks"]),
        ("", []),
        ("og og eller ,", []),
    ],
)
def test_parse(text: str, clauses: list[str]) -> None:
    assert [c.text for c in parse(text).clauses] == clauses


@pytest.mark.parametrize(
    ("text", "tag"),
    [
        ("under 30 min", Tag.QUICK),
        ("på 15 minutter", Tag.QUICK),
        ("under en halvtime", Tag.QUICK),
        ("45 min", Tag.UNDER_40),
        ("under 40 min", Tag.UNDER_40),
        ("under en time", Tag.UNDER_60),
        ("under 1 time", Tag.UNDER_60),
    ],
)
def test_prep_time_is_the_strictest_bucket_that_keeps_within_it(text: str, tag: Tag) -> None:
    assert parse(text).clauses == (tag_clause(tag),)


def test_a_later_prep_time_replaces_an_earlier_one() -> None:
    assert tags_of("rask kylling under en time") == ["kylling", "under en time"]
    assert tags_of("under 3 timer") == []


def test_the_written_search_parses_back_to_the_same_clauses() -> None:
    for text in (
        "rask kylling uten sopp",
        "laks eller torsk på tilbud",
        "gris elg",
        "uten kjøtt barnevennlig",
        "annet kjøtt",
        *Tag,
        *Diet,
        *Order,
    ):
        once = parse(text)
        assert parse(once.text).clauses == once.clauses


def test_an_order_toggles_and_replaces_the_other() -> None:
    s = parse("kylling rabatt i kroner")
    assert s.order is Order.KRONER and order_clause(Order.KRONER).label == "Rabatt kr"
    assert s.toggle(order_clause(Order.PERCENT)).text == "kylling rabatt i prosent"
    assert s.toggle(order_clause(Order.KRONER)).text == "kylling"


def test_toggle_adds_removes_and_replaces() -> None:
    s = parse("rask kylling")
    assert s.toggle(tag_clause(Tag.QUICK)).text == "kylling"
    assert s.toggle(tag_clause(Tag.UNDER_40)).text == "kylling under 40 min"
    assert s.toggle(protein_clause("fisk")).text == "under 20 min fisk"
    assert s.toggle(tag_clause(Tag.ON_SALE)).text == "under 20 min kylling på tilbud"


def test_clause_kinds_and_labels() -> None:
    assert parse("uten kylling").clauses == (protein_clause("kylling", negated=True),)
    assert parse("uten sjømat").clauses[0].values == ("fisk", "skalldyr")
    assert protein_clause("kjøtt").values == MEAT
    assert parse("uten kjøtt").clauses == (diet_clause(Diet.PESCETARIAN),)
    assert diet_clause(Diet.FODMAP).label == "Lav FODMAP" and diet_clause(Diet.EGG).label == "Uten egg"
    assert parse("laks eller torsk").clauses == (with_clause(("laks", "torsk")),)
    assert parse("uten sopp").clauses[0].label == "Uten sopp"
    assert parse("kylling fisk").clauses[0].label == "Kylling eller fisk"


def test_fix_swaps_words_that_match_nothing() -> None:
    fixes = {"kyllign": "kylling", "sjampinjogn": "sjampinjong"}
    s = parse("kyllign uten sjampinjogn", fix=lambda word: fixes.get(word, word))
    assert [c.text for c in s.clauses] == ["kylling", "uten sjampinjong"]
    assert s.corrected == (("kyllign", "kylling"), ("sjampinjogn", "sjampinjong"))


@pytest.mark.parametrize(
    ("term", "word", "found"),
    [
        ("laks", "røkelaks", True),
        ("laks", "laksefilet", True),
        ("ris", "jasminris", True),
        ("ris", "kapris", False),
        ("tacos", "taco", True),
        ("kotelett", "svinekoteletter", True),
        ("kjottdeig", "kjøttdeig", True),
        ("kål", "kalkun", False),
        ("kal", "kålrot", True),
        ("egg", "eggeplomme", True),
        ("ost", "parmesanost", True),
        ("ål", "ål", True),
    ],
)
def test_same(term: str, word: str, found: bool) -> None:
    assert same(term, word) is found


@pytest.fixture
def index() -> Bound:
    s = snapshot(
        recipe("Kyllinggryte med sopp", CHICKEN, MUSHROOM, ONION, rating=4.8, rating_count=40, prep_time="Under 20 min"),
        recipe("Kylling med vårløk", CHICKEN, SPRING_ONION, prep_time="20\u201340 min"),
        recipe("Torsk med bacon", COD, BACON, prep_time="Over 60 min"),
        recipe("Pasta med røkelaks", SALMON, PASTA, prep_time="Under 20 min"),
        recipe("Chiliburger", CHICKEN, LETTUCE),
        recipe("Kyllingsalat", CHICKEN, LETTUCE, CHILI),
        known={
            "løk": traits(onion=Onion.ONION),
            "vårløk": traits(onion=Onion.ONION),
            "tagliatelle": traits(gluten=Gluten.YES),
            "rød chili": traits(kids=Kids.SPICY),
        },
    )
    every = prepare(s)
    index = Index(every, s.traits)
    return Bound(index, index.view(dinners(s, HOUSEHOLD, every)))


@dataclass(frozen=True, slots=True)
class Bound:
    """The index with one set of rules, as Queries uses it."""

    index: Index
    view: View

    def parse(self, text: str) -> Search:
        return self.index.parse(text)

    def find(self, search: Search) -> list[Dinner]:
        return self.index.find(search, self.view)

    def count(self, search: Search) -> Counts:
        return self.index.count(search, self.view)

    def relax(self, search: Search) -> list[tuple[Clause, int]]:
        return self.index.relax(search, self.view)


def names(index: Bound, text: str) -> list[str]:
    return [d.dish.name for d in index.find(index.parse(text))]


def test_diet_words_are_rules_on_top_of_a_base() -> None:
    assert parse("uten løk, glutenfri og laktosefri kylling").diets == {Diet.ONION, Diet.GLUTEN, Diet.LACTOSE}
    assert household([]) == ANYTHING
    h = household([Diet.ONION, Diet.GLUTEN, Diet.LACTOSE])
    assert (h.onion, h.onion_substitute, h.gluten, h.lactose_g_per_portion) == (Rule.AVOID, "vårløk", Rule.AVOID, 3.0)
    assert h.garlic is Rule.OK and not h.kid_notes
    assert household([Diet.ONION], Household(onion_substitute="purre")).onion_substitute == "purre"  # a profile's own


def test_rules_that_leave_things_out() -> None:
    assert household([Diet.VEGETARIAN]).avoid == {Item.MEAT, Item.FISH, Item.CRUSTACEAN, Item.MOLLUSC}
    assert household([Diet.PESCETARIAN, Diet.EGG]).avoid == {Item.MEAT, Item.EGG}
    assert {Item.ANIMAL, Item.MILK, Item.EGG} <= household([Diet.VEGAN]).avoid
    fodmap = household([Diet.FODMAP])
    assert fodmap.fodmap and fodmap.onion is Rule.AVOID and fodmap.garlic is Rule.AVOID and fodmap.gluten is Rule.AVOID
    assert fodmap.lactose_g_per_portion == 3.0 and fodmap.onion_substitute == "vårløk"
    assert household([Diet.LOW_CARB]).carbs_g_per_portion == 20.0 and household([Diet.PREGNANT]).pregnant
    assert household([Diet.GARLIC]).garlic is Rule.AVOID


def test_rules_do_not_filter_an_index(index: Bound) -> None:
    assert names(index, "glutenfri") == names(index, "")  # the rule picks the index (Queries), it does not narrow one


def test_barnevennlig(index: Bound) -> None:
    assert "Kyllingsalat" not in names(index, "barnevennlig")  # chili among the ingredients
    assert "Chiliburger" not in names(index, "barnevennlig")  # chili in the name


def test_time_rating_and_protein(index: Bound) -> None:
    assert set(names(index, "rask")) == {"Kyllinggryte med sopp", "Pasta med røkelaks"}
    assert names(index, "godt likt") == ["Kyllinggryte med sopp"]
    assert names(index, "fisk") == ["Torsk med bacon", "Pasta med røkelaks"]  # no swap first


def test_words_find_names_ingredients_departments_and_synonyms(index: Bound) -> None:
    assert names(index, "laks") == ["Pasta med røkelaks"]
    assert names(index, "sopp") == ["Kyllinggryte med sopp"]  # sjampinjong is in /sopp
    assert "Pasta med røkelaks" in names(index, "spagetti eller pasta")
    assert names(index, "salat") == ["Kyllingsalat"]  # not the burger with lettuce: dish kinds are names only


def test_dish_name_matches_come_first(index: Bound) -> None:
    assert names(index, "isbergsalat eller sopp") == ["Kyllinggryte med sopp", "Chiliburger", "Kyllingsalat"]


def test_without_leaves_out_side_ingredients_too(index: Bound) -> None:
    assert "Torsk med bacon" not in names(index, "uten bacon")
    assert "Kyllingsalat" not in names(index, "uten kylling") and "Torsk med bacon" in names(index, "uten kylling")


def test_typos_are_fixed_with_the_index(index: Bound) -> None:
    s = index.parse("kyllingrgyte")
    assert s.corrected == (("kyllingrgyte", "kyllinggryte"),)
    assert names(index, "kyllingrgyte") == ["Kyllinggryte med sopp"]


def test_counts_and_relax(index: Bound) -> None:
    s = index.parse("rask kylling")
    counts = index.count(s)
    assert counts.tags[Tag.UNDER_40] == 4  # what switching to under 40 min would give, not the current results
    assert counts.proteins == {"kylling": 1, "fisk": 1}
    nothing = index.parse("rask torsk")
    assert index.find(nothing) == []
    assert [(c.text, n) for c, n in index.relax(nothing)] == [("torsk", 2), ("under 20 min", 1)]


def test_via_and_marked(index: Bound) -> None:
    s = index.parse("sopp")
    (dinner,) = index.find(s)
    assert via(dinner, s) == ()  # in the name already
    s = index.parse("sjampinjong")
    assert via(dinner, s) == ("sjampinjong",)
    pieces = marked("Pasta med røkelaks", parse("laks"))
    assert [p for p, hit in pieces if hit] == ["røkelaks"]


def test_without_clause_text() -> None:
    assert without_clause("sopp").text == "uten sopp"
