"""The offline build: keep the recipe library current, classify ingredients, match this week's offers.

Runs on a laptop with Jev (wired in src/pipeline/datasets.py). The site only reads the result, so
the server needs no Jev key and makes no calls to matprat.no or mattilbud.no.
"""

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
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

type Progress = Callable[[str, int, int], None]
"""(step, done, due) for a person watching the build: called with done 0 as a step starts, then as each item is done.
The steps: "recipes" (matprat.no pages), "ingredients" (Jev's labels), "catalogs" (mattilbud.no), "offers" (Jev's matches)."""


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
    if progress:
        progress(done, len(due))

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


async def classify(
    ingredients: Iterable[Ingredient],
    store: TraitsStore,
    classifier: IngredientClassifier,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Traits]:
    """Traits per ingredient name. The classifier is asked only for the labels not stored for a name, all in one
    request per name, and each answer is stored as it comes, so a run that stops halfway keeps what it got."""
    wanted: dict[str, Ingredient] = {}
    for ingredient in ingredients:
        wanted.setdefault(ingredient.name, ingredient)
    known = await store.get_many(wanted)
    missing = {name: labels for name in sorted(wanted) if (labels := [k for k in classifier.labels if k not in known.get(name, {})])}
    done = 0
    if progress:
        progress(done, len(missing))

    async def one(name: str) -> None:
        nonlocal done
        levels = await classifier.classify(wanted[name], missing[name])
        await store.save_many({name: levels})
        known[name] = {**known.get(name, {}), **levels}
        done += 1
        if progress:
            progress(done, len(missing))

    async with asyncio.TaskGroup() as tg:
        for name in missing:
            tg.create_task(one(name))
    return {name: Traits.of(levels) for name, levels in known.items()}


async def match(
    names: Iterable[str],
    offers: Sequence[Offer],
    store: OfferMatchStore,
    matcher: OfferMatcher,
    threshold: float = MATCH_THRESHOLD,
    progress: Callable[[int, int], None] | None = None,
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
    done = 0
    if progress:
        progress(done, len(ask))

    async def one(name: str, found: Sequence[Offer]) -> Mapping[str, float]:
        nonlocal done
        scores = await matcher.rank(name, found)
        done += 1
        if progress:
            progress(done, len(ask))
        return scores

    async with asyncio.TaskGroup() as tg:
        tasks = {name: tg.create_task(one(name, found)) for name, found in ask.items()}
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
    progress: Progress | None = None,
) -> Snapshot:
    """Everything the site needs, for every household: no diet rule is applied here. Recipes become
    Dishes: facts per portion, without matprat's wording (docs/plan-web.md)."""

    def step(name: str) -> Callable[[int, int], None] | None:
        return (lambda done, due: progress(name, done, due)) if progress else None

    dinners = await recipes.dinners()
    known = await classify((i for r in dinners for i in r.ingredients), traits, classifier, step("ingredients"))
    if progress:
        progress("catalogs", 0, 1)
    current = await offers.current()
    if progress:
        progress("catalogs", 1, 1)
    dishes = tuple(dish(r) for r in sorted(dinners, key=lambda r: r.url))
    shoppable = (p.name for d in dishes for p in d.parts if weight(p))
    matched = await match(shoppable, current, matches, matcher, progress=step("offers"))
    return Snapshot(
        built=datetime.now(UTC),
        dishes=dishes,
        traits=dict(sorted(known.items())),
        offers=tuple(sorted(current, key=lambda o: (o.store, o.heading, o.id))),
        matches=dict(sorted(matched.items())),
    )
