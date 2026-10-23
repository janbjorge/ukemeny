"""datasets/traits.json, the vocabulary, reviewed (docs/plan-model.md §1): every name in dishes.json has a row, every
part's category is its row's, and no row contradicts itself. A row Jev drafted wrong is fixed by hand; a row that is
right although a rule says otherwise is named in EXCEPTIONS."""

import pytest

from adapters.datasets import JsonDatasets
from core.matching import CATEGORIES, HOLDS
from core.models import HAND, Item, Level, Snapshot, Traits
from core.units import implied_weights
from tests.fakes import traits

ANIMAL = (Item.MEAT, Item.FISH, Item.CRUSTACEAN, Item.MOLLUSC, Item.MILK, Item.EGG)
PLANT = ("/grønnsaker", "/frukt", "/bær", "/poteter", "/sopp", "/nøtter")
"""Categories whose rows hold nothing from an animal. Bread and pasta are not here: brioche holds milk and egg."""
SEA = ("/fisk og sjømat", "/skalldyr")
EXCEPTIONS = {
    "hvalkjøtt": "whale is meat, sold with the fish",
    "ferdig potetmos": "a potato product made with milk",
}
"""Rows a rule flags that are right as they are."""


def problems(t: Traits) -> list[str]:
    """Where a row contradicts itself: a label against another, or against its category."""
    holds = {item: t.contains.get(item) for item in Item}

    def yes(item: Item) -> bool:
        return holds[item] is Level.YES

    found = []
    if t.category not in CATEGORIES:
        found.append(f"category {t.category!r} is not one of ours")
    if holds[Item.ANIMAL] is Level.NO:
        found += [f"animal no, but {item} yes" for item in ANIMAL if yes(item)]
    if holds[Item.PORK] is Level.YES and not yes(Item.MEAT):
        found.append(f"pork yes, but meat {holds[Item.MEAT]}")
    if holds[Item.PORK] is Level.MAYBE and holds[Item.MEAT] is Level.NO:
        found.append("pork maybe, but meat no")
    for prefix, items in HOLDS.items():
        if t.category.startswith(prefix) and not any(yes(item) for item in items):
            found.append(f"filed under {t.category}, but " + ", ".join(f"{item} {holds[item]}" for item in items))
    if t.category.startswith(PLANT):
        found += [f"filed under {t.category}, but {item} yes" for item in ANIMAL if yes(item)]
    if t.category.startswith(SEA) and yes(Item.MEAT):
        found.append(f"filed under {t.category}, but meat yes")
    if t.category.startswith("/kjøtt/svinekjøtt") and not yes(Item.PORK):
        found.append(f"filed under {t.category}, but pork {holds[Item.PORK]}")
    if t.category.startswith("/egg") and not yes(Item.EGG):
        found.append(f"filed under /egg, but egg {holds[Item.EGG]}")
    return found


def test_a_row_against_its_category_or_itself_is_flagged() -> None:
    assert problems(traits(contains={Item.MEAT: Level.YES, Item.ANIMAL: Level.YES}, category="/kjøtt/storfekjøtt")) == []
    assert problems(traits(category="/kjøtt/storfekjøtt")) == ["filed under /kjøtt/storfekjøtt, but meat no"]
    assert problems(traits(contains={Item.EGG: Level.YES}, category="/grønnsaker")) == [
        "animal no, but egg yes",
        "filed under /grønnsaker, but egg yes",
    ]
    assert problems(traits(contains={Item.PORK: Level.YES}, category="/diverse")) == ["pork yes, but meat no"]
    assert problems(traits(category="/kjott")) == ["category '/kjott' is not one of ours"]


@pytest.fixture(scope="module")
def live() -> Snapshot:
    return JsonDatasets().snapshot()


def test_every_row_is_filed_and_signed(live: Snapshot) -> None:
    assert all(t.category in CATEGORIES and t.product and t.source for t in live.traits.values())
    assert sum(t.source == HAND for t in live.traits.values()) > 0


def test_every_part_takes_its_rows_category(live: Snapshot) -> None:
    parts = [(p, live.traits[p.name]) for d in live.dishes for p in d.parts]
    assert {(p.name, p.category, t.category) for p, t in parts if p.category != t.category} == set()


def test_no_row_contradicts_itself(live: Snapshot) -> None:
    flagged = {name: found for name, t in live.traits.items() if name not in EXCEPTIONS and (found := problems(t))}
    assert flagged == {}


def test_every_exception_is_still_needed(live: Snapshot) -> None:
    assert {name for name in EXCEPTIONS if problems(live.traits[name])} == set(EXCEPTIONS)


WEIGHT_BANDS: dict[str, tuple[float, float]] = {
    "/egg": (10, 80),
    "/poteter": (20, 300),
    "/sopp": (5, 100),
    "/grønnsaker": (2, 2000),
    "/frukt": (5, 3000),
    "/bær": (1, 50),
    "/kjøtt": (20, 5000),
    "/fisk og sjømat": (10, 3000),
    "/skalldyr": (5, 1000),
    "/ost": (5, 500),
}
"""Grams a piece can weigh, by category: the order-of-magnitude guard on Traits.piece_g (docs/plan-per-person.md)."""
ANY_WEIGHT = (1.0, 5000.0)
WEIGHT_AGREEMENT = 3.0
"""Jev's piece weight against the one the recipes imply: within this factor, either way."""


def test_every_piece_weight_is_in_its_categorys_band(live: Snapshot) -> None:
    out = {}
    for name, t in live.traits.items():
        if t.piece_g is not None:
            low, high = next((band for prefix, band in WEIGHT_BANDS.items() if t.category.startswith(prefix)), ANY_WEIGHT)
            if not low <= t.piece_g <= high:
                out[name] = (t.piece_g, t.category)
    assert out == {}


def test_the_piece_weights_agree_with_what_the_recipes_imply(live: Snapshot) -> None:
    implied = implied_weights(live.dishes)
    off = {
        name: (t.piece_g, round(grams))
        for name, grams in implied.items()
        if (t := live.traits.get(name))
        and t.piece_g is not None
        and name not in EXCEPTIONS
        and not (1 / WEIGHT_AGREEMENT <= t.piece_g / grams <= WEIGHT_AGREEMENT)
    }
    assert off == {}
