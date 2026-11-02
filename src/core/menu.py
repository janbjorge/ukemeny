"""A week's menu: dinners picked together so the shopping takes few chains and costs little. Pure: ranked dinners in, a
menu out (METHOD.md §8).

The catalogs only price what is on sale, so a menu's price is that of the ingredients some store near the place has on
sale: per ingredient, the cheapest pack at the chains picked, or, when none of them has it on sale, its usual price, the
median before-price of every offer for it near the place. Each dinner's main ingredient (Dinner.on_sale) must be on sale
at the chains picked, so the dearest part of it is known, and the packs bought there must save core.ranking.FLOOR_KR.
Every set of up to MAX_STORES chains is tried; per set, the
cheapest dinners, a few per main protein, make the menu, and each chain past the first costs the weight's STORE_COST.
"""

import heapq
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import combinations
from statistics import median

from core.models import MAIN_WEIGHT, Buy, Dinner, Offer
from core.ranking import FLOOR_KR

SIZE = 7
"""Dinners in a menu: a week (jb 2026-11-02: "i think a full week? I there any point in giving options? They can ignore
what they dont want")."""

MAX_STORES = 3
"""Chains a menu may send the cook to."""

PER_PROTEIN = 2
"""Dinners per main protein in a menu, so a week is not five kjøttdeig dinners."""

NOISES = (1.0, 0.5, 0.25, 0.1)
"""With a seed, each dinner's price is scaled by its own draw between 1 and 1 + noise, so menus vary (jb 2026-11-02: "i
want some kind of semi randomness here"). The strongest noise whose menu is within TOLERANCE of the best is used: 0.2
alone never got past a 20 kr karbonade, so «Ny meny» swapped dinners and kept the price."""

TOLERANCE = 0.05
"""A drawn menu may cost this much more than the best for its weight, chain cost included (jb 2026-11-02: "we need to
make sure that we are within %5 of the lewst optoion or so"), at no more chains; past it, the best menu is shown."""


class Weight(StrEnum):
    """What a menu gives up for what."""

    CHEAPEST = "cheapest"
    """The lowest price, at up to MAX_STORES chains."""
    BALANCED = "balanced"
    """A chain more only when it makes the menu STORE_COST cheaper."""
    ONE_STORE = "one-store"
    """Everything from one chain."""


STORE_COST: Mapping[Weight, float] = {Weight.CHEAPEST: 0.0, Weight.BALANCED: 80.0, Weight.ONE_STORE: 0.0}
"""Kroner a chain past the first must save. 80 for «Balansert» is a guess to tune on real menus, as FLOOR_KR was."""


@dataclass(frozen=True, slots=True)
class Course:
    """A dinner in a menu, and what its ingredients with a known price cost at the menu's chains."""

    dinner: Dinner
    """With only the offers at the menu's chains: its `deals` are the packs bought, each its `sale`."""
    price: float
    """The packs on sale bought, plus `usual`."""
    saving: float
    """The catalogs' kroner off the packs bought (Dinner.saving)."""
    usual: tuple[tuple[str, float], ...]
    """Ingredients on sale near the place but not at the menu's chains, with the usual price paid for them."""


@dataclass(frozen=True, slots=True)
class Menu:
    courses: tuple[Course, ...]
    stores: tuple[str, ...]
    """The chains to shop at, by name."""

    @property
    def usual(self) -> float:
        """What the ingredients not on sale at `stores` cost at their usual price."""
        return sum(kr for c in self.courses for _, kr in c.usual)

    @property
    def dinners(self) -> tuple[Dinner, ...]:
        return tuple(c.dinner for c in self.courses)

    @property
    def price(self) -> float:
        """What every ingredient with a known price costs; the cards' prices summed."""
        return sum(c.price for c in self.courses)

    @property
    def saving(self) -> float:
        """The catalogs' kroner off; the cards' savings summed."""
        return sum(c.saving for c in self.courses)


@dataclass(frozen=True, slots=True)
class _Ingredient:
    name: str
    main: bool
    """The dinner's main ingredient (Dinner.on_sale)."""
    usual: float
    exact: Mapping[str, Offer]
    """Per chain, its cheapest exact offer on sale."""
    near: Mapping[str, Offer]
    """Per chain, its cheapest near offer on sale."""

    def pick(self, stores: frozenset[str]) -> Offer | None:
        """The pack to buy at `stores`: as Buy.sale picks it among their offers."""
        for kind in (self.exact, self.near):
            if found := [o for store, o in kind.items() if store in stores]:
                return min(found, key=_cheapest)
        return None


def _cheapest(o: Offer) -> tuple[float, float, str]:
    """The order Buy.sale picks in."""
    return o.price, -(o.saving or 0.0), o.store


def _ingredient(dinner: Dinner, buy: Buy) -> _Ingredient:
    def best(offers: Sequence[Offer]) -> dict[str, Offer]:
        found: dict[str, Offer] = {}
        for o in offers:
            if o.saving and (o.store not in found or _cheapest(o) < _cheapest(found[o.store])):
                found[o.store] = o
        return found

    usual = median(o.pre_price for o in buy.sales if o.pre_price)
    main = buy.part.name == dinner.main if dinner.main else buy.weight >= MAIN_WEIGHT
    return _Ingredient(buy.part.name, main, usual, best(buy.offers), best(buy.near))


@dataclass(frozen=True, slots=True)
class _Priced:
    """A dinner at a set of chains."""

    price: float
    saving: float
    picks: tuple[Offer, ...]
    usual: tuple[tuple[str, float], ...]


def _priced(ingredients: Sequence[_Ingredient], stores: frozenset[str]) -> _Priced | None:
    """Per ingredient, the pack on sale at `stores`, or its usual price; an offer two ingredients share is bought once.
    None when the main ingredient is not on sale there, or the packs save less than FLOOR_KR (jb 2026-11-02: "right now
    we get meny options that are 5 nok saving on a recepie, no-one really cares")."""
    picks: dict[str, Offer] = {}
    usual: list[tuple[str, float]] = []
    main = False
    for i in ingredients:
        if (o := i.pick(stores)) is None:
            usual.append((i.name, i.usual))
            continue
        main = main or i.main
        picks.setdefault(o.id, o)
    saving = sum(o.saving or 0.0 for o in picks.values())
    if not main or saving < FLOOR_KR:
        return None
    price = sum(o.price for o in picks.values()) + sum(kr for _, kr in usual)
    return _Priced(price, saving, tuple(picks.values()), tuple(usual))


def _draw(seed: int, dinner: Dinner) -> float:
    """The dinner's own draw for this seed, 0 to 1: the same whatever else the search finds."""
    return random.Random(f"{seed}:{dinner.dish.url}").random()


@dataclass(frozen=True, slots=True)
class _Row:
    dinner: Dinner
    ingredients: tuple[_Ingredient, ...]
    main: frozenset[str]
    """The chains with its main ingredient on sale."""
    reach: frozenset[str]
    """The chains with any of its ingredients on sale."""
    floor: float
    """The least it can cost at any chains: each ingredient at its cheapest offer or its usual price."""


@dataclass(frozen=True, slots=True)
class _Pick:
    taken: tuple[tuple[Dinner, _Priced], ...]
    stores: tuple[str, ...]
    cost: float
    """The price, and the weight's cost for each chain past the first."""


def plan(dinners: Sequence[Dinner], weight: Weight = Weight.BALANCED, seed: int | None = None) -> Menu | None:
    """The cheapest menu of up to SIZE `dinners` for `weight`, a full menu before a shorter one; `seed` gives another
    within TOLERANCE of it (jb 2026-11-02: "lavest pris lacks the new meny"). None when no dinner's main ingredient is on sale."""
    rows = []
    for d in dinners:
        ingredients = tuple(_ingredient(d, b) for b in d.buys if b.sales)
        main = frozenset(s for i in ingredients if i.main for s in (*i.exact, *i.near))
        reach = frozenset(s for i in ingredients for s in (*i.exact, *i.near))
        floor = 0.0
        shared: set[str] = set()
        for i in ingredients:
            offers = [*i.exact.values(), *i.near.values()]
            # A pack two ingredients share is bought once (_priced), so the second may cost nothing
            floor += 0.0 if shared & {o.id for o in offers} else min([i.usual, *(o.price for o in offers)])
            shared |= {o.id for o in offers}
        rows.append(_Row(d, ingredients, main, reach, floor))
    chains = sorted(frozenset().union(*(r.main for r in rows)))
    most = 1 if weight is Weight.ONE_STORE else MAX_STORES
    chain_cost = STORE_COST[weight]
    # Per dinner, its price by the chains of a set that have its offers: most dinners are on sale at one or two chains,
    # so most sets ask again for what an earlier set worked out
    known: list[dict[frozenset[str], _Priced | None]] = [{} for _ in rows]

    def search(factors: Sequence[float]) -> _Pick | None:
        """Every set of chains, each with its cheapest dinners by price times `factors`; the best set by the same.
        Dinners are priced in the order of their least possible price, and only until the cheapest SIZE are sure: a
        dinner is taken once no dinner left could be cheaper."""
        order = sorted(range(len(rows)), key=lambda n: rows[n].floor * factors[n])
        best: tuple[int, float, int] | None = None
        found: _Pick | None = None
        for k in range(1, most + 1):
            for chosen in combinations(chains, k):
                picked = frozenset(chosen)
                waiting: list[tuple[float, int, _Priced]] = []  # n is unique, so _Priced is never compared
                taken: list[tuple[Dinner, _Priced]] = []
                drawn = 0.0
                per: Counter[str] = Counter()
                i = 0
                while len(taken) < SIZE:
                    while i < len(order) and (not waiting or rows[order[i]].floor * factors[order[i]] <= waiting[0][0]):
                        n, i = order[i], i + 1
                        row = rows[n]
                        if not picked & row.main:
                            continue
                        here = picked & row.reach
                        if here not in known[n]:
                            known[n][here] = _priced(row.ingredients, here)
                        if (p := known[n][here]) is not None:
                            heapq.heappush(waiting, (p.price * factors[n], n, p))
                    if not waiting:
                        break
                    price, n, p = heapq.heappop(waiting)
                    d = rows[n].dinner
                    if per[d.protein] < PER_PROTEIN:
                        per[d.protein] += 1
                        drawn += price
                        taken.append((d, p))
                used = tuple(sorted({o.store for _, p in taken for o in p.picks}))
                extra = chain_cost * max(len(used) - 1, 0)
                key = (len(taken), -(drawn + extra), -len(used))
                if taken and (best is None or key > best):
                    best = key
                    found = _Pick(tuple(taken), used, sum(p.price for _, p in taken) + extra)
        return found

    if (pick := search([1.0] * len(rows))) is None:
        return None
    if seed is not None:
        draws = [_draw(seed, r.dinner) for r in rows]
        for noise in NOISES:
            other = search([1.0 + noise * x for x in draws])
            if (
                other
                and len(other.taken) == len(pick.taken)
                and len(other.stores) <= len(pick.stores)
                and other.cost <= pick.cost * (1 + TOLERANCE)
            ):
                pick = other
                break
    stores = frozenset(pick.stores)
    return Menu(tuple(Course(_at(d, stores), p.price, p.saving, p.usual) for d, p in pick.taken), pick.stores)


def _at(dinner: Dinner, stores: frozenset[str]) -> Dinner:
    """The dinner with only the offers at `stores`."""
    buys = []
    for b in dinner.buys:
        kept = replace(b, offers=tuple(o for o in b.offers if o.store in stores), near=tuple(o for o in b.near if o.store in stores))
        if kept.offers or kept.near:
            buys.append(kept)
    return replace(dinner, buys=tuple(buys))
