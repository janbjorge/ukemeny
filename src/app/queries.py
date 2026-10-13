"""Read-only queries behind every page, the JSON API and the CLI. They read the snapshot once."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from core import ranking
from core.diet import judge
from core.models import Dinner, Dish, Household, Plan, Rule, Snapshot, Verdict
from core.ports import Datasets
from core.ranking import Week
from core.search import Clause, Counts, Index, Kind, Search, via


@dataclass(frozen=True, slots=True)
class Check:
    dish: Dish
    verdict: Verdict


@dataclass(frozen=True, slots=True)
class Found:
    search: Search
    """What the words were understood as."""
    dinners: tuple[Dinner, ...]
    """At most the limit asked for, best first."""
    total: int
    """Every dinner that matches."""
    counts: Counts
    via: Mapping[str, tuple[str, ...]]
    """Per dish URL shown, the ingredients that hold a searched word the name does not."""
    relax: tuple[tuple[Clause, int], ...]
    """With nothing found: which clause to drop, and how many dinners that gives."""


class Queries:
    def __init__(self, datasets: Datasets, household: Household, week: Week) -> None:
        self.snapshot: Snapshot = datasets.snapshot()
        self.household = household
        self.week = week
        # The snapshot and household only change on deploy, so the ranking and the index are worked out once
        self.ranked = ranking.dinners(self.snapshot, household)
        self.index = Index(self.ranked, self.snapshot.traits, household)

    def search(self, text: str = "", limit: int = 30, per_protein: int = 3, skip: frozenset[str] = frozenset()) -> Found:
        """Dinners that fit and match a search in plain bokmål (core.search), best first. Without a protein
        or a word to find, the best `per_protein` of each main protein come first. `skip` holds dish URLs
        to leave out when nothing is searched for (the week, shown above the list)."""
        search = self.index.parse(text)
        found = self.index.find(search)
        if not search.clauses:
            found = [d for d in found if d.dish.url not in skip]
        if not any(c.kind in (Kind.PROTEIN, Kind.WITH) for c in search.clauses):
            found = ranking.varied(found, per_protein)
        shown = tuple(found[:limit])
        return Found(
            search=search,
            dinners=shown,
            total=len(found),
            counts=self.index.count(search),
            via={d.dish.url: names for d in shown if (names := via(d, search))},
            relax=() if found else tuple(self.index.relax(search)),
        )

    def plan(self) -> Plan:
        offers = self.snapshot.offers
        return Plan(
            dinners=tuple(ranking.plan(self.ranked, self.week)),
            offers=len(offers),
            stores=tuple(sorted({o.store for o in offers})),
            considered=len(self.snapshot.dishes),
            fitting=len(self.ranked),
            on_sale=sum(d.on_sale for d in self.ranked),
        )

    def check(self, url: str) -> Check | None:
        dish = next((d for d in self.snapshot.dishes if d.url == url), None)
        return Check(dish, judge(dish, self.snapshot.traits, self.household)) if dish else None

    def offers_until(self) -> date | None:
        """When most of this week's offers end (the median; a few catalogs run for months)."""
        ends = sorted(o.valid_until for o in self.snapshot.offers)
        return ends[len(ends) // 2] if ends else None

    def stale(self, today: date) -> bool:
        """Most offers have run out: the snapshot needs a rebuild."""
        until = self.offers_until()
        return until is None or until < today

    def household_lines(self) -> list[str]:
        """The household's rules in plain bokmål, without saying why (the site is public)."""
        h = self.household
        lines = []
        if h.onion is Rule.AVOID:
            lines.append(f"Uten løk ({h.onion_substitute} går fint)" if h.onion_substitute else "Uten løk")
        if h.gluten is Rule.AVOID:
            lines.append("Glutenfritt")
        if h.lactose_g_per_portion is not None:
            lines.append(f"Lite laktose (under {h.lactose_g_per_portion:g} g per porsjon)")
        if h.garlic is Rule.AVOID:
            lines.append("Uten hvitløk")
        if h.kid_notes:
            lines.append("Barnevennlig")
        return lines
