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
SPRING_ONION_OK = Household(onion_ok="vårløk")
DAIRY = "/melk/melkeprodukter"


def test_plain_recipe_fits_as_is() -> None:
    r = recipe("Kylling med ris", ingredient("kyllingfilet", 600, "g"), ingredient("ris", 3, "dl"))
    verdict = judge(r, {"kyllingfilet": PLAIN, "ris": PLAIN}, HOUSEHOLD)
    assert verdict.blocked is None
    assert verdict.warnings == ()


def test_gluten_or_onion_leaves_the_dinner_out_with_nothing_swapped() -> None:
    r = recipe("Laks med nudler", ingredient("eggnudler", 250, "g"), ingredient("rødløk", 1, "stk."))
    known = {"eggnudler": traits(gluten=Gluten.YES), "rødløk": traits(onion=Onion.ONION)}
    assert judge(r, known, HOUSEHOLD).blocked == "inneholder gluten (eggnudler)"  # the first one says why
    assert judge(r, known, Household(gluten=Rule.OK)).blocked == "inneholder løk (rødløk)"


def test_maybe_is_a_warning_to_check_the_label() -> None:
    r = recipe("Gryte", ingredient("buljongterning", 1, "stk."))
    verdict = judge(r, {"buljongterning": traits(gluten=Gluten.MAYBE, onion=Onion.MAYBE)}, HOUSEHOLD)
    assert verdict.blocked is None
    assert {w.problem for w in verdict.warnings} == {Problem.GLUTEN, Problem.ONION}


def test_garlic_is_not_onion() -> None:
    r = recipe("Laks med hvitløk", ingredient("hvitløk", 2, "båt"))
    assert judge(r, {"hvitløk": traits(onion=Onion.GARLIC)}, HOUSEHOLD).blocked is None


def test_one_onion_for_four_leaves_the_dinner_out() -> None:
    r = recipe("Lapskaus", ingredient("løk", 1, "stk."), portions=4)
    assert judge(r, {"løk": traits(onion=Onion.ONION)}, HOUSEHOLD).blocked == "inneholder løk (løk)"


def test_spring_onion_is_fine() -> None:
    r = recipe("Laks med vårløk", ingredient("vårløk", 1, "bunt"))
    known = {"vårløk": traits(onion=Onion.ONION)}
    assert judge(r, known, HOUSEHOLD).blocked == "inneholder løk (vårløk)"
    assert judge(r, known, SPRING_ONION_OK).blocked is None
    with_onion = recipe("Laks med vårløk", ingredient("vårløk", 1, "bunt"), ingredient("løk", 1, "stk."))
    assert judge(with_onion, known | {"løk": traits(onion=Onion.ONION)}, SPRING_ONION_OK).blocked == "inneholder løk (løk)"


def test_rules_note_and_ok() -> None:
    r = recipe("Biff med løk", ingredient("løk", 3, "stk."), ingredient("spaghetti", 400, "g"))
    known = {"løk": traits(onion=Onion.ONION), "spaghetti": traits(gluten=Gluten.YES)}
    noted = judge(r, known, Household(onion=Rule.NOTE, gluten=Rule.NOTE))
    assert noted.blocked is None
    assert {w.problem for w in noted.warnings} == {Problem.ONION, Problem.GLUTEN}
    fine = judge(r, known, Household(onion=Rule.OK, gluten=Rule.OK))
    assert (fine.blocked, fine.warnings) == (None, ())


def test_no_lactose_limit() -> None:
    r = recipe("Grøt", ingredient("melk", 1, "l", DAIRY), portions=2)
    verdict = judge(r, {"melk": traits(lactose=Lactose.HIGH)}, Household(lactose_g_per_portion=None))
    assert verdict.blocked is None


def test_garlic_is_a_note_unless_the_household_avoids_it() -> None:
    r = recipe("Gryte", ingredient("hvitløk", 2, "båt"))
    garlic = {"hvitløk": traits(onion=Onion.GARLIC)}
    assert [w.problem for w in judge(r, garlic, HOUSEHOLD).warnings] == [Problem.GARLIC]
    assert judge(r, garlic, Household(garlic=Rule.AVOID)).blocked == "inneholder hvitløk (hvitløk)"
    assert judge(r, garlic, Household(garlic=Rule.OK)).warnings == ()


def test_a_splash_of_cream_is_fine() -> None:
    r = recipe("Gryte", ingredient("matfløte", 1, "dl", DAIRY), portions=4)
    verdict = judge(r, {"matfløte": traits(lactose=Lactose.SOME)}, HOUSEHOLD)
    assert verdict.blocked is None
    assert round(verdict.lactose_g, 2) == 0.75


def test_a_cream_sauce_over_the_lactose_limit_is_left_out() -> None:
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
    assert verdict.blocked == "rundt 4,6 g laktose per porsjon"


def test_lactose_only_counts_in_dairy_departments() -> None:
    r = recipe("Gryte", ingredient("vineddik", 5, "dl", "/diverse"), portions=4)
    verdict = judge(r, {"vineddik": traits(lactose=Lactose.HIGH)}, HOUSEHOLD)
    assert verdict.blocked is None
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


def test_a_rule_that_leaves_an_item_out_leaves_out_maybe_and_unknown_too() -> None:
    r = recipe("Pasta carbonara", ingredient("spagetti", 400, "g"), ingredient("buljongterning", 1, "stk."))
    plain = {"spagetti": PLAIN}
    no_egg = Household(avoid=frozenset({Item.EGG}))
    assert judge(r, plain | {"buljongterning": traits(contains={Item.EGG: Level.NO})}, no_egg).blocked is None
    maybe = judge(r, plain | {"buljongterning": traits(contains={Item.EGG: Level.MAYBE})}, no_egg)
    assert maybe.blocked == "inneholder egg (buljongterning)"
    never_asked = Traits(Gluten.NO, Onion.NONE, Lactose.NONE, Kids.OK)
    assert judge(r, plain | {"buljongterning": never_asked}, no_egg).blocked == "inneholder egg (buljongterning)"


def test_fodmap_leaves_out_what_no_other_rule_judges() -> None:
    low_fodmap = Household(onion_ok="vårløk", garlic=Rule.AVOID, fodmap=True)
    r = recipe("Kyllinggryte", ingredient("kyllingfilet", 600, "g"), ingredient("vårløk", 1, "bunt"), ingredient("kikerter", 1, "boks"))
    spring_onion = traits(onion=Onion.ONION, fodmap=Fodmap.HIGH)
    verdict = judge(r, {"kyllingfilet": PLAIN, "vårløk": spring_onion, "kikerter": traits(fodmap=Fodmap.LOW)}, low_fodmap)
    assert verdict.blocked is None  # the onion rule judges vårløk, and lets it be
    chickpeas = judge(r, {"kyllingfilet": PLAIN, "vårløk": spring_onion, "kikerter": traits(fodmap=Fodmap.HIGH)}, low_fodmap)
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
