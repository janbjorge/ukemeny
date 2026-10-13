"""Which dinners fit the household, and in what order. Pure: a snapshot in, ranked dinners out."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.diet import judge
from core.matching import FISH, cheapest_first, main_protein, weight
from core.models import Buy, Dinner, Dish, Household, Offer, Snapshot, Verdict

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


def dinners(snapshot: Snapshot, household: Household) -> list[Dinner]:
    """Every dinner that fits the household, best first (see `rank`)."""
    by_id = {o.id: o for o in snapshot.offers}
    matched = {name: cheapest_first([by_id[i] for i in ids if i in by_id]) for name, ids in snapshot.matches.items()}
    found = []
    for dish in snapshot.dishes:
        verdict = judge(dish, snapshot.traits, household)
        if verdict.blocked is None:
            protein, main = main_protein(dish)
            found.append(Dinner(dish, verdict, buys(dish, verdict, matched), score(dish), protein, main))
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
    first, rest = [], []
    for dinner in ranked:
        seen[dinner.protein] += 1
        (first if seen[dinner.protein] <= per_protein else rest).append(dinner)
    return first + rest
