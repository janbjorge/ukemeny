"""Does a recipe fit the household? Combines per-ingredient traits with amounts."""

import re
from collections.abc import Mapping

from core.models import (
    Carbs,
    Dish,
    Fodmap,
    Gluten,
    Household,
    Ingredient,
    Item,
    Kids,
    Lactose,
    Level,
    Note,
    Onion,
    Pregnancy,
    Problem,
    Rule,
    Traits,
    Verdict,
)

GRAMS_PER_UNIT: Mapping[str, float] = {
    "g": 1,
    "kg": 1000,
    "ml": 1,
    "cl": 10,
    "dl": 100,
    "l": 1000,
    "liter": 1000,
    "ss": 15,
    "ts": 5,
    "klype": 0.5,
    "stk": 100,
    "båt": 5,
    "beger": 300,
    "boks": 400,
    "pk": 250,
    "pakke": 250,
    "bunt": 50,
    "skive": 20,
}
"""Rough grams for matprat's units. "stk" is a medium onion or a carrot."""

LACTOSE_PER_100G: Mapping[Lactose, float] = {
    Lactose.NONE: 0.0,
    Lactose.TRACE: 0.1,
    Lactose.SOME: 3.0,
    Lactose.HIGH: 4.7,
}

DAIRY = ("/melk/melkeprodukter", "/ost")
"""matprat's dairy departments. Lactose only counts there (or with no department), since
Jev called akevitt, vineddik and riseddik lactose-rich, and matprat's labels are by hand."""

HEAVY_ONION_G_PER_PORTION = 75
"""Three medium onions for four: with nothing to use instead, leaving it out changes the dish."""

CARBS_PER_100G: Mapping[Carbs, float] = {
    Carbs.NONE: 1.0,
    Carbs.LOW: 6.0,
    Carbs.MEDIUM: 25.0,
    Carbs.HIGH: 70.0,
}
"""The middle of each of Jev's buckets (under 2 g, 2-10, 10-40, over 40 g per 100 g)."""

# Why a dinner is left out, in bokmål
ITEM_WORDS: Mapping[Item, str] = {
    Item.MILK: "melk",
    Item.EGG: "egg",
    Item.FISH: "fisk",
    Item.CRUSTACEAN: "skalldyr",
    Item.MOLLUSC: "bløtdyr",
    Item.TREE_NUT: "nøtter",
    Item.PEANUT: "peanøtter",
    Item.SOY: "soya",
    Item.SESAME: "sesam",
    Item.CELERY: "selleri",
    Item.MUSTARD: "sennep",
    Item.SULPHITE: "sulfitt",
    Item.LUPIN: "lupin",
    Item.LEGUME: "belgfrukter",
    Item.MEAT: "kjøtt",
    Item.ANIMAL: "noe fra dyr",
    Item.PORK: "svin",
    Item.ALCOHOL: "alkohol",
}

# What users read is bokmål.
ADVICE: Mapping[Problem, str] = {
    Problem.GLUTEN: "bruk en glutenfri variant",
    Problem.ONION: "dropp den, eller bruk det grønne av vårløk eller purre, gressløk eller hvitløksolje",
    Problem.GARLIC: "bruk hvitløksolje i stedet",
    Problem.LACTOSE: "bruk en laktosefri variant",
}
NOTES: Mapping[Problem, str] = {
    Problem.GLUTEN: "inneholder gluten",
    Problem.ONION: "inneholder løk",
    Problem.GARLIC: "plager mange med sensitiv mage; hvitløksolje er et trygt bytte",
}
SWAP: Mapping[Problem, str] = {
    Problem.GLUTEN: "glutenfri {}",
    Problem.ONION: "dropp {}",
    Problem.GARLIC: "hvitløksolje for {}",
    Problem.LACTOSE: "laktosefri {}",
}
"""The same swaps in a few words, for a card."""
CHECK_GLUTEN = "sjekk etiketten for hvete"
CHECK_ONION = "sjekk etiketten for løk"
SPICY_NOTE = "hold det mildt, og server det sterke ved siden av"
CHOKING_NOTE = "kutt smått eller dropp for de minste (fare for å sette i halsen)"
UNKNOWN_NOTE = "ikke vurdert ennå"


def grams(ingredient: Ingredient) -> float | None:
    per_unit = GRAMS_PER_UNIT.get(ingredient.unit.rstrip(".").lower())
    if per_unit is None or ingredient.amount is None:
        return None
    return ingredient.amount * per_unit


def _in_name(ingredient: str, recipe: str) -> bool:
    """ "løk" is in "Biff med løk", but not in "Laks med hvitløk" or "... med vårløk"."""
    pattern = rf"(?<!hvit)(?<!gress)(?<!vår){re.escape(ingredient.lower())}"
    return re.search(pattern, recipe.lower()) is not None


def _apply(rule: Rule, problem: Problem, name: str, swaps: list[Note], notes: list[Note]) -> None:
    if rule is Rule.AVOID:
        swaps.append(Note(problem, name, ADVICE[problem], SWAP[problem].format(name)))
    elif rule is Rule.NOTE:
        notes.append(Note(problem, name, NOTES[problem]))


def _left_out(t: Traits, household: Household) -> str | None:
    """Why the ingredient alone leaves the dinner out, by the strict rules: an item it holds or may hold, or advice
    for pregnant women. A label never asked about counts against it."""
    for item in sorted(household.avoid):
        if t.contains.get(item, Level.YES) is not Level.NO:
            return f"inneholder {ITEM_WORDS[item]}"
    if household.pregnant and t.pregnancy is not Pregnancy.OK:
        return "frarådes for gravide"
    return None


def _swapped(t: Traits, part_category: str) -> bool:
    """Does a swap (vårløk, glutenfri, laktosefri) already take the FODMAP out of the ingredient?"""
    dairy = (part_category.startswith(DAIRY) or not part_category) and t.lactose in (Lactose.SOME, Lactose.HIGH)
    return t.onion in (Onion.ONION, Onion.GARLIC) or t.gluten is Gluten.YES or dairy


def judge(dish: Dish, traits: Mapping[str, Traits], household: Household) -> Verdict:
    swaps: list[Note] = []
    warnings: list[Note] = []
    dairy: list[str] = []
    lactose_g = onion_g = carbs_g = 0.0
    onion_in_name: str | None = None
    left_out: str | None = None
    avoid_onion = household.onion is Rule.AVOID
    substitute = (household.onion_substitute or "").lower()

    for part in dish.parts:
        name = part.name
        t = traits.get(name)
        if t is None:
            warnings.append(Note(Problem.UNKNOWN, name, UNKNOWN_NOTE))
            continue

        if t.gluten is Gluten.YES:
            _apply(household.gluten, Problem.GLUTEN, name, swaps, warnings)
        elif t.gluten is Gluten.MAYBE and household.gluten is Rule.AVOID:
            warnings.append(Note(Problem.GLUTEN, name, CHECK_GLUTEN))

        if t.onion is Onion.ONION and substitute and substitute in name:
            pass  # The substitute itself is fine.
        elif t.onion is Onion.ONION:
            if avoid_onion and substitute:
                swaps.append(Note(Problem.ONION, name, f"bruk {substitute} i stedet", f"{substitute} for {name}"))
            else:
                _apply(household.onion, Problem.ONION, name, swaps, warnings)
            onion_g += part.grams or 0.0
            if avoid_onion and onion_in_name is None and _in_name(name, dish.name):
                onion_in_name = name
        elif t.onion is Onion.MAYBE and avoid_onion:
            warnings.append(Note(Problem.ONION, name, CHECK_ONION))
        elif t.onion is Onion.GARLIC:
            _apply(household.garlic, Problem.GARLIC, name, swaps, warnings)

        if part.category.startswith(DAIRY) or not part.category:
            lactose_g += (part.grams or 0.0) * LACTOSE_PER_100G[t.lactose] / 100
            if t.lactose in (Lactose.SOME, Lactose.HIGH):
                dairy.append(name)

        if household.kid_notes and t.kids is Kids.SPICY:
            warnings.append(Note(Problem.KIDS, name, SPICY_NOTE))
        elif household.kid_notes and t.kids is Kids.CHOKING:
            warnings.append(Note(Problem.KIDS, name, CHOKING_NOTE))

        if left_out is None and (why := _left_out(t, household)):
            left_out = f"{why} ({name})"
        if left_out is None and household.fodmap and t.fodmap in (None, Fodmap.HIGH) and not _swapped(t, part.category):
            left_out = f"mye FODMAP ({name})"
        carbs_g += (part.grams or 0.0) * CARBS_PER_100G[t.carbs or Carbs.HIGH] / 100

    limit = household.lactose_g_per_portion
    if limit is not None and lactose_g > limit:
        swaps.extend(Note(Problem.LACTOSE, name, ADVICE[Problem.LACTOSE], SWAP[Problem.LACTOSE].format(name)) for name in dairy)

    blocked = None
    carb_limit = household.carbs_g_per_portion
    if onion_in_name is not None:
        blocked = f"løk er poenget med retten ({onion_in_name})"
    elif avoid_onion and not substitute and onion_g >= HEAVY_ONION_G_PER_PORTION:
        blocked = f"mye løk (rundt {onion_g:.0f} g per porsjon)"
    elif left_out is not None:
        blocked = left_out
    elif carb_limit is not None and carbs_g > carb_limit:
        blocked = f"rundt {carbs_g:.0f} g karbohydrater per porsjon"
    elif not household.swaps and any(s.problem is not Problem.LACTOSE for s in swaps):
        blocked = "trenger et bytte"

    return Verdict(
        blocked=blocked,
        swaps=tuple(dict.fromkeys(swaps)),
        warnings=tuple(dict.fromkeys(warnings)),
        lactose_g=lactose_g,
    )
