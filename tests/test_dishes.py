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
