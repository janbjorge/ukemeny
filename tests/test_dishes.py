from core.dishes import dish, form
from core.models import Ingredient, Part
from tests.fakes import ingredient, recipe


def test_the_form_is_the_first_the_line_names() -> None:
    assert form("200 g røkt laksefilet") == "røkt"
    assert form("1 boks tunfisk") == "hermetisk"
    assert form("2 dl frosne erter") == "frossen"
    assert form("400 g tunfisk, av sushikvalitet") == ""
    assert form("1 pk ferdigkokte, røkte reker") == "kokt"


def test_a_part_keeps_the_form_the_line_asks_for() -> None:
    salmon = ingredient("laksefilet", 600, "g", "/fisk og sjømat")
    smoked = Ingredient("laks", "200 g røkt laks", 200, "g", "/fisk og sjømat")
    parts = dish(recipe("Laks", salmon, smoked)).parts
    assert parts == (Part("laksefilet", "/fisk og sjømat", 150, "g"), Part("laks", "/fisk og sjømat", 50, "g", "røkt"))


def test_a_line_counted_in_pieces_keeps_the_pieces_per_portion() -> None:
    eggs = ingredient("egg", 2, "stk.", "/egg")
    milk = ingredient("melk", 1, "dl", "/melk/melkeprodukter")
    tin = ingredient("hakkede tomater", 1, "boks", "/hermetikk")
    herbs = ingredient("friske urter", None, "", "/grønnsaker")
    parts = dish(recipe("Omelett", eggs, milk, tin, herbs, portions=3)).parts
    assert [p.pieces for p in parts] == [0.67, None, 0.33, None]
    assert [p.grams for p in parts] == [65, 35, 135, None]  # The rough table's guess, for the diet rules
