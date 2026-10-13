"""The JSON shape of dinners, plans and recipe checks, shared by the API (/api) and `matris --json`.

No ingredient lists: the recipes belong to matprat.no, and every dinner links there.

pydantic v2 models, so the OpenAPI schema documents every field. Keys are English, for agents;
the text inside (advice) is bokmål, like the site. No label or kid notes either: they named ingredient after
ingredient, so they stay in the CLI's text output, on this machine.
"""

from collections.abc import Iterable
from datetime import date, datetime
from typing import TypedDict
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict

from app.queries import Check, Found, Queries
from core.matching import main_protein
from core.models import Dinner, Dish, Note, Plan
from core.search import Clause, Diet, Kind, Search, diet_clause, place_clause


class Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class NoteOut(Out):
    ingredient: str
    problem: str
    """gluten, onion, garlic or lactose."""
    advice: str


class DiscountOut(Out):
    ingredient: str
    store: str
    offer: str
    """The offer's heading in the store's catalog."""
    price: float
    """Kroner."""
    before: float
    """Kroner before the offer."""
    discount_percent: int
    valid_until: date


class RecipeOut(Out):
    name: str
    url: str
    protein: str
    """fisk, skalldyr, kylling, kalkun, and, kjøttdeig, svin, pølser, storfe, lam, vilt, kjøtt or vegetar."""
    protein_ingredient: str | None
    prep_time: str
    rating: float | None
    rating_count: int
    portions: int


class DinnerOut(RecipeOut):
    rank: int
    on_sale: bool
    """The main protein (or, without meat or fish, a main vegetable) is discounted this week."""
    fits_as_is: bool
    swaps: list[NoteOut]
    discounts: list[DiscountOut]
    matched: list[str] = []
    """Ingredients that hold a searched word the dish name does not."""


class CheckOut(Out):
    recipe: RecipeOut
    """The recipe itself is on matprat.no (`recipe.url`); its ingredients are not repeated here."""
    fits: bool
    blocked: str | None
    swaps: list[NoteOut]
    lactose_g_per_portion: float


class ClauseOut(Out):
    kind: str
    """diet (a rule), tag (a category), protein (the main protein is one of these), not_protein, with (a word in the
    name or an ingredient), without, order (a sort order) or place (where the offers are from)."""
    text: str
    """How the search writes it."""
    label: str
    """In bokmål, for people."""


class CorrectionOut(Out):
    typed: str
    used: str


class SearchOut(Out):
    query: str
    """The search as understood. Send it back as `q` for the same dinners."""
    understood: list[ClauseOut]
    corrected: list[CorrectionOut]
    """Words that matched nothing and were swapped for the closest known word."""
    total: int
    """Dinners that match, before `antall`."""
    without: list[ClauseOut] = []
    """With nothing found: clauses to drop for some matches, most matches first."""


class LinksOut(Out):
    """Where to go next, so an agent can combine rules by following links instead of writing URLs (ChatGPT, for one,
    opens only addresses it has seen; jb 2026-10-13)."""

    add: dict[str, str]
    """Per diet rule not in this search: this answer (the week or the list) with it."""
    remove: dict[str, str]
    """Per diet rule in this search, and its place («i bergen»): this answer without it."""
    places: dict[str, str]
    """Per place other than this search's: this answer with the offers from the stores near it."""
    plan: str
    """The week for this search's diet rules and place."""
    dinners: str
    """Every dinner for this search."""


def _rules(search: Search) -> Search:
    """What the week follows: the diet rules and the place."""
    return Search(tuple(c for c in search.clauses if c.kind in (Kind.DIET, Kind.PLACE)))


def links(base: str, search: Search, path: str, places: Iterable[str]) -> LinksOut:
    """`base` is the API's address, ending in "/" (https://matris.app/api/); `path` is this answer's ("plan", "middager")."""
    rules = _rules(search)

    def url(path: str, s: Search) -> str:
        return f"{base}{path}" + (f"?{urlencode({'q': s.text})}" if s.text else "")

    here = [place_clause(search.place)] if search.place else []
    return LinksOut(
        add={d.value: url(path, search.toggle(diet_clause(d))) for d in Diet if d not in search.diets},
        remove={d.value: url(path, search.drop(diet_clause(d))) for d in search.diets} | {c.text: url(path, search.drop(c)) for c in here},
        places={p: url(path, search.toggle(place_clause(p))) for p in places if p != search.place},
        plan=url("plan", rules),
        dinners=url("middager", search),
    )


class SnapshotOut(Out):
    considered: int
    fitting: int
    on_sale: int
    place: str | None
    """Where the offers are from: the stores near this place (`i bergen` in `q`), or, when null, every store in every
    place (`links.places`)."""
    offers: int
    built: datetime
    """When the snapshot was built; offers are from that week."""
    offers_until: date | None
    dinners: list[DinnerOut]
    links: LinksOut | None = None
    """From the API: the same search with a diet rule added or taken away, in another place, and the week or the list
    for it."""


class DinnersOut(SnapshotOut):
    search: SearchOut


class PlanOut(SnapshotOut):
    stores: list[str]


def _note(note: Note) -> NoteOut:
    return NoteOut(ingredient=note.ingredient, problem=note.problem.value, advice=note.advice)


class _DishFields(TypedDict):
    name: str
    url: str
    protein: str
    protein_ingredient: str | None
    prep_time: str
    rating: float | None
    rating_count: int
    portions: int


def _dish(dish: Dish) -> _DishFields:
    protein, main = main_protein(dish)
    return {
        "name": dish.name,
        "url": dish.url,
        "protein": protein,
        "protein_ingredient": main or None,
        "prep_time": dish.prep_time,
        "rating": dish.rating,
        "rating_count": dish.rating_count,
        "portions": dish.portions,
    }


def dinner(d: Dinner, rank: int, matched: tuple[str, ...] = ()) -> DinnerOut:
    discounts = [
        DiscountOut(
            ingredient=b.part.name,
            store=sale.store,
            offer=sale.heading,
            price=sale.price,
            before=sale.pre_price,
            discount_percent=round(sale.discount * 100),
            valid_until=sale.valid_until,
        )
        for b in d.buys
        if (sale := b.sale) and sale.discount and sale.pre_price
    ]
    return DinnerOut(
        **_dish(d.dish),
        rank=rank,
        on_sale=d.on_sale,
        fits_as_is=not d.verdict.swaps,
        swaps=[_note(s) for s in d.verdict.swaps],
        discounts=discounts,
        matched=list(matched),
    )


def _clause(c: Clause) -> ClauseOut:
    return ClauseOut(kind=c.kind.value, text=c.text, label=c.label)


def _search(search: Search, total: int, relax: tuple[tuple[Clause, int], ...]) -> SearchOut:
    return SearchOut(
        query=search.text,
        understood=[_clause(c) for c in search.clauses],
        corrected=[CorrectionOut(typed=t, used=u) for t, u in search.corrected],
        total=total,
        without=[_clause(c) for c, _ in relax],
    )


def dinners(queries: Queries, found: Found, base: str | None = None) -> DinnersOut:
    plan = queries.plan(found.household, found.place)
    return DinnersOut(
        considered=plan.considered,
        fitting=plan.fitting,
        on_sale=plan.on_sale,
        place=plan.place,
        offers=plan.offers,
        built=queries.snapshot.built,
        offers_until=queries.offers_until(),
        dinners=[dinner(d, n, found.via.get(d.dish.url, ())) for n, d in enumerate(found.dinners, 1)],
        search=_search(found.search, found.total, found.relax),
        links=links(base, found.search, "middager", queries.snapshot.places) if base else None,
    )


def plan(queries: Queries, week: Plan, search: Search | None = None, base: str | None = None) -> PlanOut:
    return PlanOut(
        considered=week.considered,
        fitting=week.fitting,
        on_sale=week.on_sale,
        place=week.place,
        offers=week.offers,
        stores=list(week.stores),
        built=queries.snapshot.built,
        offers_until=queries.offers_until(),
        dinners=[dinner(d, n) for n, d in enumerate(week.dinners, 1)],
        links=links(base, _rules(search or Search()), "plan", queries.snapshot.places) if base else None,
    )


def check(found: Check) -> CheckOut:
    verdict = found.verdict
    return CheckOut(
        recipe=RecipeOut(**_dish(found.dish)),
        fits=verdict.blocked is None,
        blocked=verdict.blocked,
        swaps=[_note(s) for s in verdict.swaps],
        lactose_g_per_portion=round(verdict.lactose_g, 1),
    )
