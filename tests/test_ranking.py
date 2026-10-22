import random
from collections import Counter

from adapters.datasets import JsonDatasets
from core.diet import judge
from core.models import Gluten, Household, Onion
from core.ranking import POOL, Week, dinners, pick, plan, prepare, varied
from core.search import Diet, household
from tests.fakes import ingredient, offer, recipe, snapshot, traits

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
SALMON = ingredient("laksefilet", 600, "g", "/fisk og sjømat")
COD = ingredient("torskefilet", 600, "g", "/fisk og sjømat")
ONION = ingredient("løk", 1, "stk.", "/grønnsaker")
PASTA = ingredient("spaghetti", 400, "g", "/pasta/ris")
BROCCOLI = ingredient("brokkoli", 300, "g", "/grønnsaker")
HAM = ingredient("spekeskinke", 100, "g", "/kjøtt/spekemat")
PORK = ingredient("svinestek", 800, "g", "/kjøtt/svinekjøtt")
HOUSEHOLD = Household()
SALE = offer("KYLLINGBRYST", 99, pre_price=135, id="sale")


def test_blocked_recipes_are_left_out() -> None:
    s = snapshot(recipe("Biff med løk", ONION), recipe("Kyllinggryte", CHICKEN), known={"løk": traits(onion=Onion.ONION)})
    assert [d.dish.name for d in dinners(s, HOUSEHOLD)] == ["Kyllinggryte"]


def test_discounted_dinner_ranks_first() -> None:
    s = snapshot(
        recipe("Laks", SALMON, rating=5.0, rating_count=50),
        recipe("Kylling", CHICKEN),
        offers=[SALE, offer("LAKSEFILET", 120, id="no sale")],
        matches={"kyllingfilet": ["sale"], "laksefilet": ["no sale"]},
    )
    found = dinners(s, HOUSEHOLD)
    assert [d.dish.name for d in found] == ["Kylling", "Laks"]
    assert found[0].on_sale and found[0].protein == "kylling" and found[0].main == "kyllingfilet"
    assert not found[1].on_sale  # On offer, but no before-price


def test_a_dinner_that_would_need_a_swap_is_left_out() -> None:
    s = snapshot(
        recipe("Pasta", PASTA, CHICKEN),
        recipe("Laks", SALMON),
        known={"spaghetti": traits(gluten=Gluten.YES)},
        offers=[offer("SPAGHETTI", 20, pre_price=30, id="pasta"), SALE],
        matches={"spaghetti": ["pasta"], "kyllingfilet": ["sale"]},
    )
    assert [d.dish.name for d in dinners(s, HOUSEHOLD)] == ["Laks"]  # no «glutenfri spaghetti» (jb 2026-10-22)


def test_a_discount_on_the_side_does_not_put_a_dinner_on_sale() -> None:
    lutefisk = ingredient("lutefisk", 1200, "g", "/fisk og sjømat")
    bacon = ingredient("bacon", 150, "g", "/kjøtt/svinekjøtt")
    s = snapshot(recipe("Lutefisk", lutefisk, bacon), offers=[offer("Stjernebacon", 20, pre_price=39.9, id="b")], matches={"bacon": ["b"]})
    (dinner,) = dinners(s, HOUSEHOLD)
    assert dinner.main == "lutefisk" and dinner.sale > 0 and not dinner.on_sale


def test_offers_missing_from_the_snapshot_are_ignored() -> None:
    s = snapshot(recipe("Kylling", CHICKEN), matches={"kyllingfilet": ["gone"]})
    (dinner,) = dinners(s, HOUSEHOLD)
    assert dinner.buys == ()


def test_week_is_varied_and_never_the_same_fish_twice() -> None:
    s = snapshot(
        recipe("Kylling 1", CHICKEN, rating=5.0, rating_count=10),
        recipe("Kylling 2", CHICKEN, rating=5.0, rating_count=10),
        recipe("Laks 1", SALMON),
        recipe("Laks 2", SALMON),
        recipe("Torsk", COD),
        recipe("Grønnsaksgryte", BROCCOLI),
    )
    names = [d.dish.name for d in plan(dinners(s, HOUSEHOLD), Week(days=4, fish=2, on_sale_only=False), random.Random(0).random)]
    assert len(names) == 4
    assert sum(n.startswith("Laks") for n in names) == 1
    assert "Torsk" in names
    assert sum(n.startswith("Kylling") for n in names) == 1


def test_week_goes_by_the_meat_in_the_recipe_not_matprats_label() -> None:
    s = snapshot(recipe("Kylling med spekeskinke", CHICKEN, HAM, main="Svin"), recipe("Kyllinggryte", CHICKEN), recipe("Svinestek", PORK))
    names = {d.dish.name for d in pick(dinners(s, HOUSEHOLD), days=2, fish=0)}
    assert "Svinestek" in names and len(names) == 2


def test_week_picks_dinners_on_sale_and_fills_in() -> None:
    s = snapshot(
        recipe("Kylling", CHICKEN, rating=3.0, rating_count=10),
        recipe("Biff", PORK, rating=5.0, rating_count=10),
        recipe("Lam", BROCCOLI, rating=5.0, rating_count=10),
        offers=[SALE],
        matches={"kyllingfilet": ["sale"]},
    )
    week = plan(dinners(s, HOUSEHOLD), Week(days=2, fish=0), random.Random(0).random)
    assert week[0].dish.name == "Kylling" and len(week) == 2


def test_week_is_drawn_from_the_most_kroner_off_the_more_the_likelier() -> None:
    """jb 2026-10-14: "I want a Ukens middager that consist of the lowest prices, in rabatt kr, if we can make this semi
    random"."""
    off = [10, 20, 30, 40, 50, 60, 70]  # kroner off, one chicken dinner each
    parts = [ingredient(f"kylling {kr}", 600, "g", "/kjøtt/kylling/høns") for kr in off]
    s = snapshot(
        *(recipe(f"Kylling {kr}", part) for kr, part in zip(off, parts, strict=True)),
        offers=[offer(f"KYLLING {kr}", 100, pre_price=100 + kr, id=str(kr)) for kr in off],
        matches={f"kylling {kr}": [str(kr)] for kr in off},
    )
    ranked, week = dinners(s, HOUSEHOLD), Week(days=1, fish=0)
    drawn = Counter(plan(ranked, week, random.Random(n).random)[0].dish.name for n in range(400))
    assert set(drawn) == {f"Kylling {kr}" for kr in off[-POOL:]}  # the 10 and 20 kr off are not in the draw
    assert drawn["Kylling 70"] > drawn["Kylling 50"] > drawn["Kylling 30"]  # the more off, the likelier
    assert plan(ranked, week, random.Random(7).random) == plan(ranked, week, random.Random(7).random)  # the same seed, the same week


def test_pick_repeats_proteins_only_when_it_must() -> None:
    s = snapshot(recipe("Kylling 1", CHICKEN), recipe("Kylling 2", CHICKEN))
    assert len(pick(dinners(s, HOUSEHOLD), days=2, fish=2)) == 2


def test_varied_puts_a_few_of_each_protein_first() -> None:
    s = snapshot(
        recipe("Kylling 1", CHICKEN, rating=5.0, rating_count=10),
        recipe("Kylling 2", CHICKEN, rating=4.9, rating_count=10),
        recipe("Kylling 3", CHICKEN, rating=4.8, rating_count=10),
        recipe("Svinestek", PORK),
    )
    ranked = dinners(s, HOUSEHOLD)
    assert [d.dish.name for d in varied(ranked, 2)] == ["Kylling 1", "Kylling 2", "Svinestek", "Kylling 3"]
    assert varied(ranked, 0) == ranked


def test_the_shortcut_agrees_with_judge_for_every_rule() -> None:
    s = JsonDatasets().snapshot()
    prepared = prepare(s)
    for diet in Diet:
        h = household([diet])
        fast = {d.dish.url for d in dinners(s, h, prepared)}
        slow = {dish.url for dish in s.dishes if judge(dish, s.traits, h).blocked is None}
        assert fast == slow, diet
