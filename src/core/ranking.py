"""Which dinners fit the household, and in what order. Pure: a snapshot in, ranked dinners out."""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from core.diet import carbs, fodmap_out, judge
from core.matching import FISH, cheapest_first, main_protein, weight
from core.models import Buy, Dinner, Dish, Household, Item, Level, Offer, Pregnancy, Snapshot, Verdict

TIME_BONUS: Mapping[str, float] = {"Under": 1.0, "20": 0.5, "40": 0.0, "Over": -1.0}
"""By the start of matprat's prep time bucket: small kids do not wait for a slow dinner."""


@dataclass(frozen=True, slots=True)
class Week:
    days: int = 5
    fish: int = 2
    """Fish dinners per week, when enough fit."""
    on_sale_only: bool = True
    """Drawn from dinners whose main protein is on sale (`plan`); others only fill in when there are too few."""


POOL = 5
"""Per main protein, the dinners on sale with the most kroner off that the week is drawn from (fish: this many per fish
dinner in the week, so two fish can differ)."""


def swaps(verdict: Verdict) -> int:
    """How far a dinner is from fitting as is. Ranks before anything else."""
    return len(verdict.swaps)


def score(dish: Dish) -> float:
    """Rating and prep time, for dinners that fit and are discounted equally well."""
    rating = dish.rating - 4 if dish.rating and dish.rating_count >= 5 else 0.0
    quick = next((v for k, v in TIME_BONUS.items() if dish.prep_time.startswith(k)), 0.0)
    return rating + quick


def rank(dinner: Dinner) -> tuple[int, float, float]:
    """Fewest swaps first, then the most kroner off (Dinner.saving; jb 2026-10-22: the sort «Rabatt kr» became the
    order), then rating and prep time."""
    return (swaps(dinner.verdict), -dinner.saving, -dinner.score)


def buys(dish: Dish, verdict: Verdict, matched: Mapping[str, tuple[Offer, ...]]) -> tuple[Buy, ...]:
    """The dish's ingredients that are on offer, used as is (not swapped), most important first."""
    swapped = {s.ingredient for s in verdict.swaps}
    seen: set[str] = set()
    found = []
    for part in dish.parts:
        if matched.get(part.name) and part.name not in swapped and part.name not in seen and weight(part):
            seen.add(part.name)
            found.append(Buy(part, matched[part.name], weight(part)))
    return tuple(sorted(found, key=lambda b: b.weight, reverse=True))


@dataclass(frozen=True, slots=True)
class Prepared:
    """What does not depend on the household, worked out once per snapshot, so a new set of rules only judges."""

    dish: Dish
    protein: str
    main: str
    score: float
    buys: tuple[Buy, ...]
    """Every ingredient on offer, as if nothing were swapped."""
    holds: frozenset[Item]
    """What some judged ingredient holds or may hold, or was never asked about: a rule that leaves one of these out
    leaves the dinner out (core.diet.judge says why)."""
    not_for_pregnant: bool
    high_fodmap: bool
    """An ingredient no swap takes care of (core.diet.fodmap_out)."""
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


def offered(snapshot: Snapshot, place: str | None = None) -> dict[str, tuple[Offer, ...]]:
    """Per ingredient name, the offers a cook can buy as it, cheapest first: at the stores near `place`, or at every
    store."""
    near = frozenset(snapshot.places[place]) if place else None
    by_id = {o.id: o for o in snapshot.offers if near is None or o.catalog in near}
    return {name: cheapest_first([by_id[i] for i in ids if i in by_id]) for name, ids in snapshot.matches.items()}


def prepare(snapshot: Snapshot) -> tuple[Prepared, ...]:
    """Every dinner with the offers at every store; `nearby` gives one place's."""
    matched = offered(snapshot)
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
                buys(dish, NO_SWAPS, matched),
                holds=frozenset(item for item in Item if any(t.contains.get(item, Level.YES) is not Level.NO for _, t in known)),
                not_for_pregnant=any(t.pregnancy is not Pregnancy.OK for _, t in known),
                high_fodmap=any(fodmap_out(t, p.category) for p, t in known),
                carbs_g=sum(carbs(t, p.grams) for p, t in known),
            )
        )
    return tuple(prepared)


NO_SWAPS = Verdict(blocked=None, swaps=(), warnings=(), lactose_g=0.0)


def nearby(prepared: Sequence[Prepared], snapshot: Snapshot, place: str | None) -> tuple[Prepared, ...]:
    """The same dinners with the offers at the stores near `place`; None: every store, as `prepare` has them."""
    if place is None:
        return tuple(prepared)
    matched = offered(snapshot, place)
    return tuple(replace(p, buys=buys(p.dish, NO_SWAPS, matched)) for p in prepared)


def dinners(snapshot: Snapshot, household: Household, prepared: Sequence[Prepared] | None = None) -> list[Dinner]:
    """Every dinner that fits the household, best first (see `rank`). `prepared` (from `prepare`) saves the work that
    does not depend on the household."""
    found = []
    for p in prepared if prepared is not None else prepare(snapshot):
        if p.left_out(household):
            continue
        verdict = judge(p.dish, snapshot.traits, household)
        if verdict.blocked is None:
            swapped = {s.ingredient for s in verdict.swaps}
            kept = tuple(b for b in p.buys if b.part.name not in swapped) if swapped else p.buys
            found.append(Dinner(p.dish, verdict, kept, p.score, p.protein, p.main))
    found.sort(key=rank)
    return found


def pick(ranked: Sequence[Dinner], days: int, fish: int) -> list[Dinner]:
    """A varied week, best first: one dinner per main protein, except fish, which may come
    up to `fish` times but never the same fish twice. Fish dinners are picked first."""
    chosen: list[Dinner] = []

    def fits(dinner: Dinner) -> bool:
        same = sum(c.protein == dinner.protein for c in chosen)
        if dinner in chosen or (dinner.main and dinner.main in {c.main for c in chosen}):
            return False
        return same == 0 or (dinner.protein == FISH and same < fish)

    for dinner in (d for d in ranked if d.protein == FISH):
        if len(chosen) >= min(fish, days):
            break
        if fits(dinner):
            chosen.append(dinner)
    for dinner in ranked:
        if len(chosen) >= days:
            break
        if fits(dinner):
            chosen.append(dinner)
    for dinner in ranked:  # Too few proteins for a fully varied week.
        if len(chosen) >= days:
            break
        if dinner not in chosen:
            chosen.append(dinner)
    return chosen


def kroner(dinner: Dinner) -> float:
    """Kroner off every discounted ingredient (Dinner.saving); 0 without one."""
    return dinner.saving


def plan(ranked: Sequence[Dinner], week: Week, chance: Callable[[], float]) -> list[Dinner]:
    """The week, drawn from the dinners on sale, the more kroner off the likelier (jb 2026-10-14: "I want a Ukens
    middager that consist of the lowest prices, in rabatt kr, if we can make this semi random"): by the square of the
    kroner off, so a small saving rarely wins a day (METHOD.md §5). Per main protein the
    POOL with the most kroner off, fewest swaps first, are in the draw, and `pick` keeps the week varied. Topped up from
    the ranking when too few are on sale; without `on_sale_only`, the ranking alone. `chance` gives a random number
    from 0 to 1 (random.Random.random), so the caller decides how often the week changes."""
    if not week.on_sale_only:
        return pick(ranked, week.days, week.fish)
    pools: dict[str, list[Dinner]] = {}
    for d in sorted((d for d in ranked if d.on_sale and kroner(d) > 0), key=lambda d: (swaps(d.verdict), -kroner(d))):
        pools.setdefault(d.protein, []).append(d)
    drawn = [d for protein, pool in pools.items() for d in pool[: POOL * max(week.fish, 1) if protein == FISH else POOL]]
    # A weighted draw (Efraimidis and Spirakis): each dinner's place is a random number to the power 1 / weight
    drawn.sort(key=lambda d: chance() ** (1 / kroner(d) ** 2), reverse=True)
    chosen = pick(drawn, week.days, week.fish)
    have_fish = sum(d.protein == FISH for d in chosen)
    rest = [d for d in ranked if not d.on_sale]
    return chosen + pick(rest, week.days - len(chosen), max(week.fish - have_fish, 0))


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
