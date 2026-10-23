"""The offline build: read every recipe from matprat.no and godt.no and this week's offers, look every ingredient name up
in the vocabulary (datasets/traits.json) and draft a row for each name it has not seen, ask Jev which discounted offers
are which ingredient, and make the snapshot. The dinners and the offers are built from the sources every time (jb
2026-10-13: "one thing, and one thing only, refresh from the sources, and build up or dataset, from scratch every time");
the vocabulary is kept and fixed by hand (jb 2026-10-22, docs/plan-model.md).

Runs on a laptop with Jev (wired in src/pipeline/datasets.py). The site only reads the result, so
the server needs no Jev key and makes no calls to matprat.no, godt.no or mattilbud.no.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from core.dishes import dish
from core.errors import SourceUnavailableError
from core.matching import CATEGORIES, candidates, not_an_ingredient, per_dinner, weight, words
from core.models import Dish, Ingredient, Offer, Recipe, RecipeRef, RefreshReport, Snapshot, Traits
from core.ports import CategoryClassifier, IngredientClassifier, OfferMatcher, OfferSource, RecipeSource
from core.units import PIECE, implied_weights, stated_weight

log = logging.getLogger("matris.build")
"""-v (info): failures and totals. -vv (debug): what each page, ingredient and offer became."""

MATCH_THRESHOLD = 0.5
"""An offer counts as the ingredient from this probability on."""

EXAMPLES = 12
"""Names per category the category classifier is shown: those the dinners use most. 30 did no better (METHOD.md §2)."""

type Progress = Callable[[str, int, int], None]
"""(step, done, due) for a person watching the build: called with done 0 as a step starts, then as each item is done.
The steps: "recipes" (matprat.no and godt.no pages), "categories" (Jev's category for a new name neither its line nor a
near-name files), "ingredients" (Jev's facts for every new name), "weights" (Jev's piece weight for every name counted in
stk without one), "catalogs" (mattilbud.no), "offers" (Jev's matches)."""


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


def examples(dinners: Iterable[Recipe], vocabulary: Mapping[str, Traits]) -> dict[str, tuple[str, ...]]:
    """Per category of ours, the names the vocabulary files there that the dinners use most, EXAMPLES at most: what the
    category classifier is shown."""
    used = Counter(i.name for r in dinners for i in r.ingredients)
    filed: dict[str, list[str]] = {category: [] for category in CATEGORIES}
    for name, t in vocabulary.items():
        if t.category in filed:
            filed[t.category].append(name)
    return {category: tuple(sorted(names, key=lambda n: (-used[n], n))[:EXAMPLES]) for category, names in filed.items()}


async def draft(
    dinners: Sequence[Recipe],
    vocabulary: Mapping[str, Traits],
    categories: CategoryClassifier,
    classifier: IngredientClassifier,
    progress: Progress | None = None,
) -> dict[str, Traits]:
    """The vocabulary with a row for every ingredient name the dinners use, sorted by name. A name without a row gets
    one drafted, once (METHOD.md §2): its category from the recipe line when the source has one (matprat.no), else from
    a name in the vocabulary with the same words (core.matching.words: «frosne erter» files «erter»), else the category
    classifier's pick of ours, each shown with `examples`; then its facts from the ingredient classifier, with that
    category as context. A name with a row is not asked about again: a wrong row is fixed by hand."""
    wanted: dict[str, Ingredient] = {}
    for ingredient in (i for r in dinners for i in r.ingredients):
        if ingredient.name not in wanted or (ingredient.category and not wanted[ingredient.name].category):
            wanted[ingredient.name] = ingredient
    new = sorted(name for name in wanted if name not in vocabulary)
    near: dict[frozenset[str], str] = {}
    for name, t in sorted(vocabulary.items()):
        near.setdefault(words(name), t.category)
    known = {name: wanted[name].category or near.get(words(name), "") for name in new}
    ask = [name for name in new if not known[name]]
    shown = examples(dinners, vocabulary)
    log.info("vocabulary: %d names without a row, %d of them with no line or near-name to file them", len(new), len(ask))
    done = 0
    if progress:
        progress("categories", done, len(ask))

    async def pick(name: str) -> str:
        nonlocal done
        category = await categories.category(name, shown)
        log.debug("%s: %s", name, category)
        done += 1
        if progress:
            progress("categories", done, len(ask))
        return category

    async with asyncio.TaskGroup() as tg:
        picks = {name: tg.create_task(pick(name)) for name in ask}
    known |= {name: task.result() for name, task in picks.items()}
    done = 0
    if progress:
        progress("ingredients", done, len(new))

    async def facts(name: str) -> Traits:
        nonlocal done
        levels = await classifier.classify(replace(wanted[name], category=known[name]), classifier.labels)
        flagged = " ".join(f"{k}={v}" for k, v in levels.items() if k != "source" and v not in ("no", "none", "ok", "low"))
        log.debug("%s (%s): %s", name, known[name], flagged or "nothing to note")
        done += 1
        if progress:
            progress("ingredients", done, len(new))
        return Traits.of({**levels, "category": known[name], "product": name})

    async with asyncio.TaskGroup() as tg:
        rows = {name: tg.create_task(facts(name)) for name in new}
    known_rows = {**vocabulary, **{name: task.result() for name, task in rows.items()}}
    counted = {i.name for r in dinners for i in r.ingredients if i.unit.rstrip(".").lower() == PIECE}
    implied = implied_weights(dish(r) for r in dinners)
    return dict(sorted((await weighed(counted, known_rows, classifier, implied, progress)).items()))


async def weighed(
    counted: Iterable[str],
    vocabulary: Mapping[str, Traits],
    classifier: IngredientClassifier,
    implied: Mapping[str, float],
    progress: Progress | None = None,
) -> dict[str, Traits]:
    """The vocabulary with a piece weight (Traits.piece_g) for every name in `counted` (the names some recipe counts in
    stk) that lacks one, asked once, as a label added later is asked only for the rows without it: Jev's band read as
    grams, with the row's category as context, or the name's own weight («kylling (ca. 1500 g)») without asking.
    `implied`, what the recipes themselves say a piece weighs (core.units.implied_weights), is logged beside Jev's;
    tests/test_traits.py holds the two within 3 times (docs/plan-per-person.md, the guards)."""
    rows = dict(vocabulary)
    to_ask = []
    for name in sorted(counted):
        if name not in rows or rows[name].piece_g is not None:
            continue
        if (grams := stated_weight(name)) is not None:
            rows[name] = replace(rows[name], piece_g=grams)
            log.debug("%s: %s g a piece, from the name", name, grams)
        else:
            to_ask.append(name)
    done = 0
    if progress:
        progress("weights", done, len(to_ask))

    async def weigh(name: str) -> float | None:
        nonlocal done
        grams = await classifier.weigh(Ingredient(name, name, None, PIECE, rows[name].category))
        said = f", the recipes say {implied[name]:.0f} g" if name in implied else ""
        log.info("%s: %s g a piece%s", name, grams, said)
        done += 1
        if progress:
            progress("weights", done, len(to_ask))
        return grams

    async with asyncio.TaskGroup() as tg:
        asked = {name: tg.create_task(weigh(name)) for name in to_ask}
    for name, task in asked.items():
        if (grams := task.result()) is not None:
            rows[name] = replace(rows[name], piece_g=grams)
    return rows


async def reweigh(base: Snapshot, classifier: IngredientClassifier, progress: Progress | None = None) -> Snapshot:
    """`base` with a piece weight for every name its dinners count in stk that lacks one (`weighed`), without reading a
    recipe page or a catalog: the step "weights" alone, on the snapshot in datasets/ (`--weights`)."""
    counted = {p.name for d in base.dishes for p in d.parts if p.unit == PIECE}
    traits = await weighed(counted, base.traits, classifier, implied_weights(base.dishes), progress)
    return replace(base, traits=dict(sorted(traits.items())))


def filed(dinners: Iterable[Recipe], vocabulary: Mapping[str, Traits]) -> list[Recipe]:
    """The dinners with every ingredient's category from the vocabulary, whatever the source said: the vocabulary is the
    truth, so a row fixed by hand holds in every dinner."""
    return [replace(r, ingredients=tuple(replace(i, category=vocabulary[i.name].category) for i in r.ingredients)) for r in dinners]


@dataclass(frozen=True, slots=True)
class Question:
    """One request to the offer matcher: a product and the offers that could be it, and for meat, fish and shellfish
    (core.matching.per_dinner) the form the recipe asks for and the dinner."""

    product: str
    offers: tuple[Offer, ...]
    form: str = ""
    dish: str = ""


async def match(
    dishes: Sequence[Dish],
    offers: Sequence[Offer],
    matcher: OfferMatcher,
    vocabulary: Mapping[str, Traits],
    threshold: float = MATCH_THRESHOLD,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, tuple[str, ...]], dict[str, dict[str, tuple[str, ...]]]]:
    """The ids of the offers a cook can buy as each ingredient that matters for the shop: per name, and for meat, fish and
    shellfish per dinner (Snapshot.matches, Snapshot.served). A question is about the product a name stands for in the
    vocabulary (Traits.product; the name itself until set), so two names of one product are asked once and both written;
    for meat, fish and shellfish it carries the form the recipe line asks for (Part.form) and the dinner (METHOD.md §2).
    Only discounted offers are asked about, since nothing else reaches a card (jb 2026-10-22: "make sure that we do not
    waaste effort on dishes that do not have any discounts"), so a dinner without one costs nothing. Snacks and pålegg are
    left out without asking (core.matching.not_an_ingredient)."""
    on_sale = [o for o in offers if o.saving]
    found: dict[str, tuple[Offer, ...]] = {}

    def could_be(product: str) -> tuple[Offer, ...]:
        if product not in found:
            found[product] = tuple(o for o in candidates(product, on_sale) if not not_an_ingredient(product, o.heading))
        return found[product]

    def product_of(name: str) -> str:
        return (t.product if (t := vocabulary.get(name)) else "") or name

    by_product: dict[str, Question] = {}
    by_dinner: dict[tuple[str, str], Question] = {}
    names: dict[str, set[str]] = {}
    dinner_names: dict[tuple[str, str], set[str]] = {}
    for d in dishes:
        for part in d.parts:
            product = product_of(part.name)
            if not weight(part) or not (maybe := could_be(product)):
                continue
            if per_dinner(part):
                by_dinner.setdefault((d.url, product), Question(product, maybe, part.form, d.name))
                dinner_names.setdefault((d.url, product), set()).add(part.name)
            else:
                by_product.setdefault(product, Question(product, maybe))
                names.setdefault(product, set()).add(part.name)
    due = len(by_product) + len(by_dinner)
    log.info(
        "offers: %d of %d discounted, %d products and %d dinner products to ask about",
        len(on_sale),
        len(offers),
        len(by_product),
        len(by_dinner),
    )
    done = 0
    if progress:
        progress(done, due)

    async def ask(q: Question) -> tuple[str, ...]:
        nonlocal done
        ranked = await matcher.rank(q.product, q.offers, q.form, q.dish)
        ids = tuple(o.id for o in q.offers if ranked.get(o.id, 0.0) >= threshold)
        log.debug(
            "%s%s%s: %d of %d offers match %s",
            q.product,
            f" ({q.form})" if q.form else "",
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
        products = {product: tg.create_task(ask(q)) for product, q in by_product.items()}
        served = {key: tg.create_task(ask(q)) for key, q in by_dinner.items()}
    matched = {name: ids for product, task in products.items() if (ids := task.result()) for name in names[product]}
    per_dish: dict[str, dict[str, tuple[str, ...]]] = {}
    for (url, product), task in sorted(served.items()):
        if ids := task.result():
            per_dish.setdefault(url, {}).update(dict.fromkeys(sorted(dinner_names[url, product]), ids))
    return dict(sorted(matched.items())), per_dish


async def snapshot(
    sources: Sequence[RecipeSource],
    vocabulary: Mapping[str, Traits],
    categories: CategoryClassifier,
    classifier: IngredientClassifier,
    offers: OfferSource,
    matcher: OfferMatcher,
    progress: Progress | None = None,
) -> tuple[Snapshot, RefreshReport]:
    """Everything the site needs, for every household: no diet rule is applied here. Recipes become Dishes: facts per
    portion, without the sources' wording (docs/plan-web.md), each part filed as the vocabulary has it (`filed`). The
    snapshot's traits are the vocabulary with the rows drafted for new names (`draft`), to be written back."""

    def step(name: str) -> Callable[[int, int], None] | None:
        return (lambda done, due: progress(name, done, due)) if progress else None

    dinners, report = await recipes(sources, step("recipes"))
    known = await draft(dinners, vocabulary, categories, classifier, progress)
    dinners = sorted(filed(dinners, known), key=lambda r: r.url)
    base = Snapshot(
        built=datetime.now(UTC),
        dishes=tuple(dish(r) for r in dinners),
        traits=known,
        offers=(),
        matches={},
        places={},
    )
    return await reprice(base, offers, matcher, progress), report


async def reprice(base: Snapshot, offers: OfferSource, matcher: OfferMatcher, progress: Progress | None = None) -> Snapshot:
    """`base`'s dinners and traits with this week's offers and their matches (`match`); the steps "catalogs" and
    "offers". The weekly refresh runs only this on the snapshot in datasets/ (jb 2026-10-22: "i want sometihng that
    fetches the updated tilbud and does the matching"), on the same footing as a full build: the form a line asks for is
    in dishes.json (Part.form)."""
    if progress:
        progress("catalogs", 0, 1)
    current = await offers.current()
    if progress:
        progress("catalogs", 1, 1)
    step = (lambda done, due: progress("offers", done, due)) if progress else None
    matched, served = await match(base.dishes, current.offers, matcher, base.traits, progress=step)
    return replace(
        base,
        built=datetime.now(UTC),
        offers=tuple(sorted(current.offers, key=lambda o: (o.store, o.heading, o.id))),
        matches=matched,
        places={place: tuple(sorted(catalogs)) for place, catalogs in sorted(current.places.items())},
        served=served,
    )
