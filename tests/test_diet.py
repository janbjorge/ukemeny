from core import diet
from core.dishes import dish
from core.models import (
    Carbs,
    Fodmap,
    Gluten,
    Household,
    Item,
    Kids,
    Lactose,
    Level,
    Onion,
    Pregnancy,
    Problem,
    Recipe,
    Rule,
    Traits,
    Verdict,
)
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


def test_a_rule_that_leaves_an_item_out_leaves_out_maybe_and_unknown_too() -> None:
    r = recipe("Pasta carbonara", ingredient("spagetti", 400, "g"), ingredient("buljongterning", 1, "stk."))
    plain = {"spagetti": PLAIN}
    no_egg = Household(avoid=frozenset({Item.EGG}))
    assert judge(r, plain | {"buljongterning": traits(contains={Item.EGG: Level.NO})}, no_egg).blocked is None
    maybe = judge(r, plain | {"buljongterning": traits(contains={Item.EGG: Level.MAYBE})}, no_egg)
    assert maybe.blocked == "inneholder egg (buljongterning)"
    never_asked = Traits(Gluten.NO, Onion.NONE, Lactose.NONE, Kids.OK)
    assert judge(r, plain | {"buljongterning": never_asked}, no_egg).blocked == "inneholder egg (buljongterning)"


def test_fodmap_leaves_out_what_no_swap_takes_care_of() -> None:
    low_fodmap = Household(onion_substitute="vårløk", garlic=Rule.AVOID, fodmap=True)
    r = recipe("Kyllinggryte", ingredient("kyllingfilet", 600, "g"), ingredient("løk", 1, "stk."), ingredient("kikerter", 1, "boks"))
    onion = traits(onion=Onion.ONION, fodmap=Fodmap.HIGH)
    verdict = judge(r, {"kyllingfilet": PLAIN, "løk": onion, "kikerter": traits(fodmap=Fodmap.LOW)}, low_fodmap)
    assert verdict.blocked is None and [s.swap for s in verdict.swaps] == ["vårløk for løk"]  # the swap takes the onion out
    chickpeas = judge(r, {"kyllingfilet": PLAIN, "løk": onion, "kikerter": traits(fodmap=Fodmap.HIGH)}, low_fodmap)
    assert chickpeas.blocked == "mye FODMAP (kikerter)"


def test_low_carb_counts_grams_per_portion() -> None:
    low_carb = Household(carbs_g_per_portion=20)
    r = recipe("Laks med brokkoli", ingredient("laksefilet", 600, "g"), ingredient("brokkoli", 400, "g"))
    known = {"laksefilet": traits(carbs=Carbs.NONE), "brokkoli": traits(carbs=Carbs.LOW)}
    assert judge(r, known, low_carb).blocked is None  # 150 g fish and 100 g broccoli: about 7 g
    with_rice = recipe("Laks med ris", ingredient("laksefilet", 600, "g"), ingredient("ris", 3, "dl"))
    assert judge(with_rice, {"laksefilet": known["laksefilet"], "ris": traits(carbs=Carbs.HIGH)}, low_carb).blocked == (
        "rundt 54 g karbohydrater per porsjon"
    )


def test_pregnant_leaves_out_avoid_and_limit() -> None:
    r = recipe("Pasta med røkelaks", ingredient("røkelaks", 200, "g"))
    pregnant = Household(pregnant=True)
    assert judge(r, {"røkelaks": traits(pregnancy=Pregnancy.AVOID)}, pregnant).blocked == "frarådes for gravide (røkelaks)"
    assert judge(r, {"røkelaks": traits(pregnancy=Pregnancy.LIMIT)}, pregnant).blocked is not None
    assert judge(r, {"røkelaks": traits(pregnancy=Pregnancy.OK)}, pregnant).blocked is None
    assert judge(r, {"røkelaks": traits(pregnancy=Pregnancy.AVOID)}, Household()).blocked is None
