from core import diet
from core.dishes import dish
from core.models import Gluten, Household, Kids, Lactose, Onion, Problem, Recipe, Rule, Traits, Verdict
from tests.fakes import PLAIN, ingredient, recipe, traits


def judge(r: Recipe, known: dict[str, Traits], household: Household) -> Verdict:
    return diet.judge(dish(r), known, household)


HOUSEHOLD = Household()
SPRING_ONION_OK = Household(onion_substitute="vårløk")
DAIRY = "/melk/melkeprodukter"


def test_plain_recipe_fits_as_is() -> None:
    r = recipe("Kylling med ris", ingredient("kyllingfilet", 600, "g"), ingredient("ris", 3, "dl"))
    verdict = judge(r, {"kyllingfilet": PLAIN, "ris": PLAIN}, HOUSEHOLD)
    assert verdict.blocked is None
    assert verdict.swaps == ()
    assert verdict.warnings == ()


def test_gluten_and_onion_become_swaps() -> None:
    r = recipe("Laks med nudler", ingredient("eggnudler", 250, "g"), ingredient("rødløk", 1, "stk."))
    verdict = judge(r, {"eggnudler": traits(gluten=Gluten.YES), "rødløk": traits(onion=Onion.ONION)}, HOUSEHOLD)
    assert verdict.blocked is None
    assert [(s.problem, s.ingredient) for s in verdict.swaps] == [
        (Problem.GLUTEN, "eggnudler"),
        (Problem.ONION, "rødløk"),
    ]
    assert [s.swap for s in verdict.swaps] == ["glutenfri eggnudler", "dropp rødløk"]


def test_maybe_is_a_warning_to_check_the_label() -> None:
    r = recipe("Gryte", ingredient("buljongterning", 1, "stk."))
    verdict = judge(r, {"buljongterning": traits(gluten=Gluten.MAYBE, onion=Onion.MAYBE)}, HOUSEHOLD)
    assert verdict.swaps == ()
    assert {w.problem for w in verdict.warnings} == {Problem.GLUTEN, Problem.ONION}


def test_onion_in_the_dish_name_blocks() -> None:
    r = recipe("Biff med løk", ingredient("løk", 1, "stk."))
    verdict = judge(r, {"løk": traits(onion=Onion.ONION)}, HOUSEHOLD)
    assert verdict.blocked is not None and "løk" in verdict.blocked


def test_garlic_in_the_name_is_not_onion() -> None:
    r = recipe("Laks med hvitløk", ingredient("løk", 1, "stk."), ingredient("hvitløk", 2, "båt"))
    verdict = judge(r, {"løk": traits(onion=Onion.ONION), "hvitløk": traits(onion=Onion.GARLIC)}, HOUSEHOLD)
    assert verdict.blocked is None


def test_three_onions_for_four_blocks_without_a_substitute() -> None:
    r = recipe("Lapskaus", ingredient("løk", 3, "stk."), portions=4)
    onion = {"løk": traits(onion=Onion.ONION)}
    assert judge(r, onion, HOUSEHOLD).blocked is not None
    verdict = judge(r, onion, SPRING_ONION_OK)
    assert verdict.blocked is None
    assert [s.advice for s in verdict.swaps] == ["bruk vårløk i stedet"]
    assert [s.swap for s in verdict.swaps] == ["vårløk for løk"]


def test_spring_onion_is_fine() -> None:
    r = recipe("Laks med vårløk", ingredient("vårløk", 1, "bunt"), ingredient("løk", 1, "stk."))
    known = {"vårløk": traits(onion=Onion.ONION), "løk": traits(onion=Onion.ONION)}
    assert [s.ingredient for s in judge(r, known, HOUSEHOLD).swaps] == ["vårløk", "løk"]
    verdict = judge(r, known, SPRING_ONION_OK)
    assert verdict.blocked is None
    assert [s.ingredient for s in verdict.swaps] == ["løk"]


def test_one_onion_for_four_is_a_swap() -> None:
    r = recipe("Lapskaus", ingredient("løk", 1, "stk."), portions=4)
    verdict = judge(r, {"løk": traits(onion=Onion.ONION)}, HOUSEHOLD)
    assert verdict.blocked is None
    assert [s.problem for s in verdict.swaps] == [Problem.ONION]


def test_no_swaps_household_skips_recipes_that_need_one() -> None:
    r = recipe("Pasta", ingredient("spaghetti", 400, "g"))
    verdict = judge(r, {"spaghetti": traits(gluten=Gluten.YES)}, Household(swaps=False))
    assert verdict.blocked == "trenger et bytte"


def test_no_swaps_household_still_allows_lactose_free_dairy() -> None:
    r = recipe("Gryte", ingredient("matfløte", 5, "dl", DAIRY), portions=4)
    verdict = judge(r, {"matfløte": traits(lactose=Lactose.SOME)}, Household(swaps=False))
    assert verdict.blocked is None
    assert [s.problem for s in verdict.swaps] == [Problem.LACTOSE]


def test_rules_note_and_ok() -> None:
    r = recipe("Biff med løk", ingredient("løk", 3, "stk."), ingredient("spaghetti", 400, "g"))
    known = {"løk": traits(onion=Onion.ONION), "spaghetti": traits(gluten=Gluten.YES)}
    noted = judge(r, known, Household(onion=Rule.NOTE, gluten=Rule.NOTE))
    assert noted.blocked is None
    assert noted.swaps == ()
    assert {w.problem for w in noted.warnings} == {Problem.ONION, Problem.GLUTEN}
    fine = judge(r, known, Household(onion=Rule.OK, gluten=Rule.OK))
    assert (fine.blocked, fine.swaps, fine.warnings) == (None, (), ())


def test_no_lactose_limit() -> None:
    r = recipe("Grøt", ingredient("melk", 1, "l", DAIRY), portions=2)
    verdict = judge(r, {"melk": traits(lactose=Lactose.HIGH)}, Household(lactose_g_per_portion=None))
    assert verdict.swaps == ()


def test_garlic_is_a_note_unless_the_household_avoids_it() -> None:
    r = recipe("Gryte", ingredient("hvitløk", 2, "båt"))
    garlic = {"hvitløk": traits(onion=Onion.GARLIC)}
    assert [w.problem for w in judge(r, garlic, HOUSEHOLD).warnings] == [Problem.GARLIC]
    assert [s.problem for s in judge(r, garlic, Household(garlic=Rule.AVOID)).swaps] == [Problem.GARLIC]
    assert judge(r, garlic, Household(garlic=Rule.OK)).warnings == ()


def test_a_splash_of_cream_is_fine() -> None:
    r = recipe("Gryte", ingredient("matfløte", 1, "dl", DAIRY), portions=4)
    verdict = judge(r, {"matfløte": traits(lactose=Lactose.SOME)}, HOUSEHOLD)
    assert verdict.swaps == ()
    assert round(verdict.lactose_g, 2) == 0.75


def test_a_cream_sauce_gets_a_lactose_free_swap() -> None:
    r = recipe(
        "Kremet gryte",
        ingredient("matfløte", 3, "dl", DAIRY),
        ingredient("lettmelk", 2, "dl", DAIRY),
        ingredient("smør", 2, "ss", DAIRY),
        portions=4,
    )
    verdict = judge(
        r,
        {
            "matfløte": traits(lactose=Lactose.SOME),
            "lettmelk": traits(lactose=Lactose.HIGH),
            "smør": traits(lactose=Lactose.TRACE),
        },
        HOUSEHOLD,
    )
    assert [(s.problem, s.ingredient) for s in verdict.swaps] == [
        (Problem.LACTOSE, "matfløte"),
        (Problem.LACTOSE, "lettmelk"),
    ]


def test_lactose_only_counts_in_dairy_departments() -> None:
    r = recipe("Gryte", ingredient("vineddik", 5, "dl", "/diverse"), portions=4)
    verdict = judge(r, {"vineddik": traits(lactose=Lactose.HIGH)}, HOUSEHOLD)
    assert verdict.swaps == ()
    assert verdict.lactose_g == 0.0


def test_kids_notes() -> None:
    r = recipe("Wok", ingredient("chili", 1, "stk."), ingredient("cashewnøtter", 50, "g"))
    verdict = judge(
        r,
        {"chili": traits(kids=Kids.SPICY), "cashewnøtter": traits(kids=Kids.CHOKING)},
        HOUSEHOLD,
    )
    assert [w.ingredient for w in verdict.warnings if w.problem is Problem.KIDS] == [
        "chili",
        "cashewnøtter",
    ]


def test_kid_notes_can_be_off() -> None:
    r = recipe("Wok", ingredient("chili", 1, "stk."))
    verdict = judge(r, {"chili": traits(kids=Kids.SPICY)}, Household(kid_notes=False))
    assert verdict.warnings == ()


def test_unclassified_ingredient_is_noted() -> None:
    verdict = judge(recipe("Gryte", ingredient("noe nytt")), {}, HOUSEHOLD)
    assert [w.problem for w in verdict.warnings] == [Problem.UNKNOWN]


def test_an_ingredient_listed_twice_gives_one_swap() -> None:
    r = recipe("Taco", ingredient("tortilla", 4, "stk."), ingredient("tortilla", 4, "stk."))
    verdict = judge(r, {"tortilla": traits(gluten=Gluten.YES)}, HOUSEHOLD)
    assert len(verdict.swaps) == 1
