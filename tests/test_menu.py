"""A week's menu: few chains, a low price (core.menu)."""

import random

from core.menu import PER_PROTEIN, TOLERANCE, Weight, plan
from core.models import Dinner, Household, Offer, Recipe
from core.ranking import dinners
from tests.fakes import SIDE, ingredient, offer, recipe, snapshot

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
SALMON = ingredient("laksefilet", 600, "g", "/fisk og sjømat")


def ranked(*recipes: Recipe, offers: list[Offer], matches: dict[str, list[str]]) -> list[Dinner]:
    return dinners(snapshot(*recipes, offers=offers, matches=matches), Household())


def test_the_cheapest_pack_wins_over_the_biggest_discount() -> None:
    found = ranked(
        recipe("Kyllinggryte", CHICKEN),
        offers=[
            offer("KYLLINGFILET", 40, pre_price=70, id="kiwi", store="KIWI"),
            offer("KYLLINGFILET", 30, pre_price=45, id="rema", store="REMA 1000"),
        ],
        matches={"kyllingfilet": ["kiwi", "rema"]},
    )
    menu = plan(found, Weight.CHEAPEST)
    assert menu is not None and menu.stores == ("REMA 1000",)
    assert menu.price == 30 and menu.saving == 15  # REMA's 30 kr pack, 15 kr off, over KIWI's 40 kr, 30 kr off
    assert [o.store for b in menu.dinners[0].buys for o in b.sales] == ["REMA 1000"]  # the card: only where to shop


def sale_at_two_chains(salmon_pre_price: float) -> list[Dinner]:
    return ranked(
        recipe("Kyllinggryte", CHICKEN),
        recipe("Laks i ovn", SALMON),
        offers=[
            offer("KYLLINGFILET", 100, pre_price=300, id="kiwi", store="KIWI"),
            offer("LAKSEFILET", 50, pre_price=salmon_pre_price, id="rema", store="REMA 1000"),
        ],
        matches={"kyllingfilet": ["kiwi"], "laksefilet": ["rema"]},
    )


def test_one_store_keeps_to_one_chain() -> None:
    found = sale_at_two_chains(100)
    one = plan(found, Weight.ONE_STORE)
    assert one is not None and one.stores == ("REMA 1000",) and [d.dish.name for d in one.dinners] == ["Laks i ovn"]
    cheapest = plan(found, Weight.CHEAPEST)  # a full menu before a shorter one
    assert cheapest is not None and cheapest.stores == ("KIWI", "REMA 1000") and len(cheapest.dinners) == 2


def on_sale_at_both(dearer: float) -> list[Dinner]:
    """Chicken is cheapest at KIWI and salmon at REMA, each `dearer` kroner more at the other."""
    return ranked(
        recipe("Kyllinggryte", CHICKEN),
        recipe("Laks i ovn", SALMON),
        offers=[
            offer("KYLLINGFILET", 100, pre_price=400, id="k-kiwi", store="KIWI"),
            offer("KYLLINGFILET", 100 + dearer, pre_price=400, id="k-rema", store="REMA 1000"),
            offer("LAKSEFILET", 50, pre_price=400, id="l-rema", store="REMA 1000"),
            offer("LAKSEFILET", 50 + dearer, pre_price=400, id="l-kiwi", store="KIWI"),
        ],
        matches={"kyllingfilet": ["k-kiwi", "k-rema"], "laksefilet": ["l-kiwi", "l-rema"]},
    )


def test_balanced_takes_a_second_chain_only_when_it_pays() -> None:
    small = plan(on_sale_at_both(50), Weight.BALANCED)  # a second chain saves 50 kr: less than it costs
    assert small is not None and len(small.stores) == 1 and small.price == 200
    big = plan(on_sale_at_both(150), Weight.BALANCED)  # it saves 150 kr
    assert big is not None and big.stores == ("KIWI", "REMA 1000") and big.price == 150


def test_the_cheapest_is_never_dearer_than_the_others() -> None:
    """Without a seed: with one, «Lavest pris» may be TOLERANCE over its best too (test_a_seed_stays_near_the_best)."""
    for found in (on_sale_at_both(50), on_sale_at_both(150), sale_at_two_chains(100)):
        cheapest = plan(found, Weight.CHEAPEST)
        assert cheapest is not None
        for weight in (Weight.BALANCED, Weight.ONE_STORE):
            other = plan(found, weight, seed=3)
            assert other is not None
            assert len(other.dinners) < len(cheapest.dinners) or cheapest.price <= other.price


def test_an_ingredient_not_on_sale_at_the_chains_costs_its_usual_price() -> None:
    found = ranked(
        recipe("Kyllinggryte", CHICKEN, SIDE),
        offers=[offer("KYLLINGFILET", 100, pre_price=150, id="kiwi"), offer("POTETER", 20, pre_price=45, id="potet", store="REMA 1000")],
        matches={"kyllingfilet": ["kiwi"], "potet": ["potet"]},
    )
    one = plan(found, Weight.ONE_STORE)
    assert one is not None and one.stores == ("KIWI",) and one.price == 145  # 100 kr on sale, potatoes at 45 kr
    assert one.courses[0].usual == (("potet", 45),) and one.saving == 50


def test_a_few_of_each_main_protein() -> None:
    names = [f"Kylling nr {n}" for n in range(PER_PROTEIN + 2)]
    found = ranked(
        *(recipe(name, CHICKEN) for name in names),
        offers=[offer("KYLLINGFILET", 100, pre_price=200, id="kiwi")],
        matches={"kyllingfilet": ["kiwi"]},
    )
    menu = plan(found, Weight.BALANCED, seed=1)
    assert menu is not None and len(menu.dinners) == PER_PROTEIN


def test_a_seed_gives_the_same_menu() -> None:
    found = sale_at_two_chains(200)
    for weight in Weight:
        assert plan(found, weight, seed=7) == plan(found, weight, seed=7)


def test_nothing_on_sale_is_no_menu() -> None:
    found = ranked(recipe("Kyllinggryte", CHICKEN), offers=[offer("KYLLINGFILET", 100, id="kiwi")], matches={"kyllingfilet": ["kiwi"]})
    assert plan(found) is None


def test_a_seed_stays_near_the_best() -> None:
    meat = [("kjøttdeig", "/kjøtt/kjøttdeig"), ("svinekotelett", "/kjøtt/svinekjøtt"), ("lammekjøtt", "/kjøtt/lamme")]
    parts = [ingredient(name, 400, "g", category) for name, category in meat] + [CHICKEN, SALMON]
    found = ranked(
        *(recipe(f"Middag {n}", part) for n, part in enumerate(parts * 2)),
        offers=[offer(p.name.upper(), 40 + 7 * n, pre_price=200, id=p.name, store=("KIWI", "MENY")[n % 2]) for n, p in enumerate(parts)],
        matches={p.name: [p.name] for p in parts},
    )
    for weight in Weight:
        best = plan(found, weight)
        assert best is not None
        menus = [plan(found, weight, seed) for seed in range(1, 30)]
        assert len({m.dinners for m in menus if m}) > 1  # «Ny meny» gives another menu
        for m in menus:
            assert m is not None and len(m.stores) <= len(best.stores) and len(m.dinners) == len(best.dinners)
            assert m.price + 80 * (len(m.stores) - 1) <= (best.price + 80 * (len(best.stores) - 1)) * (1 + TOLERANCE)


def test_every_card_adds_up_to_its_price_and_the_menu_to_the_cards() -> None:
    for found in (on_sale_at_both(50), on_sale_at_both(150), sale_at_two_chains(100)):
        for weight in Weight:
            menu = plan(found, weight, seed=4)
            assert menu is not None
            for c in menu.courses:
                bought = [x.sale for x in c.dinner.deals if x.sale]
                assert all(o.store in menu.stores for o in bought)
                assert c.price == sum(o.price for o in bought) + sum(kr for _, kr in c.usual)
                assert c.saving == c.dinner.saving
            assert menu.price == sum(c.price for c in menu.courses)


def test_a_seed_leaves_the_shared_generator_alone() -> None:
    """Every request shares the process (jb 2026-11-02: "this should not st the random.seed as we have to rememer that
    multi users"): a menu draws from generators of its own."""
    before = random.getstate()
    plan(sale_at_two_chains(200), Weight.BALANCED, seed=7)
    assert random.getstate() == before
