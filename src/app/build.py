"""The offline build: read every recipe from matprat.no and this week's offers, ask Jev about every ingredient and
offer, and make the snapshot. From scratch every time, with nothing kept between runs (jb 2026-10-13: "one thing,
and one thing only, refresh from the sources, and build up or dataset, from scratch every time").

Runs on a laptop with Jev (wired in src/pipeline/datasets.py). The site only reads the result, so
the server needs no Jev key and makes no calls to matprat.no or mattilbud.no.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime

from core.dishes import dish
from core.errors import SourceUnavailableError
from core.matching import candidates, heading_key, obvious, weight
from core.models import Ingredient, Offer, Recipe, RecipeRef, RefreshReport, Snapshot, Traits
from core.ports import IngredientClassifier, OfferMatcher, OfferSource, RecipeSource

log = logging.getLogger("matris.build")
"""-v (info): failures and totals. -vv (debug): what each page, ingredient and offer became."""

MATCH_THRESHOLD = 0.5
"""An offer counts as the ingredient from this probability on."""

type Progress = Callable[[str, int, int], None]
"""(step, done, due) for a person watching the build: called with done 0 as a step starts, then as each item is done.
The steps: "recipes" (matprat.no pages), "ingredients" (Jev's labels), "catalogs" (mattilbud.no), "offers" (Jev's matches)."""


async def recipes(source: RecipeSource, progress: Callable[[int, int], None] | None = None) -> tuple[list[Recipe], RefreshReport]:
    """Every dinner the source lists. The source decides how fast; a page that fails is left out and counted."""
    listed = await source.index()
    dinners: list[Recipe] = []
    done = failed = 0
    if progress:
        progress(done, len(listed))

    async def one(ref: RecipeRef) -> None:
        nonlocal done, failed
        try:
            recipe = await source.fetch(ref.url)
        except SourceUnavailableError as e:
            failed += 1
            log.info("failed: %s (%s)", ref.url, e)
        else:
            if recipe is not None and recipe.is_dinner:
                dinners.append(recipe)
                log.debug("dinner: %s (%d ingredients) %s", recipe.name, len(recipe.ingredients), ref.url)
            else:
                log.debug("%s: %s", "no recipe" if recipe is None else "not a dinner", ref.url)
        done += 1
        if progress:
            progress(done, len(listed))

    async with asyncio.TaskGroup() as tg:
        for ref in listed:
            tg.create_task(one(ref))
    log.info("matprat.no: %d dinners from %d pages, %d failed", len(dinners), len(listed), failed)
    return dinners, RefreshReport(listed=len(listed), fetched=done - failed, failed=failed, dinners=len(dinners))


async def classify(
    ingredients: Iterable[Ingredient],
    classifier: IngredientClassifier,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Traits]:
    """Traits per ingredient name: every label, one request per name."""
    wanted: dict[str, Ingredient] = {}
    for ingredient in ingredients:
        wanted.setdefault(ingredient.name, ingredient)
    done = 0
    if progress:
        progress(done, len(wanted))

    async def one(name: str) -> Traits:
        nonlocal done
        levels = await classifier.classify(wanted[name], classifier.labels)
        flagged = " ".join(f"{k}={v}" for k, v in levels.items() if k != "model" and v not in ("no", "none", "ok", "low"))
        log.debug("%s (%s): %s", name, wanted[name].category, flagged or "nothing to note")
        done += 1
        if progress:
            progress(done, len(wanted))
        return Traits.of(levels)

    async with asyncio.TaskGroup() as tg:
        tasks = {name: tg.create_task(one(name)) for name in sorted(wanted)}
    return {name: task.result() for name, task in tasks.items()}


async def match(
    names: Iterable[str],
    offers: Sequence[Offer],
    matcher: OfferMatcher,
    threshold: float = MATCH_THRESHOLD,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Per ingredient name, the ids of the offers a cook can buy as it. The matcher is asked about every
    (ingredient, offer heading) pair that is not obvious (core.matching.obvious)."""
    lookups = {name: found for name in sorted(set(names)) if (found := candidates(name, offers))}
    scores: dict[tuple[str, str], float] = {}
    ask: dict[str, list[Offer]] = {}
    for name, found in lookups.items():
        for o in found:
            pair = (name, heading_key(o.heading))
            if (answer := obvious(*pair)) is not None:
                scores[pair] = answer
            else:
                ask.setdefault(name, []).append(o)
    log.info("offers: %d ingredients with candidates, %d pairs settled without Jev", len(lookups), len(scores))
    done = 0
    if progress:
        progress(done, len(ask))

    async def one(name: str, found: Sequence[Offer]) -> Mapping[str, float]:
        nonlocal done
        ranked = await matcher.rank(name, found)
        hits = sorted({o.heading for o in found if ranked.get(o.id, 0.0) >= threshold})
        log.debug("%s: %d of %d offers match %s", name, len(hits), len(found), hits)
        done += 1
        if progress:
            progress(done, len(ask))
        return ranked

    async with asyncio.TaskGroup() as tg:
        tasks = {name: tg.create_task(one(name, found)) for name, found in ask.items()}
    scores |= {(name, heading_key(o.heading)): tasks[name].result().get(o.id, 0.0) for name, found in ask.items() for o in found}
    matched: dict[str, tuple[str, ...]] = {}
    for name, found in lookups.items():
        ids = tuple(o.id for o in found if scores[name, heading_key(o.heading)] >= threshold)
        if ids:
            matched[name] = ids
    return matched


async def snapshot(
    source: RecipeSource,
    classifier: IngredientClassifier,
    offers: OfferSource,
    matcher: OfferMatcher,
    progress: Progress | None = None,
) -> tuple[Snapshot, RefreshReport]:
    """Everything the site needs, for every household: no diet rule is applied here. Recipes become
    Dishes: facts per portion, without matprat's wording (docs/plan-web.md)."""

    def step(name: str) -> Callable[[int, int], None] | None:
        return (lambda done, due: progress(name, done, due)) if progress else None

    dinners, report = await recipes(source, step("recipes"))
    known = await classify((i for r in dinners for i in r.ingredients), classifier, step("ingredients"))
    if progress:
        progress("catalogs", 0, 1)
    current = await offers.current()
    if progress:
        progress("catalogs", 1, 1)
    dishes = tuple(dish(r) for r in sorted(dinners, key=lambda r: r.url))
    shoppable = (p.name for d in dishes for p in d.parts if weight(p))
    matched = await match(shoppable, current.offers, matcher, progress=step("offers"))
    built = Snapshot(
        built=datetime.now(UTC),
        dishes=dishes,
        traits=dict(sorted(known.items())),
        offers=tuple(sorted(current.offers, key=lambda o: (o.store, o.heading, o.id))),
        matches=dict(sorted(matched.items())),
        places={place: tuple(sorted(catalogs)) for place, catalogs in sorted(current.places.items())},
    )
    return built, report
