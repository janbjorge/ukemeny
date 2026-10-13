"""Read-only queries behind every page, the JSON API and the CLI. They read the snapshot once.

The rules come from the search: «uten løk», «glutenfri» and «lite laktose» are put on top of a base household.
The site's base has no rules (core.search.ANYTHING); the CLI's is profile.yaml. Rankings, indexes and weeks
are worked out once per household and kept: there are only a few, and the snapshot only changes on deploy.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from core import ranking
from core.diet import judge
from core.models import Dinner, Dish, Household, Plan, Snapshot, Verdict
from core.ports import Datasets
from core.ranking import Week
from core.search import ANYTHING, Clause, Counts, Index, Kind, Search, household, via


@dataclass(frozen=True, slots=True)
class Check:
    dish: Dish
    verdict: Verdict


@dataclass(frozen=True, slots=True)
class Found:
    search: Search
    """What the words were understood as."""
    household: Household
    """The rules the dinners were judged by: the base and the search's diet rules."""
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
    def __init__(self, datasets: Datasets, base: Household = ANYTHING, week: Week | None = None) -> None:
        self.snapshot: Snapshot = datasets.snapshot()
        self.base = base
        self.week = week or Week()
        self._ranked: dict[Household, list[Dinner]] = {}
        self._index: dict[Household, Index] = {}
        self._plan: dict[Household, Plan] = {}

    def ranked(self, h: Household | None = None) -> list[Dinner]:
        """Every dinner that fits, best first (core.ranking.dinners)."""
        h = h or self.base
        if h not in self._ranked:
            self._ranked[h] = ranking.dinners(self.snapshot, h)
        return self._ranked[h]

    def index(self, h: Household | None = None) -> Index:
        h = h or self.base
        if h not in self._index:
            self._index[h] = Index(self.ranked(h), self.snapshot.traits)
        return self._index[h]

    def parse(self, text: str) -> Search:
        """The search, with typos fixed against every dinner the base allows."""
        return self.index().parse(text)

    def household(self, text: str = "") -> Household:
        """The base with the rules a search names: «uten løk glutenfri»."""
        return household(self.parse(text).diets, self.base)

    def search(self, text: str = "", limit: int = 30, per_protein: int = 3, skip_week: bool = False) -> Found:
        """Dinners that fit the search's rules and match the rest of it, best first. Without a protein or a word
        to find, the best `per_protein` of each main protein come first. With `skip_week` and nothing but rules
        searched for, the week's dinners are left out (the page shows them above the list)."""
        search = self.parse(text)
        h = household(search.diets, self.base)
        index = self.index(h)
        found = index.find(search)
        if skip_week and all(c.kind is Kind.DIET for c in search.clauses):
            week = {d.dish.url for d in self.plan(h).dinners}
            found = [d for d in found if d.dish.url not in week]
        if not any(c.kind in (Kind.PROTEIN, Kind.WITH) for c in search.clauses):
            found = ranking.varied(found, per_protein)
        shown = tuple(found[:limit])
        return Found(
            search=search,
            household=h,
            dinners=shown,
            total=len(found),
            counts=index.count(search),
            via={d.dish.url: names for d in shown if (names := via(d, search))},
            relax=() if found else tuple(index.relax(search)),
        )

    def plan(self, h: Household | None = None) -> Plan:
        """The week for these rules."""
        h = h or self.base
        if h not in self._plan:
            ranked, offers = self.ranked(h), self.snapshot.offers
            self._plan[h] = Plan(
                dinners=tuple(ranking.plan(ranked, self.week)),
                offers=len(offers),
                stores=tuple(sorted({o.store for o in offers})),
                considered=len(self.snapshot.dishes),
                fitting=len(ranked),
                on_sale=sum(d.on_sale for d in ranked),
            )
        return self._plan[h]

    def check(self, url: str, h: Household | None = None) -> Check | None:
        dish = next((d for d in self.snapshot.dishes if d.url == url), None)
        return Check(dish, judge(dish, self.snapshot.traits, h or self.base)) if dish else None

    def offers_until(self) -> date | None:
        """When most of this week's offers end (the median; a few catalogs run for months)."""
        ends = sorted(o.valid_until for o in self.snapshot.offers)
        return ends[len(ends) // 2] if ends else None

    def stale(self, today: date) -> bool:
        """Most offers have run out: the snapshot needs a rebuild."""
        until = self.offers_until()
        return until is None or until < today
