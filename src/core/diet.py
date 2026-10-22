"""Does a recipe fit the household? Combines per-ingredient traits with amounts."""

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
HOLDS: Mapping[Problem, str] = {
    Problem.GLUTEN: "inneholder gluten",
    Problem.ONION: "inneholder løk",
    Problem.GARLIC: "inneholder hvitløk",
}
"""Why a rule (Rule.AVOID) leaves a dinner out. Nothing is swapped (jb 2026-10-22: "i do not want the replace x with y
options")."""
NOTES: Mapping[Problem, str] = {
    Problem.GLUTEN: "inneholder gluten",
    Problem.ONION: "inneholder løk",
    Problem.GARLIC: "plager mange med sensitiv mage; hvitløksolje er et trygt bytte",
}
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


def _apply(rule: Rule, problem: Problem, name: str, notes: list[Note]) -> str | None:
    """Why the ingredient leaves the dinner out, or None; a rule that only mentions it adds a note."""
    if rule is Rule.AVOID:
        return f"{HOLDS[problem]} ({name})"
    if rule is Rule.NOTE:
        notes.append(Note(problem, name, NOTES[problem]))
    return None


def _left_out(t: Traits, household: Household) -> str | None:
    """Why the ingredient alone leaves the dinner out, by the strict rules: an item it holds or may hold, or advice
    for pregnant women. A label never asked about counts against it."""
    for item in sorted(household.avoid):
        if t.contains.get(item, Level.YES) is not Level.NO:
            return f"inneholder {ITEM_WORDS[item]}"
    if household.pregnant and t.pregnancy is not Pregnancy.OK:
        return "frarådes for gravide"
    return None


def fodmap_elsewhere(t: Traits, part_category: str) -> bool:
    """Is the ingredient's FODMAP judged by another rule? Onion and gluten leave the dinner out (an onion that is fine,
    vårløk, stays), and dairy counts by its lactose."""
    dairy = (part_category.startswith(DAIRY) or not part_category) and t.lactose in (Lactose.SOME, Lactose.HIGH)
    return t.onion in (Onion.ONION, Onion.GARLIC) or t.gluten is Gluten.YES or dairy


def fodmap_out(t: Traits, part_category: str) -> bool:
    """High in FODMAP (or never asked), and no other rule judges it."""
    return t.fodmap in (None, Fodmap.HIGH) and not fodmap_elsewhere(t, part_category)


def carbs(t: Traits, grams: float | None) -> float:
    """Grams of carbohydrate in this much of the ingredient; never asked counts as a lot."""
    return (grams or 0.0) * CARBS_PER_100G[t.carbs or Carbs.HIGH] / 100


def judge(dish: Dish, traits: Mapping[str, Traits], household: Household) -> Verdict:
    """Whether the dinner fits as it is: the first ingredient a rule leaves out says why it does not. Nothing is swapped."""
    warnings: list[Note] = []
    lactose_g = carbs_g = 0.0
    blocked: str | None = None
    strict = bool(household.avoid) or household.pregnant
    count_carbs = household.carbs_g_per_portion is not None
    onion_ok = (household.onion_ok or "").lower()

    for part in dish.parts:
        name = part.name
        t = traits.get(name)
        if t is None:
            warnings.append(Note(Problem.UNKNOWN, name, UNKNOWN_NOTE))
            continue
        why: str | None = None

        if t.gluten is Gluten.YES:
            why = _apply(household.gluten, Problem.GLUTEN, name, warnings)
        elif t.gluten is Gluten.MAYBE and household.gluten is Rule.AVOID:
            warnings.append(Note(Problem.GLUTEN, name, CHECK_GLUTEN))

        if t.onion is Onion.ONION and onion_ok and onion_ok in name:
            pass  # An onion that is fine.
        elif t.onion is Onion.ONION:
            why = why or _apply(household.onion, Problem.ONION, name, warnings)
        elif t.onion is Onion.MAYBE and household.onion is Rule.AVOID:
            warnings.append(Note(Problem.ONION, name, CHECK_ONION))
        elif t.onion is Onion.GARLIC:
            why = why or _apply(household.garlic, Problem.GARLIC, name, warnings)

        if part.category.startswith(DAIRY) or not part.category:
            lactose_g += (part.grams or 0.0) * LACTOSE_PER_100G[t.lactose] / 100

        if household.kid_notes and t.kids is Kids.SPICY:
            warnings.append(Note(Problem.KIDS, name, SPICY_NOTE))
        elif household.kid_notes and t.kids is Kids.CHOKING:
            warnings.append(Note(Problem.KIDS, name, CHOKING_NOTE))

        if why is None and strict and (held := _left_out(t, household)):
            why = f"{held} ({name})"
        if why is None and household.fodmap and fodmap_out(t, part.category):
            why = f"mye FODMAP ({name})"
        blocked = blocked or why
        if count_carbs:
            carbs_g += carbs(t, part.grams)

    lactose_limit = household.lactose_g_per_portion
    carb_limit = household.carbs_g_per_portion
    if blocked is None and lactose_limit is not None and lactose_g > lactose_limit:
        blocked = f"rundt {lactose_g:.1f} g laktose per porsjon".replace(".", ",")
    elif blocked is None and carb_limit is not None and carbs_g > carb_limit:
        blocked = f"rundt {carbs_g:.0f} g karbohydrater per porsjon"

    return Verdict(blocked=blocked, warnings=tuple(dict.fromkeys(warnings)), lactose_g=lactose_g)
