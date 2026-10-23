"""The kroner a head on one discount line (docs/plan-per-person.md, the table under «The arithmetic»): one test per row."""

import pytest

from core.dishes import dish
from core.models import Offer, Part, Pricing
from core.units import bought, counted, implied_weights, needed, per_portion, price, stated_weight
from tests.fakes import ingredient, offer, recipe

DIRECT, INDIRECT = Pricing.DIRECT, Pricing.INDIRECT


def part(unit: str, grams: float | None = None, pieces: float | None = None, name: str = "x") -> Part:
    return Part(name, "/grønnsaker", grams, unit, "", pieces)


def test_a_unit_counts_pieces_unless_it_is_a_mass_a_volume_or_nothing() -> None:
    assert all(counted(unit) for unit in ("stk", "båt", "skive", "boks", "pk", "bunt", "potte", "kvist"))
    assert not any(counted(unit) for unit in ("g", "kg", "ml", "dl", "l", "ss", "ts", ""))


def test_a_name_can_carry_its_own_weight() -> None:
    assert stated_weight("kylling (ca. 1500 g)") == 1500 and stated_weight("kalkun, ca. 5 kg") == 5000
    assert stated_weight("kalkunfilet, ca. 1,5 kg (med skinn)") == 1500 and stated_weight("kyllingfilet") is None


def test_the_recipes_imply_a_piece_weight_where_they_weigh_and_count_the_same_name() -> None:
    weighed = [recipe(f"Vekt {n}", ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")) for n in range(3)]
    counted = [recipe(f"Stk {n}", ingredient("kyllingfilet", 4, "stk", "/kjøtt/kylling/høns")) for n in range(3)]
    once = [recipe("Løk", ingredient("løk", 100, "g", "/grønnsaker"), ingredient("løk", 1, "stk", "/grønnsaker"))]
    assert implied_weights(dish(r) for r in weighed + counted + once) == {"kyllingfilet": 150.0}  # 150 g a head over 1 a head


def test_what_the_recipe_wants_a_head_is_in_g_ml_stk_or_packs() -> None:
    assert per_portion(part("g", 100)) == (100, "g") and per_portion(part("kg", 250)) == (250, "g")
    assert per_portion(part("dl", 200)) == (200, "ml") and per_portion(part("ss", 15)) == (15, "ml")
    assert per_portion(part("stk", 50, 0.5)) == (0.5, "stk") and per_portion(part("boks", 100, 0.25)) == (0.25, "pk")
    assert per_portion(part("skive", 20, 1)) is None and per_portion(part("", None)) is None and per_portion(part("stk", 50)) is None


def test_what_the_price_buys_is_packs_times_size_in_g_ml_or_stk() -> None:
    assert bought(offer("BIFF", size=1, unit="kg")) == (1000, "g") and bought(offer("RIBBE", size=0.1, unit="kg")) == (100, "g")
    assert bought(offer("EGG", size=12, unit="stk", pieces=2)) == (24, "stk") and bought(offer("MELK", size=1, unit="l")) == (1000, "ml")
    assert bought(offer("PASTA", size=250, size_to=500, unit="g")) == (375, "g")  # The midpoint of a range
    assert bought(offer("X")) is None


# A saving of 30 kr on a 700 g pack, 179,60 on a kilo, 4 kr on 100 g, 37 kr on two packs of 12, 8,90 on a 190 g pack
PACK = offer("KYLLINGFILET", 69.9, pre_price=99.9, size=700, unit="g")
KILO = offer("Biff", 269.4, pre_price=449, size=1, unit="kg")
HECTO = offer("RIBBE", 29.9, pre_price=33.9, size=0.1, unit="kg")
EGGS = offer("GÅRDSEGG", 80, pre_price=117, size=12, unit="stk", pieces=2)
TIN = offer("HAKKEDE TOMATER", 10, pre_price=18.9, size=400, unit="g")
EACH = offer("Nygrillet kyllinglår", 25, pre_price=39.9, size=1, unit="stk")
LITRE = offer("FLØTE", 20, pre_price=30, size=1, unit="l")
RANGE = offer("Fersk pasta", 40, pre_price=69.9, size=250, size_to=500, unit="g")


@pytest.mark.parametrize(
    ("line", "sale", "piece_g", "expected"),
    [
        (part("g", 100), PACK, None, (30 / 700 * 100, DIRECT)),
        (part("g", 100), KILO, None, (17.96, DIRECT)),
        (part("g", 100), HECTO, None, (4.0, DIRECT)),
        (part("dl", 200), LITRE, None, (2.0, DIRECT)),
        (part("stk", 50, 0.5), EGGS, None, (37 / 24 * 0.5, DIRECT)),
        (part("stk", 100, 1), EACH, None, (14.9, DIRECT)),
        (part("boks", 100, 0.25), TIN, None, (8.9 * 0.25, DIRECT)),
        (part("boks", 100, 0.25), KILO, None, None),  # A tin of something priced by the kilo: nothing to count
        (part("stk", 50, 0.5), PACK, 150, (30 / 700 * 75, INDIRECT)),  # Half a fillet a head, 150 g a fillet
        (part("stk", 50, 0.5), PACK, None, None),  # No piece weight yet
        (part("g", 100), EACH, 175, (14.9 * 100 / 175, INDIRECT)),
        (part("ss", 15), TIN, None, (8.9 / 400 * 15, INDIRECT)),  # A solid by volume, a gram a ml
        (part("g", 300), RANGE, None, (29.9 / 375 * 300, INDIRECT)),
        (part("ss", 15), EACH, None, None),  # A spoon of something sold per piece
        (part("skive", 20, 1), PACK, None, None),
        (part("", None), PACK, None, None),
        (part("g", 100), offer("NOTHING", 10, pre_price=15), None, None),  # No amount on the offer
        (part("g", 100), offer("FULL PRICE", 10, size=100, unit="g"), None, None),  # No saving
        (part("g", 1200), KILO, None, None),  # A batch for «1 portion»
        (part("stk", 200, 2), PACK, 3000, None),  # A piece weight that makes 6 kg a head
    ],
)
def test_kroner_a_head(line: Part, sale: Offer, piece_g: float | None, expected: tuple[float, Pricing] | None) -> None:
    found = price(line, sale, piece_g)
    if expected is None:
        assert found is None
    else:
        assert found is not None and found[0] == pytest.approx(expected[0], abs=0.005) and found[1] is expected[1]


# For what the recipe needs, four portions (jb 2026-10-23: "say the recepie calls for 2kg of chicken, we should then make
# sure that we multiplie up the savings if the chickon on sale is ex. 1kg")
@pytest.mark.parametrize(
    ("line", "sale", "piece_g", "expected"),
    [
        (part("g", 500), KILO, None, 179.6 * 2),  # 2 kg against a kilo price counts twice
        (part("g", 75), KILO, None, 179.6 * 0.3),  # 300 g counts 0,3
        (part("g", 75), HECTO, None, 4.0 * 3),  # 300 g against a price per 100 g
        (part("dl", 50), LITRE, None, 10 * 0.2),  # 2 dl of a litre
        (part("g", 150), PACK, None, 30.0),  # 600 g fills one 700 g pack
        (part("g", 375), PACK, None, 30.0 * 3),  # 1,5 kg fills three
        (part("g", 175), PACK, None, 30.0),  # 700 g is one pack exactly, not two
        (part("stk", 50, 1), EGGS, None, 37.0),  # 4 eggs: the lot of two dozen, once
        (part("stk", 100, 2), EACH, None, 14.9 * 8),  # 8 thighs priced each
        (part("boks", 100, 0.5), TIN, None, 8.9 * 2),  # 2 tins
        (part("stk", 50, 1), KILO, 150, 179.6 * 0.6),  # 4 steaks of 150 g against a kilo price
        (part("g", 300), RANGE, None, 29.9 * 4),  # 1,2 kg of 250 to 500 g packs, at the midpoint: four
        (part("boks", 100, 0.25), KILO, None, 179.6),  # A tin against a kilo price: the catalog's saving once
        (part("stk", 50, 0.5), PACK, None, 30.0),  # No piece weight: once
        (part("", None), PACK, None, 30.0),  # No amount: once
        (part("g", 1200), KILO, None, 179.6),  # Past the cap a head: once
        (
            part("stk", 100, 0.5),
            offer("Kyllingfilet", 30, pre_price=42, size=110, unit="g"),
            3400,
            12.0,
        ),  # A turkey against a 110 g pack: once
        (part("g", 150), HECTO, None, 4.0 * 6),  # 600 g of ribbe at a price per 100 g: six times, under the ten kilos
        (part("g", 100), offer("FULL PRICE", 10, size=100, unit="g"), None, 0.0),  # No saving
    ],
)
def test_kroner_for_what_the_recipe_needs(line: Part, sale: Offer, piece_g: float | None, expected: float) -> None:
    assert needed(line, sale, piece_g, 4) == pytest.approx(expected, abs=0.005)


def test_a_recipe_for_thirty_past_ten_kilos_counts_the_saving_once() -> None:
    assert needed(part("g", 400), KILO, None, 30) == pytest.approx(179.6)  # 12 kg of biff: once
    assert needed(part("g", 400), KILO, None, 20) == pytest.approx(179.6 * 8)  # 8 kg
