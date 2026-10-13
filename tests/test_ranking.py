from core.models import Gluten, Household, Onion
from core.ranking import Week, dinners, pick, plan, varied
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


def test_discounted_dinner_ranks_first_within_the_same_swaps() -> None:
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


def test_swaps_rank_before_discounts() -> None:
    s = snapshot(
        recipe("Kyllinggryte", CHICKEN, ONION),
        recipe("Laks", SALMON),
        known={"løk": traits(onion=Onion.ONION)},
        offers=[SALE],
        matches={"kyllingfilet": ["sale"]},
    )
    assert [d.dish.name for d in dinners(s, HOUSEHOLD)] == ["Laks", "Kyllinggryte"]


def test_swapped_ingredients_are_not_bought_on_offer() -> None:
    s = snapshot(
        recipe("Pasta", PASTA, CHICKEN),
        known={"spaghetti": traits(gluten=Gluten.YES)},
        offers=[offer("SPAGHETTI", 20, pre_price=30, id="pasta"), SALE],
        matches={"spaghetti": ["pasta"], "kyllingfilet": ["sale"]},
    )
    (dinner,) = dinners(s, HOUSEHOLD)
    assert [b.part.name for b in dinner.buys] == ["kyllingfilet"]


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
    names = [d.dish.name for d in plan(dinners(s, HOUSEHOLD), Week(days=4, fish=2, on_sale_only=False))]
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
    week = plan(dinners(s, HOUSEHOLD), Week(days=2, fish=0))
    assert week[0].dish.name == "Kylling" and len(week) == 2


def test_pick_repeats_proteins_only_when_it_must() -> None:
    s = snapshot(recipe("Kylling 1", CHICKEN), recipe("Kylling 2", CHICKEN))
    assert len(pick(dinners(s, HOUSEHOLD), days=2, fish=2)) == 2


def test_varied_caps_each_protein() -> None:
    s = snapshot(
        recipe("Kylling 1", CHICKEN, rating=5.0, rating_count=10),
        recipe("Kylling 2", CHICKEN, rating=4.9, rating_count=10),
        recipe("Kylling 3", CHICKEN, rating=4.8, rating_count=10),
        recipe("Svinestek", PORK),
    )
    ranked = dinners(s, HOUSEHOLD)
    assert [d.dish.name for d in varied(ranked, 2)] == ["Kylling 1", "Kylling 2", "Svinestek"]
    assert len(varied(ranked, 0)) == 4
