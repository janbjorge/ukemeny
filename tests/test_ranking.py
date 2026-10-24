from dataclasses import replace

from adapters.datasets import JsonDatasets
from core.diet import judge
from core.models import Gluten, Household, Onion
from core.ranking import dinners, prepare, varied
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
    assert dinner.main == "lutefisk" and dinner.saving > 0 and not dinner.on_sale


def test_offers_missing_from_the_snapshot_are_ignored() -> None:
    s = snapshot(recipe("Kylling", CHICKEN), matches={"kyllingfilet": ["gone"]})
    (dinner,) = dinners(s, HOUSEHOLD)
    assert dinner.buys == ()


def test_meat_and_fish_offers_count_per_dinner() -> None:
    raw = recipe("Nigiri", ingredient("tunfisk", 400, "g", "/fisk og sjømat"))
    salad = recipe("Tunfisksalat", ingredient("tunfisk", 2, "boks", "/fisk og sjømat"))
    s = replace(
        snapshot(raw, salad, offers=[offer("Tunfisk", 15, pre_price=23.9, id="tin")]),
        served={salad.url: {"tunfisk": ("tin",)}},
        matches={"tunfisk": ("tin",)},  # By name, meat and fish are never looked up
    )
    found = {d.dish.name: [b.best.id for b in d.buys] for d in dinners(s, HOUSEHOLD)}
    assert found == {"Nigiri": [], "Tunfisksalat": ["tin"]}


def test_the_saving_counts_the_most_kroner_off_exact_before_near() -> None:
    mince = ingredient("kjøttdeig av svin", 400, "g", "/kjøtt/svinekjøtt")
    pork = recipe("Svinekjøttboller", mince)
    offers = [
        offer("SVINEKJØTTDEIG", 40, pre_price=60, id="rema", store="REMA 1000"),
        offer("SVINEKJØTTDEIG", 30, pre_price=40, id="kiwi", store="KIWI"),
        offer("SVINEKJØTTDEIG", 30, pre_price=40, id="kiwi nord", store="KIWI", catalog="kiwi-nord"),
        offer("Kjøttdeig av storfe&svin", 50, pre_price=74.9, id="mix", store="MENY"),
    ]
    exact = replace(
        snapshot(pork, offers=offers),
        served={pork.url: {mince.name: ("rema", "kiwi", "kiwi nord")}},
        near_served={pork.url: {mince.name: ("mix",)}},
    )
    (dinner,) = dinners(exact, HOUSEHOLD)
    assert dinner.saving == 20  # REMA's 20 kr: the most off among the exact ones, before MENY's mix
    assert [o.id for o in dinner.buys[0].sales] == ["mix", "rema", "kiwi"]  # Most kroner off first; KIWI's two catalogs once
    near_only = replace(exact, served={})
    (dinner,) = dinners(near_only, HOUSEHOLD)
    assert dinner.buys[0].sale is not None and dinner.buys[0].sale.id == "mix" and dinner.on_sale


def test_the_main_protein_is_the_meat_in_the_recipe_not_matprats_label() -> None:
    s = snapshot(recipe("Kylling med spekeskinke", CHICKEN, HAM, main="Svin"), recipe("Svinestek", PORK))
    assert [d.protein for d in dinners(s, HOUSEHOLD)] == ["kylling", "svin"]


def test_the_most_kroner_off_comes_first() -> None:
    off = [10, 70, 40]  # kroner off, one chicken dinner each
    parts = [ingredient(f"kylling {kr}", 600, "g", "/kjøtt/kylling/høns") for kr in off]
    s = snapshot(
        *(recipe(f"Kylling {kr}", part) for kr, part in zip(off, parts, strict=True)),
        offers=[offer(f"KYLLING {kr}", 100, pre_price=100 + kr, id=str(kr)) for kr in off],
        matches={f"kylling {kr}": [str(kr)] for kr in off},
    )
    assert [d.dish.name for d in dinners(s, HOUSEHOLD)] == ["Kylling 70", "Kylling 40", "Kylling 10"]


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
