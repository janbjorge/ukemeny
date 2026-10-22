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
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from core.dishes import dish
from core.errors import SourceUnavailableError
from core.matching import ELSEWHERE, agrees, candidates, doubted, not_an_ingredient, per_dinner, weight
from core.models import Dish, Ingredient, Offer, Recipe, RecipeRef, RefreshReport, Snapshot, Traits
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


@dataclass(frozen=True, slots=True)
class Question:
    """One request to the offer matcher: an ingredient and the offers that could be it, with a dinner's context for meat,
    fish and shellfish (core.matching.per_dinner)."""

    name: str
    offers: tuple[Offer, ...]
    line: str = ""
    dish: str = ""


async def match(
    dishes: Sequence[Dish],
    offers: Sequence[Offer],
    matcher: OfferMatcher,
    lines: Mapping[str, Sequence[str]] | None = None,
    threshold: float = MATCH_THRESHOLD,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, tuple[str, ...]], dict[str, dict[str, tuple[str, ...]]]]:
    """The ids of the offers a cook can buy as each ingredient that matters for the shop: per name, and for meat, fish and
    shellfish per dinner (Snapshot.matches, Snapshot.served). Only discounted offers are asked about, since nothing else
    reaches a card (jb 2026-10-22: "make sure that we do not waaste effort on dishes that do not have any discounts"), so a
    dinner without one costs nothing. Snacks and pålegg are left out without asking (core.matching.not_an_ingredient).
    `lines`: per Dish.url, the recipe's line for each part; without them (datasets/ keeps no wording) the line is the
    ingredient's name (METHOD.md §2)."""
    on_sale = [o for o in offers if o.saving]
    found: dict[str, tuple[Offer, ...]] = {}

    def could_be(name: str) -> tuple[Offer, ...]:
        if name not in found:
            found[name] = tuple(o for o in candidates(name, on_sale) if not not_an_ingredient(name, o.heading))
        return found[name]

    by_name: dict[str, Question] = {}
    by_dinner: dict[tuple[str, str], Question] = {}
    for d in dishes:
        written = (lines or {}).get(d.url) or [p.name for p in d.parts]
        for part, line in zip(d.parts, written, strict=True):
            if not weight(part) or not (maybe := could_be(part.name)):
                continue
            if per_dinner(part):
                by_dinner.setdefault((d.url, part.name), Question(part.name, maybe, line, d.name))
            else:
                by_name.setdefault(part.name, Question(part.name, maybe))
    due = len(by_name) + len(by_dinner)
    log.info(
        "offers: %d of %d discounted, %d names and %d dinner ingredients to ask about",
        len(on_sale),
        len(offers),
        len(by_name),
        len(by_dinner),
    )
    done = 0
    if progress:
        progress(done, due)

    async def ask(q: Question) -> tuple[str, ...]:
        nonlocal done
        ranked = await matcher.rank(q.name, q.offers, q.line, q.dish)
        ids = tuple(o.id for o in q.offers if ranked.get(o.id, 0.0) >= threshold)
        log.debug(
            "%s%s: %d of %d offers match %s",
            q.name,
            f" in {q.dish}" if q.dish else "",
            len(ids),
            len(q.offers),
            sorted({o.heading for o in q.offers if o.id in ids}),
        )
        done += 1
        if progress:
            progress(done, due)
        return ids

    async with asyncio.TaskGroup() as tg:
        names = {name: tg.create_task(ask(q)) for name, q in by_name.items()}
        served = {key: tg.create_task(ask(q)) for key, q in by_dinner.items()}
    matched = {name: ids for name, task in sorted(names.items()) if (ids := task.result())}
    per_dish: dict[str, dict[str, tuple[str, ...]]] = {}
    for (url, name), task in sorted(served.items()):
        if ids := task.result():
            per_dish.setdefault(url, {})[name] = ids
    return matched, per_dish


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
    dinners = sorted(dinners, key=lambda r: r.url)
    lines = {r.url: [i.text for i in r.ingredients] for r in dinners}
    base = Snapshot(
        built=datetime.now(UTC),
        dishes=tuple(dish(r) for r in dinners),
        traits=dict(sorted(known.items())),
        offers=(),
        matches={},
        places={},
    )
    return await reprice(base, offers, matcher, progress, lines), report


async def reprice(
    base: Snapshot,
    offers: OfferSource,
    matcher: OfferMatcher,
    progress: Progress | None = None,
    lines: Mapping[str, Sequence[str]] | None = None,
) -> Snapshot:
    """`base`'s dinners and traits with this week's offers and their matches (`match`); the steps "catalogs" and
    "offers". The weekly refresh runs only this on the snapshot in datasets/ (jb 2026-10-22: "i want sometihng that
    fetches the updated tilbud and does the matching")."""
    if progress:
        progress("catalogs", 0, 1)
    current = await offers.current()
    if progress:
        progress("catalogs", 1, 1)
    step = (lambda done, due: progress("offers", done, due)) if progress else None
    matched, served = await match(base.dishes, current.offers, matcher, lines, progress=step)
    return replace(
        base,
        built=datetime.now(UTC),
        offers=tuple(sorted(current.offers, key=lambda o: (o.store, o.heading, o.id))),
        matches=matched,
        places={place: tuple(sorted(catalogs)) for place, catalogs in sorted(current.places.items())},
        served=served,
    )
