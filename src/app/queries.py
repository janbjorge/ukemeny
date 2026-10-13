"""Read-only queries behind every page, the JSON API and the CLI. They read the snapshot once.

The rules come from the search: «uten løk», «glutenfri» and «lite laktose» are put on top of a base household.
The site's base has no rules (core.search.ANYTHING); the CLI's is profile.yaml. The offers are from the stores near the
place a search names («i bergen»), else near the base place (the CLI's, from profile.yaml), else from every store. What
does not depend on the rules (core.ranking.prepare, the search Index) is worked out once, and the offers once per place;
rankings, views and weeks once per set of rules and place, and kept: the snapshot only changes on deploy.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from core import ranking
from core.diet import judge
from core.models import Dinner, Dish, Household, Offer, Plan, Snapshot, Verdict
from core.ports import Datasets
from core.ranking import Week
from core.search import ANYTHING, Clause, Counts, Diet, Index, Kind, Search, View, household, via

type Rules = tuple[Household, str | None]
"""What a ranking depends on: the household, and the place whose offers count (None: every store)."""


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
    place: str | None
    """Where the offers are from: the search's place, else the base place. None: every store."""
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
    KEPT = 128
    """Rankings kept, about 0.7 MiB each with 20 places (2026-10-13): with places there are many more sets of rules and
    place than the 256 MB machine holds, so past this many they are all dropped and worked out again as asked."""

    def __init__(self, datasets: Datasets, base: Household = ANYTHING, week: Week | None = None, home: str | None = None) -> None:
        self.snapshot: Snapshot = datasets.snapshot()
        self.base = base
        self.week = week or Week()
        self.home = home
        """The base place, when a search names none; None: every store."""
        self.prepared = ranking.prepare(self.snapshot)
        self.index = Index(self.prepared, self.snapshot.traits, self.snapshot.places)
        self._nearby: dict[str | None, tuple[ranking.Prepared, ...]] = {None: self.prepared}
        self._ranked: dict[Rules, list[Dinner]] = {}
        self._view: dict[Rules, View] = {}
        self._plan: dict[Rules, Plan] = {}

    def nearby(self, place: str | None) -> tuple[ranking.Prepared, ...]:
        """Every dinner with the offers at the stores near `place` (core.ranking.nearby)."""
        if (nearby := self._nearby.get(place)) is None:
            nearby = self._nearby[place] = ranking.nearby(self.prepared, self.snapshot, place)
        return nearby

    def ranked(self, h: Household | None = None, place: str | None = None) -> list[Dinner]:
        """Every dinner that fits, best first (core.ranking.dinners)."""
        key = (h or self.base, place)
        if (ranked := self._ranked.get(key)) is None:
            if len(self._ranked) >= self.KEPT:
                self._ranked.clear()
                self._view.clear()
                self._plan.clear()
            ranked = self._ranked[key] = ranking.dinners(self.snapshot, key[0], self.nearby(place))
        return ranked  # Not self._ranked[key]: warm() in its thread may have dropped it already

    def view(self, h: Household | None = None, place: str | None = None) -> View:
        key = (h or self.base, place)
        if (view := self._view.get(key)) is None:
            view = self._view[key] = self.index.view(self.ranked(*key))
        return view

    def parse(self, text: str) -> Search:
        """The search, with typos fixed against every dinner the base allows."""
        return self.index.parse(text)

    def rules(self, search: Search) -> Rules:
        """The base with the rules a search names («uten løk glutenfri»), and its place or the base place."""
        return household(search.diets, self.base), search.place or self.home

    def household(self, text: str = "") -> Household:
        """The base with the rules a search names: «uten løk glutenfri»."""
        return self.rules(self.parse(text))[0]

    def search(self, text: str = "", limit: int = 30, per_protein: int = 3, skip_week: bool = False) -> Found:
        """Dinners that fit the search's rules and match the rest of it, best first. Without a protein or a word
        to find, the best `per_protein` of each main protein come first. With `skip_week` and nothing but rules
        searched for, the week's dinners are left out (the page shows them above the list)."""
        search = self.parse(text)
        h, place = self.rules(search)
        view = self.view(h, place)
        found = self.index.find(search, view)
        if skip_week and all(c.kind in (Kind.DIET, Kind.ORDER, Kind.PLACE) for c in search.clauses):
            week = {d.dish.url for d in self.plan(h, place).dinners}
            found = [d for d in found if d.dish.url not in week]
        if not any(c.kind in (Kind.PROTEIN, Kind.WITH, Kind.ORDER) for c in search.clauses):
            found = ranking.varied(found, per_protein)
        shown = tuple(found[:limit])
        return Found(
            search=search,
            household=h,
            place=place,
            dinners=shown,
            total=len(found),
            counts=self.index.count(search, view),
            via={d.dish.url: names for d in shown if (names := via(d, search))},
            relax=() if found else tuple(self.index.relax(search, view)),
        )

    def warm(self) -> None:
        """Work out the view and the week for each diet rule on its own, and for each place without rules, ahead of the
        first search that needs it."""
        for diet in Diet:
            h = household([diet], self.base)
            self.view(h, self.home)
            self.plan(h, self.home)
        for place in self.snapshot.places:
            self.view(self.base, place)
            self.plan(self.base, place)

    def offers(self, place: str | None = None) -> list[Offer]:
        """This week's offers at the stores near `place`, or at every store."""
        if place is None:
            return list(self.snapshot.offers)
        near = frozenset(self.snapshot.places[place])
        return [o for o in self.snapshot.offers if o.catalog in near]

    def plan(self, h: Household | None = None, place: str | None = None) -> Plan:
        """The week for these rules and this place."""
        key = (h or self.base, place)
        if (week := self._plan.get(key)) is None:
            ranked, offers = self.ranked(*key), self.offers(place)
            week = self._plan[key] = Plan(
                dinners=tuple(ranking.plan(ranked, self.week)),
                place=place,
                offers=len(offers),
                stores=tuple(sorted({o.store for o in offers})),
                considered=len(self.snapshot.dishes),
                fitting=len(ranked),
                on_sale=sum(d.on_sale for d in ranked),
            )
        return week

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
