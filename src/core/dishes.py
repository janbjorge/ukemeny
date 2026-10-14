"""From a full recipe to the Dish the site keeps: facts only, per portion, without the source's wording.
Rules are applied at runtime (core.diet, core.ranking), so a new rule needs no new data."""

from core.diet import grams
from core.models import Dish, Part, Recipe

ROUND_G = 5
"""Grams per portion are rounded to this: enough for any rule, and no copy of the source's amounts."""


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
        parts=tuple(Part(i.name, i.category, per_portion(grams(i)), i.unit.rstrip(".").lower()) for i in recipe.ingredients),
    )
