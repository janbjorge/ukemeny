"""The offline build: keep the recipe library current, classify ingredients, match this week's offers.

Runs on a laptop with Jev (wired in src/pipeline/datasets.py). The site only reads the result, so
the server needs no Jev key and makes no calls to matprat.no or mattilbud.no.
"""

import asyncio
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime

from core.dishes import dish
from core.errors import SourceUnavailableError
from core.matching import candidates, heading_key, obvious, weight
from core.models import Ingredient, Offer, RecipeRef, RefreshReport, Snapshot, Traits
from core.ports import (
    IngredientClassifier,
    OfferMatcher,
    OfferMatchStore,
    OfferSource,
    RecipeSource,
    RecipeStore,
    TraitsStore,
)

MATCH_THRESHOLD = 0.5
"""An offer counts as the ingredient from this probability on."""


async def refresh(
    source: RecipeSource,
    store: RecipeStore,
    limit: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> RefreshReport:
    """Fetch recipe pages that are new or changed since the last refresh. The source decides how
    fast; pages that fail are retried on the next refresh. `progress` gets (done, due)."""
    listed = await source.index()
    known = await store.known()
    due = [ref for ref in listed if known.get(ref.url) != ref.lastmod][:limit]
    done = failed = 0

    async def one(ref: RecipeRef) -> None:
        nonlocal done, failed
        try:
            recipe = await source.fetch(ref.url)
        except SourceUnavailableError:
            failed += 1
        else:
            await store.save(ref, recipe)
        done += 1
        if progress:
            progress(done, len(due))

    async with asyncio.TaskGroup() as tg:
        for ref in due:
            tg.create_task(one(ref))
    return RefreshReport(listed=len(listed), fetched=done - failed, failed=failed, dinners=len(await store.dinners()))


async def classify(ingredients: Iterable[Ingredient], store: TraitsStore, classifier: IngredientClassifier) -> dict[str, Traits]:
    """Traits per ingredient name. Only names not seen before go to the classifier."""
    wanted: dict[str, Ingredient] = {}
    for ingredient in ingredients:
        wanted.setdefault(ingredient.name, ingredient)
    known = await store.get_many(wanted)
    missing = sorted(wanted.keys() - known.keys())
    if missing:
        async with asyncio.TaskGroup() as tg:
            tasks = {name: tg.create_task(classifier.classify(wanted[name])) for name in missing}
        new = {name: task.result() for name, task in tasks.items()}
        await store.save_many(new)
        known |= new
    return known


async def match(
    names: Iterable[str],
    offers: Sequence[Offer],
    store: OfferMatchStore,
    matcher: OfferMatcher,
    threshold: float = MATCH_THRESHOLD,
) -> dict[str, tuple[str, ...]]:
    """Per ingredient name, the ids of the offers a cook can buy as it. The matcher is only asked
    about (ingredient, offer heading) pairs that are neither stored from an earlier week nor obvious."""
    lookups = {name: found for name in sorted(set(names)) if (found := candidates(name, offers))}
    pairs = {(name, heading_key(o.heading)) for name, found in lookups.items() for o in found}
    scores = await store.get_many(pairs)
    for pair in pairs - scores.keys():
        if (answer := obvious(*pair)) is not None:
            scores[pair] = answer
    ask = {
        name: unknown for name, found in lookups.items() if (unknown := [o for o in found if (name, heading_key(o.heading)) not in scores])
    }
    async with asyncio.TaskGroup() as tg:
        tasks = {name: tg.create_task(matcher.rank(name, found)) for name, found in ask.items()}
    new = {(name, heading_key(o.heading)): tasks[name].result().get(o.id, 0.0) for name, found in ask.items() for o in found}
    await store.save_many(new)
    scores |= new
    matched: dict[str, tuple[str, ...]] = {}
    for name, found in lookups.items():
        ids = tuple(o.id for o in found if scores[name, heading_key(o.heading)] >= threshold)
        if ids:
            matched[name] = ids
    return matched


async def snapshot(
    recipes: RecipeStore,
    traits: TraitsStore,
    classifier: IngredientClassifier,
    offers: OfferSource,
    matches: OfferMatchStore,
    matcher: OfferMatcher,
) -> Snapshot:
    """Everything the site needs, for every household: no diet rule is applied here. Recipes become
    Dishes: facts per portion, without matprat's wording (docs/plan-web.md)."""
    dinners = await recipes.dinners()
    known = await classify((i for r in dinners for i in r.ingredients), traits, classifier)
    current = await offers.current()
    dishes = tuple(dish(r) for r in sorted(dinners, key=lambda r: r.url))
    shoppable = (p.name for d in dishes for p in d.parts if weight(p))
    matched = await match(shoppable, current, matches, matcher)
    return Snapshot(
        built=datetime.now(UTC),
        dishes=dishes,
        traits=dict(sorted(known.items())),
        offers=tuple(sorted(current, key=lambda o: (o.store, o.heading, o.id))),
        matches=dict(sorted(matched.items())),
    )
