from datetime import date

from app.queries import Queries
from core.models import Gluten, Household, Item, Level, Onion, Rule
from core.ranking import Week
from core.search import Order
from tests.fakes import FakeDatasets, ingredient, offer, recipe, snapshot, traits

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
SALMON = ingredient("laksefilet", 600, "g", "/fisk og sjømat")
SALE = offer("KYLLINGBRYST", 99, pre_price=135, id="sale")


def queries(household: Household | None = None) -> Queries:
    s = snapshot(recipe("Kylling", CHICKEN), recipe("Laks", SALMON), offers=[SALE], matches={"kyllingfilet": ["sale"]})
    return Queries(FakeDatasets(s), household or Household(), Week(days=2, fish=1))


def test_plan_and_dinners() -> None:
    q = queries()
    week = q.plan()
    assert (week.considered, week.fitting, week.on_sale, week.offers, week.stores) == (2, 2, 1, 1, ("KIWI",))
    assert {d.dish.name for d in week.dinners} == {"Kylling", "Laks"}


def test_search() -> None:
    q = queries()
    assert [d.dish.name for d in q.search("på tilbud").dinners] == ["Kylling"]
    found = q.search("fisk")
    assert [d.dish.name for d in found.dinners] == ["Laks"] and found.total == 1
    assert found.counts.proteins == {"kylling": 1, "fisk": 1}
    assert [d.dish.name for d in q.search("laks").dinners] == ["Laks"]
    assert q.search("laksefilet").via == {recipe("Laks", SALMON).url: ("laksefilet",)}


def test_search_skips_the_week_only_when_browsing_and_relaxes_when_empty() -> None:
    s = snapshot(recipe("Kylling", CHICKEN), recipe("Laks", SALMON), offers=[SALE], matches={"kyllingfilet": ["sale"]})
    q = Queries(FakeDatasets(s), week=Week(days=1, fish=0))
    assert [d.dish.name for d in q.plan().dinners] == ["Kylling"]
    assert [d.dish.name for d in q.search("", skip_week=True).dinners] == ["Laks"]
    assert [d.dish.name for d in q.search("glutenfri", skip_week=True).dinners] == ["Laks"]  # rules alone are browsing
    assert [d.dish.name for d in q.search("kylling", skip_week=True).dinners] == ["Kylling"]
    q = queries()
    found = q.search("fisk på tilbud")
    assert found.dinners == () and found.total == 0
    assert [(c.text, n) for c, n in found.relax] == [("fisk", 1), ("på tilbud", 1)]


def test_search_limit_and_variety() -> None:
    q = queries()
    assert len(q.search("", limit=1).dinners) == 1 and q.search("", limit=1).total == 2


def test_check_finds_dinners_in_the_snapshot_only() -> None:
    q = queries()
    found = q.check(recipe("Kylling", CHICKEN).url)
    assert found is not None and found.verdict.blocked is None
    assert q.check("https://www.matprat.no/oppskrifter/kos/finnes-ikke/") is None


def test_offers_until_and_stale() -> None:
    q = queries()
    assert q.offers_until() == date(2026, 10, 18)
    assert not q.stale(date(2026, 10, 18))
    assert q.stale(date(2026, 10, 19))


def test_the_site_starts_with_no_rules_and_the_search_adds_them() -> None:
    onion = ingredient("løk", 400, "g", "/grønnsaker")
    pasta = ingredient("spagetti", 400, "g", "/pasta/ris")
    s = snapshot(
        recipe("Biff med løk", onion),
        recipe("Pasta", pasta),
        recipe("Laks", SALMON),
        known={"løk": traits(onion=Onion.ONION), "spagetti": traits(gluten=Gluten.YES)},
    )
    q = Queries(FakeDatasets(s))
    assert {d.dish.name for d in q.search("").dinners} == {"Biff med løk", "Pasta", "Laks"}
    assert all(not d.verdict.swaps for d in q.search("").dinners)
    found = q.search("uten løk glutenfri")
    assert {d.dish.name for d in found.dinners} == {"Pasta", "Laks"}  # onion is the point of the biff
    assert found.household.onion is Rule.AVOID and found.household.gluten is Rule.AVOID
    pasta_card = next(d for d in found.dinners if d.dish.name == "Pasta")
    assert [n.swap for n in pasta_card.verdict.swaps] == ["glutenfri spagetti"]
    assert q.plan(found.household).fitting == 2 and q.plan().fitting == 3
    checked = q.check(recipe("Pasta", pasta).url, q.household("glutenfri"))
    assert checked is not None and checked.verdict.swaps


def test_sort_by_discount_in_percent_or_kroner() -> None:
    lamb = ingredient("lammekotelett", 600, "g", "/kjøtt/lamme-/fåre-/sauekjøtt")
    s = snapshot(
        recipe("Kylling", CHICKEN),
        recipe("Laks", SALMON),
        recipe("Lam", lamb),
        offers=[offer("KYLLINGFILET", 60, pre_price=100, id="k"), offer("LAMMEKOTELETT", 200, pre_price=300, id="l")],
        matches={"kyllingfilet": ["k"], "lammekotelett": ["l"]},
    )
    q = Queries(FakeDatasets(s))
    assert [d.dish.name for d in q.search(order=Order.PERCENT).dinners] == ["Kylling", "Lam", "Laks"]  # 40 % before 33 %
    assert [d.dish.name for d in q.search(order=Order.KRONER).dinners] == ["Lam", "Kylling", "Laks"]  # 100 kr before 40 kr
    assert q.search(order=Order.KRONER).total == 3  # sorting leaves nothing out
    assert not q.search("rabatt i kroner").dinners  # not a word for sorting (jb 2026-10-14)


def test_allergies_and_vegetar_leave_dinners_out() -> None:
    mayo = ingredient("majones", 1, "dl", "/margarin/olje/majones")
    stock = ingredient("kyllingbuljong", 5, "dl", "/diverse")
    s = snapshot(
        recipe("Potetsalat", mayo),
        recipe("Grønnsakssuppe", stock),
        recipe("Laks", SALMON),
        known={
            "majones": traits(contains={Item.EGG: Level.YES, Item.ANIMAL: Level.YES}),
            "kyllingbuljong": traits(contains={Item.MEAT: Level.YES, Item.ANIMAL: Level.YES}),
            "laksefilet": traits(contains={Item.FISH: Level.YES, Item.ANIMAL: Level.YES}),
        },
    )
    q = Queries(FakeDatasets(s))
    assert {d.dish.name for d in q.search("uten egg").dinners} == {"Grønnsakssuppe", "Laks"}
    assert {d.dish.name for d in q.search("vegetar").dinners} == {"Potetsalat"}  # the stock is chicken
    assert {d.dish.name for d in q.search("uten kjøtt").dinners} == {"Potetsalat", "Laks"}
    assert not q.search("vegansk").dinners
    checked = q.check(recipe("Potetsalat", mayo).url, q.household("uten egg"))
    assert checked is not None and checked.verdict.blocked == "inneholder egg (majones)"


def test_offers_are_from_the_place_picked_or_from_every_store() -> None:
    west = offer("KYLLINGBRYST", 99, pre_price=135, id="vest", catalog="kiwi-vest")
    north = offer("LAKSEFILET", 120, pre_price=160, id="nord", catalog="kiwi-nord")
    s = snapshot(
        recipe("Kylling", CHICKEN),
        recipe("Laks", SALMON),
        offers=[west, north],
        matches={"kyllingfilet": ["vest"], "laksefilet": ["nord"]},
        places={"Bergen": ["kiwi-vest", "rema"], "Tromsø": ["kiwi-nord", "rema"]},
    )
    q = Queries(FakeDatasets(s), week=Week(days=2, fish=1))

    def on_sale(place: str | None = None) -> list[str]:
        return sorted(d.dish.name for d in q.search("på tilbud", place).dinners)

    assert on_sale() == ["Kylling", "Laks"] and q.search("på tilbud").place is None
    assert on_sale("Bergen") == ["Kylling"]
    assert on_sale("Tromsø") == ["Laks"]
    assert q.search("", "Bergen").place == "Bergen"
    assert (q.place("bergen"), q.place("TROMSO"), q.place("Gotham"), q.place("")) == ("Bergen", "Tromsø", None, None)
    week = q.plan(place="Bergen")
    assert (week.place, week.offers, week.on_sale) == ("Bergen", 1, 1)
    assert (q.plan().place, q.plan().offers, q.plan().on_sale) == (None, 2, 2)
    home = Queries(FakeDatasets(s), home="Tromsø")  # the CLI's place, from profile.yaml
    assert [d.dish.name for d in home.search("på tilbud").dinners] == ["Laks"]
    assert [d.dish.name for d in home.search("på tilbud", "Bergen").dinners] == ["Kylling"]  # a place picked goes first


def test_rankings_past_the_limit_are_dropped_and_worked_out_again() -> None:
    q = queries()
    q.KEPT = 1
    first = q.ranked()
    assert q.ranked(Household(gluten=Rule.OK)) and q.ranked() is not first
    assert [d.dish.name for d in q.search("på tilbud").dinners] == ["Kylling"]
