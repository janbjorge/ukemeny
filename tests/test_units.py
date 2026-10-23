"""The kroner a head on one discount line (docs/plan-per-person.md, the table under «The arithmetic»): one test per row."""

import pytest

from core.models import Offer, Part, Pricing
from core.units import bought, counted, per_portion, price
from tests.fakes import offer

DIRECT, INDIRECT = Pricing.DIRECT, Pricing.INDIRECT


def part(unit: str, grams: float | None = None, pieces: float | None = None, name: str = "x") -> Part:
    return Part(name, "/grønnsaker", grams, unit, "", pieces)


def test_a_unit_counts_pieces_unless_it_is_a_mass_a_volume_or_nothing() -> None:
    assert all(counted(unit) for unit in ("stk", "båt", "skive", "boks", "pk", "bunt", "potte", "kvist"))
    assert not any(counted(unit) for unit in ("g", "kg", "ml", "dl", "l", "ss", "ts", ""))


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
