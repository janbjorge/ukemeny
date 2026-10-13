"""Search in plain bokmål: what the words mean, and which dinners they find."""

import pytest

from core.models import Gluten, Household, Kids, Onion
from core.ranking import dinners
from core.search import (
    MEAT,
    Index,
    Tag,
    marked,
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
        ("passer som den er", ["ingen bytter"]),
        ("uten bytter", ["ingen bytter"]),
        ("kjottdeig", ["kjøttdeig"]),
        ("lok", ["lok"]),  # Not a category without «uten», just a word
        ("uten lok", ["uten løk"]),
        ("gris og elg", ["svin eller vilt"]),
        ("uten kjøtt", ["uten kjøtt"]),
        ("annet kjøtt", ["annet kjøtt"]),
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
    for text in ("rask kylling uten sopp", "laks eller torsk på tilbud", "gris elg", "uten kjøtt barnevennlig", "annet kjøtt", *Tag):
        once = parse(text)
        assert parse(once.text).clauses == once.clauses


def test_toggle_adds_removes_and_replaces() -> None:
    s = parse("rask kylling")
    assert s.toggle(tag_clause(Tag.QUICK)).text == "kylling"
    assert s.toggle(tag_clause(Tag.UNDER_40)).text == "kylling under 40 min"
    assert s.toggle(protein_clause("fisk")).text == "under 20 min fisk"
    assert s.toggle(tag_clause(Tag.ON_SALE)).text == "under 20 min kylling på tilbud"


def test_clause_kinds_and_labels() -> None:
    assert parse("uten kjøtt").clauses == (protein_clause("kjøtt", negated=True),)
    assert parse("uten kjøtt").clauses[0].values == MEAT
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
def index() -> Index:
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
    return Index(dinners(s, HOUSEHOLD), s.traits, HOUSEHOLD)


def names(index: Index, text: str) -> list[str]:
    return [d.dish.name for d in index.find(index.parse(text))]


def test_diet_categories_describe_the_recipe_as_written(index: Index) -> None:
    assert "Kyllinggryte med sopp" not in names(index, "uten løk")  # needs a swap to vårløk
    assert "Kylling med vårløk" in names(index, "uten løk")  # the household's substitute is fine
    assert "Pasta med røkelaks" not in names(index, "glutenfri")
    assert set(names(index, "ingen bytter")) == set(names(index, "")) - {"Kyllinggryte med sopp", "Pasta med røkelaks"}
    assert "Kyllingsalat" not in names(index, "barnevennlig")  # chili among the ingredients
    assert "Chiliburger" not in names(index, "barnevennlig")  # chili in the name


def test_time_rating_and_protein(index: Index) -> None:
    assert set(names(index, "rask")) == {"Kyllinggryte med sopp", "Pasta med røkelaks"}
    assert names(index, "godt likt") == ["Kyllinggryte med sopp"]
    assert names(index, "fisk") == ["Torsk med bacon", "Pasta med røkelaks"]  # no swap first


def test_words_find_names_ingredients_departments_and_synonyms(index: Index) -> None:
    assert names(index, "laks") == ["Pasta med røkelaks"]
    assert names(index, "sopp") == ["Kyllinggryte med sopp"]  # sjampinjong is in /sopp
    assert "Pasta med røkelaks" in names(index, "spagetti eller pasta")
    assert names(index, "salat") == ["Kyllingsalat"]  # not the burger with lettuce: dish kinds are names only


def test_dish_name_matches_come_first(index: Index) -> None:
    assert names(index, "isbergsalat eller sopp") == ["Kyllinggryte med sopp", "Chiliburger", "Kyllingsalat"]


def test_without_leaves_out_side_ingredients_too(index: Index) -> None:
    assert "Torsk med bacon" not in names(index, "uten svin")  # bacon is pork, though the main is fish
    assert "Torsk med bacon" not in names(index, "uten bacon")
    assert names(index, "uten kjøtt") == ["Pasta med røkelaks"]


def test_typos_are_fixed_with_the_index(index: Index) -> None:
    s = index.parse("kyllingrgyte")
    assert s.corrected == (("kyllingrgyte", "kyllinggryte"),)
    assert names(index, "kyllingrgyte") == ["Kyllinggryte med sopp"]


def test_counts_and_relax(index: Index) -> None:
    s = index.parse("rask kylling")
    counts = index.count(s)
    assert counts.tags[Tag.UNDER_40] == 4  # what switching to under 40 min would give, not the current results
    assert counts.proteins == {"kylling": 1, "fisk": 1}
    nothing = index.parse("rask torsk")
    assert index.find(nothing) == []
    assert [(c.text, n) for c, n in index.relax(nothing)] == [("torsk", 2), ("under 20 min", 1)]


def test_via_and_marked(index: Index) -> None:
    s = index.parse("sopp")
    (dinner,) = index.find(s)
    assert via(dinner, s) == ()  # in the name already
    s = index.parse("sjampinjong")
    assert via(dinner, s) == ("sjampinjong",)
    pieces = marked("Pasta med røkelaks", parse("laks"))
    assert [p for p, hit in pieces if hit] == ["røkelaks"]


def test_without_clause_text() -> None:
    assert without_clause("sopp").text == "uten sopp"
