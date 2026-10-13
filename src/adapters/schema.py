"""The JSON shape of dinners, plans and recipe checks, shared by the API (/api) and `matris --json`.

No ingredient lists: the recipes belong to matprat.no, and every dinner links there.

pydantic v2 models, so the OpenAPI schema documents every field. Keys are English, for agents;
the text inside (advice) is bokmål, like the site. No label or kid notes either: they named ingredient after
ingredient, so they stay in the CLI's text output, on this machine.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.queries import Check, Found, Queries
from core.matching import main_protein
from core.models import Dinner, Dish, Note, Plan
from core.search import Clause, Search


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
    """tag (a category), protein (the main protein is one of these), not_protein, with (a word in the
    name or an ingredient) or without."""
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


class SnapshotOut(Out):
    considered: int
    fitting: int
    on_sale: int
    offers: int
    built: datetime
    """When the snapshot was built; offers are from that week."""
    offers_until: date | None
    dinners: list[DinnerOut]


class DinnersOut(SnapshotOut):
    search: SearchOut


class PlanOut(SnapshotOut):
    stores: list[str]


def _note(note: Note) -> NoteOut:
    return NoteOut(ingredient=note.ingredient, problem=note.problem.value, advice=note.advice)


def _dish(dish: Dish) -> dict[str, Any]:
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


def dinners(queries: Queries, found: Found) -> DinnersOut:
    plan = queries.plan(found.household)
    return DinnersOut(
        considered=plan.considered,
        fitting=plan.fitting,
        on_sale=plan.on_sale,
        offers=plan.offers,
        built=queries.snapshot.built,
        offers_until=queries.offers_until(),
        dinners=[dinner(d, n, found.via.get(d.dish.url, ())) for n, d in enumerate(found.dinners, 1)],
        search=_search(found.search, found.total, found.relax),
    )


def plan(queries: Queries, week: Plan) -> PlanOut:
    return PlanOut(
        considered=week.considered,
        fitting=week.fitting,
        on_sale=week.on_sale,
        offers=week.offers,
        stores=list(week.stores),
        built=queries.snapshot.built,
        offers_until=queries.offers_until(),
        dinners=[dinner(d, n) for n, d in enumerate(week.dinners, 1)],
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
