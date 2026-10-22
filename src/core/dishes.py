"""From a full recipe to the Dish the site keeps: facts only, per portion, without the source's wording.
Rules are applied at runtime (core.diet, core.ranking), so a new rule needs no new data."""

import re
from collections.abc import Mapping

from core.diet import grams
from core.models import Dish, Part, Recipe

ROUND_G = 5
"""Grams per portion are rounded to this: enough for any rule, and no copy of the source's amounts."""

FORMS: Mapping[str, tuple[str, ...]] = {
    "røkt": ("røkt", "røkte", "varmrøkt", "kaldrøkt", "røykt"),
    "hermetisk": ("hermetisk", "hermetiske", "hermetikk", "boks", "bokser"),
    "tørket": ("tørket", "tørkede", "tørka"),
    "grillet": ("grillet", "grillede", "ferdiggrillet"),
    "kokt": ("kokt", "kokte", "ferdigkokt", "ferdigkokte"),
    "speket": ("speket", "spekete", "spekt"),
    "frossen": ("frossen", "frosne", "fryst", "fryste"),
    "saltet": ("saltet", "saltede", "lettsaltet"),
    "marinert": ("marinert", "marinerte"),
    "panert": ("panert", "panerte"),
    "fersk": ("fersk", "ferske", "rå"),
}
"""The forms a recipe line can ask for an ingredient in, by the word Part.form keeps, each with the words that say it.
The offer matcher is told the form, so a tin is no tuna for nigiri and smoked salmon no laks for a fillet (METHOD.md
§2). The first form named on the line counts; a line that names none means what the name means."""

_WORD = re.compile(r"[a-zæøåéü]+")
_SAID = {word: form for form, words in FORMS.items() for word in words}


def form(line: str) -> str:
    """The form the recipe line asks for ("røkt" for «200 g røkt laksefilet», "hermetisk" for «1 boks tunfisk»), or ""."""
    return next((_SAID[word] for word in _WORD.findall(line.lower()) if word in _SAID), "")


def dish(recipe: Recipe) -> Dish:
    portions = max(recipe.portions, 1)

    def per_portion(g: float | None) -> float | None:
        return None if g is None else round(g / portions / ROUND_G) * ROUND_G

    return Dish(
        url=recipe.url,
        name=recipe.name,
        portions=recipe.portions,
        prep_time=recipe.prep_time,
        rating=recipe.rating,
        rating_count=recipe.rating_count,
        parts=tuple(Part(i.name, i.category, per_portion(grams(i)), i.unit.rstrip(".").lower(), form(i.text)) for i in recipe.ingredients),
    )
