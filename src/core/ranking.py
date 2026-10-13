"""Which dinners fit the household, and in what order. Pure: a snapshot in, ranked dinners out."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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
    """Picked from dinners whose main protein is on sale; others only fill in when there are too few."""


def swaps(verdict: Verdict) -> int:
    """How far a dinner is from fitting as is. Ranks before anything else."""
    return len(verdict.swaps)


def score(dish: Dish) -> float:
    """Rating and prep time, for dinners that fit and are discounted equally well."""
    rating = dish.rating - 4 if dish.rating and dish.rating_count >= 5 else 0.0
    quick = next((v for k, v in TIME_BONUS.items() if dish.prep_time.startswith(k)), 0.0)
    return rating + quick


def rank(dinner: Dinner) -> tuple[int, float, float]:
    """Fewest swaps first, then the most discounted, then rating and prep time."""
    return (swaps(dinner.verdict), -dinner.sale, -dinner.score)


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


def prepare(snapshot: Snapshot) -> tuple[Prepared, ...]:
    by_id = {o.id: o for o in snapshot.offers}
    matched = {name: cheapest_first([by_id[i] for i in ids if i in by_id]) for name, ids in snapshot.matches.items()}
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


def plan(ranked: Sequence[Dinner], week: Week) -> list[Dinner]:
    """The week: from dinners on sale when `on_sale_only`, topped up with others if too few."""
    if not week.on_sale_only:
        return pick(ranked, week.days, week.fish)
    chosen = pick([d for d in ranked if d.on_sale], week.days, week.fish)
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
