from datetime import date

from app.queries import Queries
from core.models import Household, Rule
from core.ranking import Week
from tests.fakes import FakeDatasets, ingredient, offer, recipe, snapshot

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
    q = queries()
    kylling = recipe("Kylling", CHICKEN).url
    assert [d.dish.name for d in q.search("", skip=frozenset({kylling})).dinners] == ["Laks"]
    assert [d.dish.name for d in q.search("kylling", skip=frozenset({kylling})).dinners] == ["Kylling"]
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


def test_household_lines_say_what_not_why() -> None:
    lines = queries(Household(onion_substitute="vårløk", garlic=Rule.AVOID)).household_lines()
    assert lines == ["Uten løk (vårløk går fint)", "Glutenfritt", "Lite laktose (under 3 g per porsjon)", "Uten hvitløk", "Barnevennlig"]
    assert not any(word in " ".join(lines).lower() for word in ("ibs", "intoleran", "mage"))
