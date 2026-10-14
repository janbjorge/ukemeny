"""Which offers could be a recipe ingredient. A cheap word filter in front of the matcher."""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from core.diet import DAIRY
from core.models import Dish, Item, Level, Offer, Part, Traits

WEIGHTS: Mapping[str, float] = {
    "/kjøtt": 3.0,
    "/fisk og sjømat": 3.0,
    "/skalldyr": 3.0,
    "/egg": 1.0,
    "/grønnsaker": 1.0,
    "/poteter": 1.0,
    "/sopp": 1.0,
    "/frukt": 0.5,
    "/ost": 0.5,
    "/pasta/ris": 0.5,
}
"""matprat ingredient categories worth looking up in the offers, by how much a deal on them
counts. Spices, oil, flour and other pantry goods are left out."""

PROTEINS: Mapping[str, str] = {
    "/fisk og sjømat": "fisk",
    "/skalldyr": "skalldyr",
    "/kjøtt/kylling": "kylling",
    "/kjøtt/kalkun": "kalkun",
    "/kjøtt/and": "and",
    "/kjøtt/kjøttdeig": "kjøttdeig",
    "/kjøtt/svinekjøtt": "svin",
    "/kjøtt/pølser": "pølser",
    "/kjøtt/storfekjøtt": "storfe",
    "/kjøtt/kalvekjøtt": "storfe",
    "/kjøtt/lamme": "lam",
    "/kjøtt/reinsdyr": "vilt",
    "/kjøtt/elg": "vilt",
}
"""Protein groups by matprat department. Other meat (spekemat, pålegg, innmat) is "kjøtt"."""
VEGETARIAN = "vegetar"
FISH = "fisk"

HOLDS: Mapping[str | tuple[str, ...], tuple[Item, ...]] = {
    "/kjøtt": (Item.MEAT,),
    "/fisk og sjømat": (Item.FISH, Item.CRUSTACEAN, Item.MOLLUSC),
    "/skalldyr": (Item.CRUSTACEAN, Item.MOLLUSC),
    DAIRY: (Item.MILK,),
}
"""Departments that say what a dinner is built on (the main protein) or where lactose counts, and what an ingredient
filed there holds."""
ELSEWHERE = "/diverse"
"""matprat's department for what has none of its own."""

FULL_WEIGHT_G = 100
"""Per portion, from this amount an ingredient counts fully: 150 g kyllingfilet does, 25 g bacon a quarter."""
LIQUID_UNITS = frozenset({"dl", "l", "liter", "ml", "cl", "ss", "ts"})
LIQUID_WEIGHT = 0.5
"""Stock and cream: matprat files kjøttkraft under /kjøtt, but the dinner is not about it."""

STEM = 5
"""Norwegian compounds share their first part: "lakse" finds LAKSEFILET for "laksefilet"."""

_WORD = re.compile(r"[a-zæøåéü]{3,}")
_FILLER = frozenset(
    {
        "beinfri",
        "benfri",
        "eller",
        "fersk",
        "ferske",
        "frisk",
        "friske",
        "frossen",
        "frosne",
        "grønn",
        "grønne",
        "gul",
        "gule",
        "hakket",
        "hele",
        "hvit",
        "hvite",
        "kokt",
        "kokte",
        "med",
        "norsk",
        "norske",
        "revet",
        "rød",
        "røde",
        "skinn",
        "skinnfri",
        "små",
        "store",
        "tørket",
        "uten",
    }
)


def weight(part: Part) -> float:
    """How much a deal on this ingredient counts for the dinner, by category and amount."""
    base = max((w for prefix, w in WEIGHTS.items() if part.category.startswith(prefix)), default=0.0)
    if not base:
        return 0.0
    if part.unit in LIQUID_UNITS:
        return min(base, LIQUID_WEIGHT)
    return base / 2 if part.grams is None else base * min(1.0, part.grams / FULL_WEIGHT_G)


def agrees(category: str, traits: Traits) -> bool:
    """Whether the traits allow a department a classifier picked: one of meat, fish, shellfish or dairy needs Jev's yes
    that the ingredient holds it, asked without the department (METHOD.md §2)."""
    items = next((items for prefix, items in HOLDS.items() if category.startswith(prefix)), ())
    return not items or any(traits.contains.get(item) is Level.YES for item in items)


def doubted(category: str, traits: Traits) -> Traits:
    """The traits with «maybe» for what a picked department holds, when they disagree with it (`agrees`): one of Jev's
    answers says it may be there, so a rule that leaves it out leaves the ingredient out (METHOD.md §1, §2)."""
    if agrees(category, traits):
        return traits
    items = next(items for prefix, items in HOLDS.items() if category.startswith(prefix))
    return replace(traits, contains={**traits.contains, **{item: Level.MAYBE for item in items}})


def main_protein(dish: Dish) -> tuple[str, str]:
    """(group, ingredient name) of the heaviest meat, fish or shellfish in the dish, such as
    ("kylling", "kyllingfilet"). matprat's own main-ingredient label is not used: it files
    "Kyllingfilet med spekeskinke" under pork."""
    found = [
        (p.grams or 0.0, group, p.name)
        for p in dish.parts
        if p.category.startswith(("/kjøtt", "/fisk og sjømat", "/skalldyr"))
        for group in [next((g for prefix, g in PROTEINS.items() if p.category.startswith(prefix)), "kjøtt")]
    ]
    if not found:
        return VEGETARIAN, ""
    _, group, name = max(found)
    return group, name


def stems(name: str) -> set[str]:
    return {word[:STEM] for word in _WORD.findall(name.lower()) if word not in _FILLER}


def candidates(name: str, offers: Iterable[Offer], limit: int = 120) -> list[Offer]:
    """Offers whose heading shares a word stem with the ingredient name."""
    wanted = stems(name)
    if not wanted:
        return []
    found = [o for o in offers if any(stem in o.heading.lower() for stem in wanted)]
    return found[:limit]


NOT_AN_INGREDIENT = (
    "burger",
    "chips",
    "godteri",
    "kjeks",
    "nuggets",
    "postei",
    "pålegg",
    "sjokolade",
    "smårett",
    "snacks",
)
"""Offers with these in the heading are never a recipe ingredient, unless the ingredient's
own name has the word too (hamburgerbrød)."""


def heading_key(heading: str) -> str:
    """Offers with the same heading are the same product, whatever the chain."""
    return " ".join(heading.lower().split())


def obvious(ingredient: str, heading: str) -> float | None:
    """Answers that need no classifier: an offer named exactly like the ingredient is it,
    a snack or pålegg is not. None when it takes judgment."""
    key = heading_key(heading)
    if key == ingredient:
        return 1.0
    if any(word in key and word not in ingredient for word in NOT_AN_INGREDIENT):
        return 0.0
    return None


def cheapest_first(offers: Sequence[Offer]) -> tuple[Offer, ...]:
    return tuple(sorted(offers, key=lambda o: o.unit_price))
