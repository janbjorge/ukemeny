"""Which offers could be a recipe ingredient. A cheap word filter in front of the matcher."""

import re
from collections.abc import Iterable, Mapping, Sequence

from core.diet import DAIRY
from core.models import Dish, Item, Offer, Part

CATEGORIES = (
    "/bær",
    "/diverse",
    "/drikke",
    "/egg",
    "/fisk og sjømat",
    "/frukt",
    "/glutenfritt",
    "/grønnsaker",
    "/hermetikk",
    "/kjøtt/and/gås",
    "/kjøtt/elg/annet vilt",
    "/kjøtt/innmat",
    "/kjøtt/kalkun",
    "/kjøtt/kalvekjøtt",
    "/kjøtt/kjøttdeig/karbonadedeig",
    "/kjøtt/kylling/høns",
    "/kjøtt/lamme-/fåre-/sauekjøtt",
    "/kjøtt/pålegg",
    "/kjøtt/pølser",
    "/kjøtt/reinsdyr",
    "/kjøtt/spekemat",
    "/kjøtt/storfekjøtt",
    "/kjøtt/svinekjøtt",
    "/korn/mel/bakervarer",
    "/krydder",
    "/margarin/olje/majones",
    "/melk/melkeprodukter",
    "/melkefritt",
    "/nøtter",
    "/ost",
    "/pasta/ris",
    "/poteter",
    "/skalldyr",
    "/sopp",
    "/tørrvarer",
)
"""Our kinds of ingredient: what Part.category and Traits.category hold, and what the rules below go by. They are
matprat's 35 grocery departments until we rename or merge them (jb 2026-10-22: "model our internals according to OUR
needs"); a recipe source's own labels are put in these, or a name is filed by the vocabulary (app.build)."""

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
"""Categories that say what a dinner is built on (the main protein) or where lactose counts, and what a row of the
vocabulary filed there must hold (tests/test_traits.py)."""

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


_NEAR = _FILLER - {"tørket"}
"""The fillers a near-name drops: all of the offer filter's but «tørket», since a dried herb is its own product and
shelf («tørket chili» is not «chili»)."""


def words(name: str) -> frozenset[str]:
    """The words of an ingredient name that say what it is, so «frosne erter» has «erter»'s and «friske urter»
    «urter»'s: a name without a row in the vocabulary takes the category of a name with the same words
    (app.build.draft, METHOD.md §2)."""
    return frozenset(word for word in _WORD.findall(name.lower()) if word not in _NEAR)


def main_protein(dish: Dish) -> tuple[str, str]:
    """(group, ingredient name) of the heaviest meat, fish or shellfish in the dish, such as
    ("kylling", "kyllingfilet"). matprat's own main-ingredient label is not used: it files
    "Kyllingfilet med spekeskinke" under pork. Stock and other liquids only count when nothing solid is there:
    matprat files kjøttkraft under /kjøtt, so the stock for a surkål outweighed the pork chops. Since 2026-10-23 the
    vocabulary files stocks, bouillons and sauces under /diverse (METHOD.md §2), so they are not here at all."""
    found = [
        (p.unit not in LIQUID_UNITS, p.grams or 0.0, group, p.name)
        for p in dish.parts
        if p.category.startswith(("/kjøtt", "/fisk og sjømat", "/skalldyr"))
        for group in [next((g for prefix, g in PROTEINS.items() if p.category.startswith(prefix)), "kjøtt")]
    ]
    if not found:
        return VEGETARIAN, ""
    *_, group, name = max(found)
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
    "koppnudler",
    "nuggets",
    "postei",
    "potetgull",
    "pålegg",
    "sjokolade",
    "smårett",
    "snacks",
)
"""Offers with these in the heading are never a recipe ingredient, unless the ingredient's
own name has the word too (hamburgerbrød). Jev said yes to MAARUD POTETGULL for «potet» in 239 of the dinners listed
on 2026-10-23, and to COOP KOPPNUDLER for «nudler»."""


def heading_key(heading: str) -> str:
    """Offers with the same heading are the same product, whatever the chain."""
    return " ".join(heading.lower().split())


def not_an_ingredient(ingredient: str, heading: str) -> bool:
    """A snack or pålegg, which needs no classifier. An offer named like the ingredient is still asked about: «Tunfisk»
    is King Oskar's tin, no tuna for sushi."""
    key = heading_key(heading)
    return any(word in key and word not in ingredient for word in NOT_AN_INGREDIENT)


PER_DINNER = ("/kjøtt", "/fisk og sjømat", "/skalldyr")
"""Departments whose offers are matched per dinner, with the recipe's line: the dinner says whether tunfisk is raw or
tinned, laks fresh or smoked, ribbe raw or grilled. Other ingredients are matched by name (METHOD.md §2)."""


def per_dinner(part: Part) -> bool:
    return part.category.startswith(PER_DINNER)


def cheapest_first(offers: Sequence[Offer]) -> tuple[Offer, ...]:
    return tuple(sorted(offers, key=lambda o: o.unit_price))
