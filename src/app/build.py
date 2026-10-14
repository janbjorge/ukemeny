"""The offline build: read every recipe from matprat.no and godt.no and this week's offers, ask Jev about every
ingredient and offer, and make the snapshot. From scratch every time, with nothing kept between runs (jb 2026-10-13: "one thing,
and one thing only, refresh from the sources, and build up or dataset, from scratch every time").

Runs on a laptop with Jev (wired in src/pipeline/datasets.py). The site only reads the result, so
the server needs no Jev key and makes no calls to matprat.no, godt.no or mattilbud.no.
"""

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from core.dishes import dish
from core.errors import SourceUnavailableError
from core.matching import ELSEWHERE, agrees, candidates, doubted, heading_key, obvious, weight
from core.models import Ingredient, Offer, Recipe, RecipeRef, RefreshReport, Snapshot, Traits
from core.ports import DepartmentClassifier, IngredientClassifier, OfferMatcher, OfferSource, RecipeSource

log = logging.getLogger("matris.build")
"""-v (info): failures and totals. -vv (debug): what each page, ingredient and offer became."""

MATCH_THRESHOLD = 0.5
"""An offer counts as the ingredient from this probability on."""

EXAMPLES = 12
"""Names per department the department classifier is shown: those filed there most often. 30 did no better (METHOD.md §2)."""

type Progress = Callable[[str, int, int], None]
"""(step, done, due) for a person watching the build: called with done 0 as a step starts, then as each item is done.
The steps: "recipes" (matprat.no and godt.no pages), "ingredients" (Jev's labels), "departments" (Jev's departments
for godt.no's ingredients), "catalogs" (mattilbud.no), "offers" (Jev's matches)."""


async def recipes(
    sources: Sequence[RecipeSource], progress: Callable[[int, int], None] | None = None
) -> tuple[list[Recipe], RefreshReport]:
    """Every dinner the sources list. Each source decides how fast; a page that fails is left out and counted."""
    listed = [(source, ref) for source in sources for ref in await source.index()]
    dinners: list[Recipe] = []
    done = failed = 0
    if progress:
        progress(done, len(listed))

    async def one(source: RecipeSource, ref: RecipeRef) -> None:
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
        for source, ref in listed:
            tg.create_task(one(source, ref))
    log.info("recipes: %d dinners from %d pages, %d failed", len(dinners), len(listed), failed)
    return dinners, RefreshReport(listed=len(listed), fetched=done - failed, failed=failed, dinners=len(dinners))


def dishes_of(dinners: Iterable[Recipe]) -> dict[str, str]:
    """Per ingredient name no recipe files under a department (godt.no's), the first dinner by URL that uses it."""
    filed = {i.name for r in dinners for i in r.ingredients if i.category}
    found: dict[str, str] = {}
    for r in sorted(dinners, key=lambda r: r.url):
        for i in r.ingredients:
            if i.name not in filed:
                found.setdefault(i.name, r.name)
    return found


async def fill_departments(
    dinners: Sequence[Recipe],
    classifier: DepartmentClassifier,
    traits: Mapping[str, Traits],
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[Recipe], dict[str, Traits]]:
    """Every ingredient with a grocery department, and the traits. One without (godt.no names none) gets the department
    its name is filed under in other recipes (matprat.no's; the most used), or else the classifier picks one of those
    departments, each shown with the names filed there most often, and a dinner it is in. A pick of meat, fish, shellfish
    or dairy the traits do not agree with is /diverse, and the traits get «maybe» for it (core.matching.doubted;
    METHOD.md §2)."""
    filed: defaultdict[str, Counter[str]] = defaultdict(Counter)
    shelves: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for r in sorted(dinners, key=lambda r: r.url):
        for i in r.ingredients:
            if i.category:
                filed[i.name][i.category] += 1
                shelves[i.category][i.name] += 1
    known = {name: counts.most_common(1)[0][0] for name, counts in filed.items()}
    examples = {department: tuple(n for n, _ in names.most_common(EXAMPLES)) for department, names in sorted(shelves.items())}
    missing = {i.name for r in dinners for i in r.ingredients if not i.category}
    ask = sorted(missing - known.keys()) if examples else []
    used_in = dishes_of(dinners)
    settled = dict(traits)
    log.info("departments: %d names filed as in other recipes, %d to ask", len(missing & known.keys()), len(ask))
    done = 0
    if progress:
        progress(done, len(ask))

    async def one(name: str) -> str:
        nonlocal done
        picked = await classifier.department(name, examples, used_in.get(name, ""))
        department = picked
        if name in traits and not agrees(picked, traits[name]):
            department, settled[name] = ELSEWHERE, doubted(picked, traits[name])
            log.debug("%s: %s, not %s: the traits disagree, so they say maybe", name, department, picked)
        else:
            log.debug("%s: %s", name, department)
        done += 1
        if progress:
            progress(done, len(ask))
        return department

    async with asyncio.TaskGroup() as tg:
        tasks = {name: tg.create_task(one(name)) for name in ask}
    known |= {name: task.result() for name, task in tasks.items()}
    filled = [
        replace(r, ingredients=tuple(i if i.category else replace(i, category=known.get(i.name, "")) for i in r.ingredients))
        for r in dinners
    ]
    return filled, settled


async def classify(
    dinners: Sequence[Recipe],
    classifier: IngredientClassifier,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Traits]:
    """Traits per ingredient name: every label, one request per name. The department, when a recipe has one for the
    name, goes with it; a name only godt.no uses goes with a dinner it is in instead (METHOD.md §2)."""
    wanted: dict[str, Ingredient] = {}
    for ingredient in (i for r in dinners for i in r.ingredients):
        if ingredient.name not in wanted or (ingredient.category and not wanted[ingredient.name].category):
            wanted[ingredient.name] = ingredient
    used_in = dishes_of(dinners)
    done = 0
    if progress:
        progress(done, len(wanted))

    async def one(name: str) -> Traits:
        nonlocal done
        levels = await classifier.classify(wanted[name], classifier.labels, used_in.get(name, ""))
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
    sources: Sequence[RecipeSource],
    departments: DepartmentClassifier,
    classifier: IngredientClassifier,
    offers: OfferSource,
    matcher: OfferMatcher,
    progress: Progress | None = None,
) -> tuple[Snapshot, RefreshReport]:
    """Everything the site needs, for every household: no diet rule is applied here. Recipes become
    Dishes: facts per portion, without the sources' wording (docs/plan-web.md)."""

    def step(name: str) -> Callable[[int, int], None] | None:
        return (lambda done, due: progress(name, done, due)) if progress else None

    dinners, report = await recipes(sources, step("recipes"))
    known = await classify(dinners, classifier, step("ingredients"))
    dinners, known = await fill_departments(dinners, departments, known, step("departments"))
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
