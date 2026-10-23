"""Which dinners fit the household, and in what order. Pure: a snapshot in, ranked dinners out."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from core.diet import carbs, fodmap_out, judge
from core.matching import cheapest_first, main_protein, per_dinner, weight
from core.models import Buy, Dinner, Dish, Household, Item, Level, Offer, Part, Pregnancy, Snapshot, Traits
from core.units import price

TIME_BONUS: Mapping[str, float] = {"Under": 1.0, "20": 0.5, "40": 0.0, "Over": -1.0}
"""By the start of matprat's prep time bucket: small kids do not wait for a slow dinner."""

FLOOR_KR = 20.0
"""A dinner is shown from this many kroner off, every discounted ingredient summed (Dinner.saving; app.queries
`Queries.ranked`). jb 2026-10-22: "no point in showing 100 menues with tuna on sale for 8kr". With the offers of
2026-10-22, 2 262 of 3 392 dinners had any kroner off, 1 467 had 20 or more, 1 180 had 30 or more and 582 had 50 or
more; the median among those on sale was 31 kr. To tune on the cards (METHOD.md §3)."""


def score(dish: Dish) -> float:
    """Rating and prep time, for dinners that fit and are discounted equally well."""
    rating = dish.rating - 4 if dish.rating and dish.rating_count >= 5 else 0.0
    quick = next((v for k, v in TIME_BONUS.items() if dish.prep_time.startswith(k)), 0.0)
    return rating + quick


def rank(dinner: Dinner) -> tuple[float, float]:
    """The most kroner off first (Dinner.saving; jb 2026-10-22: the sort «Rabatt kr» became the order), then rating and
    prep time."""
    return (-dinner.saving, -dinner.score)


@dataclass(frozen=True, slots=True)
class Shelf:
    """The offers a cook can buy as each ingredient, cheapest first (`offered`)."""

    by_name: Mapping[str, tuple[Offer, ...]]
    by_dinner: Mapping[str, Mapping[str, tuple[Offer, ...]]]
    """Per Dish.url, for meat, fish and shellfish (core.matching.per_dinner)."""

    def get(self, dish: Dish, part: Part) -> tuple[Offer, ...]:
        if per_dinner(part):
            return self.by_dinner.get(dish.url, {}).get(part.name, ())
        return self.by_name.get(part.name, ())


def buys(dish: Dish, shelf: Shelf, traits: Mapping[str, Traits]) -> tuple[Buy, ...]:
    """The dish's ingredients that are on offer, most important first, each with its kroner a head on the offer the card
    shows (Buy.sale), through the name's piece weight in `traits` where pieces meet a price by weight (core.units)."""
    seen: set[str] = set()
    found = []
    for part in dish.parts:
        if part.name not in seen and weight(part) and (offers := shelf.get(dish, part)):
            seen.add(part.name)
            buy = Buy(part, offers, weight(part))
            t = traits.get(part.name)
            figure = price(part, buy.sale, t.piece_g if t else None) if buy.sale else None
            found.append(replace(buy, per_person=figure[0], pricing=figure[1]) if figure else buy)
    return tuple(sorted(found, key=lambda b: b.weight, reverse=True))


@dataclass(frozen=True, slots=True)
class Prepared:
    """What does not depend on the household, worked out once per snapshot, so a new set of rules only judges."""

    dish: Dish
    protein: str
    main: str
    score: float
    buys: tuple[Buy, ...]
    """Every ingredient on offer."""
    holds: frozenset[Item]
    """What some judged ingredient holds or may hold, or was never asked about: a rule that leaves one of these out
    leaves the dinner out (core.diet.judge says why)."""
    not_for_pregnant: bool
    high_fodmap: bool
    """An ingredient no other rule judges (core.diet.fodmap_out)."""
    carbs_g: float
    """Per portion, as core.diet.judge counts it."""

    def left_out(self, household: Household) -> bool:
        """Whether a rule leaves the dinner out for sure, without judging it."""
        limit = household.carbs_g_per_portion
        return bool(
            household.avoid & self.holds
            or (household.pregnant and self.not_for_pregnant)
            or (household.fodmap and self.high_fodmap)
            or (limit is not None and self.carbs_g > limit)
        )


def offered(snapshot: Snapshot, place: str | None = None) -> Shelf:
    """The offers a cook can buy as each ingredient: at the stores near `place`, or at every store."""
    near = frozenset(snapshot.places[place]) if place else None
    by_id = {o.id: o for o in snapshot.offers if near is None or o.catalog in near}

    def shelf(matches: Mapping[str, tuple[str, ...]]) -> dict[str, tuple[Offer, ...]]:
        return {name: cheapest_first([by_id[i] for i in ids if i in by_id]) for name, ids in matches.items()}

    return Shelf(shelf(snapshot.matches), {url: shelf(matches) for url, matches in snapshot.served.items()})


def prepare(snapshot: Snapshot) -> tuple[Prepared, ...]:
    """Every dinner with the offers at every store; `nearby` gives one place's."""
    shelf = offered(snapshot)
    prepared = []
    for dish in snapshot.dishes:
        protein, main = main_protein(dish)
        known = [(p, t) for p in dish.parts if (t := snapshot.traits.get(p.name)) is not None]
        prepared.append(
            Prepared(
                dish,
                protein,
                main,
                score(dish),
                buys(dish, shelf, snapshot.traits),
                holds=frozenset(item for item in Item if any(t.contains.get(item, Level.YES) is not Level.NO for _, t in known)),
                not_for_pregnant=any(t.pregnancy is not Pregnancy.OK for _, t in known),
                high_fodmap=any(fodmap_out(t, p.category) for p, t in known),
                carbs_g=sum(carbs(t, p.grams) for p, t in known),
            )
        )
    return tuple(prepared)


def nearby(prepared: Sequence[Prepared], snapshot: Snapshot, place: str | None) -> tuple[Prepared, ...]:
    """The same dinners with the offers at the stores near `place`; None: every store, as `prepare` has them."""
    if place is None:
        return tuple(prepared)
    shelf = offered(snapshot, place)
    return tuple(replace(p, buys=buys(p.dish, shelf, snapshot.traits)) for p in prepared)


def dinners(snapshot: Snapshot, household: Household, prepared: Sequence[Prepared] | None = None) -> list[Dinner]:
    """Every dinner that fits the household, best first (see `rank`). `prepared` (from `prepare`) saves the work that
    does not depend on the household."""
    found = []
    for p in prepared if prepared is not None else prepare(snapshot):
        if p.left_out(household):
            continue
        verdict = judge(p.dish, snapshot.traits, household)
        if verdict.blocked is None:
            found.append(Dinner(p.dish, verdict, p.buys, p.score, p.protein, p.main))
    found.sort(key=rank)
    return found


def varied(ranked: Sequence[Dinner], per_protein: int) -> list[Dinner]:
    """The ranking with the best `per_protein` dinners per main protein first, then the rest (0: as ranked).
    The top of a list has a bit of everything, and nothing is lost further down."""
    if per_protein <= 0:
        return list(ranked)
    seen: Counter[str] = Counter()
    first: list[Dinner] = []
    rest: list[Dinner] = []
    for dinner in ranked:
        seen[dinner.protein] += 1
        (first if seen[dinner.protein] <= per_protein else rest).append(dinner)
    return first + rest
