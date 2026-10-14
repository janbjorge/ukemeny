"""The site: pages, the HTMX fragment and its no-JS fallback, headers."""

import pytest
from fastapi.testclient import TestClient

from adapters.web import main
from app.queries import Queries
from core.models import Household, Onion
from core.ranking import Week
from tests.fakes import FakeDatasets, ingredient, offer, recipe, snapshot, traits

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
SALMON = ingredient("laksefilet", 600, "g", "/fisk og sjømat")
COD = ingredient("torskefilet", 600, "g", "/fisk og sjømat")
ONION = ingredient("løk", 1, "stk.", "/grønnsaker")
HX = {"HX-Request": "true"}
GO = ' hx-trigger="mousedown, click" hx-sync="this:drop"'
"""What a search link carries besides its hx-get: it starts on mouse-down."""


@pytest.fixture
def client() -> TestClient:
    s = snapshot(
        recipe("Kyllinggryte", CHICKEN, ONION, rating=4.6, rating_count=12),
        recipe("Laks i ovn", SALMON),
        recipe("Torsk med bacon", COD),
        known={"løk": traits(onion=Onion.ONION)},
        offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale")],
        matches={"kyllingfilet": ["sale"]},
    )
    queries = Queries(FakeDatasets(s), week=Week(days=2, fish=1))  # as on the site: no rules until searched for
    return TestClient(main.create_app(queries))


def test_front_page_shows_the_week_with_no_rules_until_picked(client: TestClient) -> None:
    html = client.get("/").text
    assert "<h1>Ukens middager</h1>" in html
    assert "Kyllinggryte" in html and "\u221236\u00a0kr" in html and "kyllingfilet hos KIWI" in html  # the week shows kroner off
    assert "Bytt:" not in html and "Glutenfritt" not in html  # no rules on the page until a visitor picks them
    for gone in ("ting å sjekke", "Også på tilbud", "Prøv for eksempel", "Søker etter", "Uten bytter"):
        assert gone not in html
    picked = client.get("/?q=uten+l%C3%B8k").text
    assert "<b>Bytt:</b> vårløk for løk" in picked
    assert 'hx-get="/middager" hx-trigger="mousedown, click" hx-sync="this:drop" aria-current="true">Uten løk</a>' in picked
    for private in ("IBS", "intoleran", "år gammel"):
        assert private not in html


def test_cards_are_calm(client: TestClient) -> None:
    s = snapshot(recipe("Laks i ovn", SALMON, rating=4.6, rating_count=3))
    page = TestClient(main.create_app(Queries(FakeDatasets(s), week=Week(days=1, fish=1)))).get("/").text
    assert "★" not in page  # 3 ratings are too few to show
    assert "Sterk" not in page


def test_sorted_by_kroner_the_cards_show_kroner_off(client: TestClient) -> None:
    ideas, week = client.get("/middager?q=kylling&sorter=kroner", headers=HX).text.split('<section id="uka"')
    assert '<span class="pct">\u221236\u00a0kr</span>' in ideas  # 135 kr before, 99 kr now
    assert "\u221227\u00a0%" not in ideas and "\u221236\u00a0kr" in week  # the week shows kroner off as well


def test_ideas_leave_out_the_week(client: TestClient) -> None:
    html = client.get("/").text
    week, ideas = html[: html.index('id="forslag"')], html[html.index('id="forslag"') :]
    shown = [n for n in ("Kyllinggryte", "Laks i ovn", "Torsk med bacon") if n in week]
    assert shown and not any(n in ideas for n in shown)
    # The visit's draw goes with every search from the page (#uke), so a fragment leaves out the same week
    drew = html.split('id="uke" name="uke" value="')[1].split('"')[0]
    assert 'hx-include="#uke"' in html and client.get("/").headers["Cache-Control"] == "no-cache"  # a new week each visit
    fragment = client.get(f"/middager?uke={drew}", headers=HX | {"HX-Current-URL": "http://testserver/"}).text
    assert not any(n in fragment for n in shown)


def test_new_dinners_draws_another_week(client: TestClient) -> None:
    """«Nye middager» (jb 2026-10-14: "lets have a 'hit me' kind of button, ie. give a new set of dinners")."""
    html = client.get("/?q=glutenfri").text
    assert '<a id="ny-uke" href="/?q=glutenfri#uka" hx-get="/middager" hx-include="#q, #sted, [name=sorter]"' in html
    here = HX | {"HX-Current-URL": "http://testserver/?q=glutenfri"}
    again = client.get("/middager?q=glutenfri", headers=here | {"HX-Trigger": "ny-uke"}).text  # no #uke: a new draw
    assert '<section id="uka" hx-swap-oob="true">' in again and 'id="uke" name="uke" value="' in again
    assert 'id="q"' not in again  # the box stays as typed
    same = client.get("/middager?q=glutenfri&uke=5", headers=here).text  # a search from the page keeps its draw
    assert 'id="uka"' not in same and 'id="uke"' not in same


def test_fragment_filters_and_falls_back_to_the_page(client: TestClient) -> None:
    r = client.get("/middager?protein=fisk", headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert r.headers["HX-Replace-Url"] == "/?q=fisk#forslag"
    r = client.get("/middager?protein=fisk&tilbud=ja", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?q=fisk+p%C3%A5+tilbud#forslag"


def test_search_page_says_what_it_understood(client: TestClient) -> None:
    html = client.get("/?q=laks+i+ovnn").text
    assert 'value="laks ovn"' in html  # the box shows the search as understood
    assert "<mark>Laks</mark> i <mark>ovn</mark>" in html
    assert "Fant ikke «ovnn», så viser treff for «ovn»." in html
    assert '<p class="count" role="status">1 middag</p>' in html


def test_nothing_found_offers_what_to_drop(client: TestClient) -> None:
    html = client.get("/?q=fisk+p%C3%A5+tilbud").text
    assert "Ingen middager passer alt dette." in html
    assert 'href="/?q=p%C3%A5+tilbud#forslag"' in html  # drop «fisk»


def test_chips_toggle_and_count(client: TestClient) -> None:
    html = client.get("/middager?q=kylling", headers=HX).text
    assert f'hx-get="/middager?q=kylling+p%C3%A5+tilbud"{GO}>På tilbud <span class="n">1</span>' in html
    assert f'hx-get="/middager?q=fisk"{GO} data-protein="fisk">Fisk <span class="n">2</span>' in html
    assert 'data-protein="kylling" aria-current="true">Kylling</a>' in html
    assert '<span class="off">Godt likt</span>' in html  # nothing would match
    assert 'hx-get="/middager?q=kylling+uten+l%C3%B8k" hx-trigger="mousedown, click" hx-sync="this:drop">Uten løk</a>' in html
    assert 'aria-label="Allergier">' in html and f'hx-get="/middager?q=kylling+uten+egg"{GO}>Uten egg</a>' in html
    assert ">Lav FODMAP</a>" in html and ">Vegetar</a>" in html
    assert 'aria-label="Sorter">' in html and f'hx-get="/middager?q=kylling&amp;sorter=prosent"{GO}>Rabatt %</a>' in html
    assert "Anbefalt" not in html and 'name="sorter"' not in html  # neither on is the ranking (jb 2026-10-14)
    by_kroner = client.get("/?q=kylling&sorter=kroner").text
    assert f'hx-get="/middager?q=kylling"{GO} aria-current="true">Rabatt kr</a>' in by_kroner  # off again
    assert f'hx-get="/middager?q=kylling&amp;sorter=prosent"{GO}>Rabatt %</a>' in by_kroner  # the other one replaces it
    assert f'hx-get="/middager?q=kylling+uten+egg&amp;sorter=kroner"{GO}>Uten egg</a>' in by_kroner  # a chip keeps the sort
    assert '<input type="hidden" name="sorter" form="sok" value="kroner">' in by_kroner  # and so does typing
    proteins_row = html[html.index('class="chips proteins"') :]
    assert "Vegetar" not in proteins_row[: proteins_row.index("</nav>")]  # a rule in Kosthold, not a main protein
    proteins = html[html.index('class="chips proteins"') :]
    assert proteins.index(">Kylling<") < proteins.index(">Alle ")  # a chosen chip leads its row


def test_the_box_follows_chips_but_not_typing(client: TestClient) -> None:
    clicked = client.get("/middager?q=fisk", headers=HX).text
    assert 'id="q"' in clicked and 'hx-swap-oob="true"' in clicked
    assert '<section id="uka" hx-swap-oob="true">' in clicked  # the week follows the rules
    typed = client.get("/middager?q=fisk", headers=HX | {"HX-Trigger": "q"}).text
    assert 'id="q"' not in typed
    same_rules = client.get("/middager?q=fisk+rask&uke=1", headers=HX | {"HX-Current-URL": "http://testserver/?q=fisk#forslag"}).text
    assert 'id="uka"' not in same_rules  # the week only comes along when the diet rules change
    new_rules = client.get("/middager?q=fisk+glutenfri&uke=1", headers=HX | {"HX-Current-URL": "http://testserver/?q=fisk#forslag"}).text
    assert '<section id="uka" hx-swap-oob="true">' in new_rules


def test_unknown_choices_still_show_a_page(client: TestClient) -> None:
    assert client.get("/?protein=enhjørning&antall=abc&tilbud=kanskje").status_code == 200
    assert client.get("/?q=" + "x" * 5000 + "&antall=99999999999").status_code == 200


def test_about_llms_robots_sitemap_health(client: TestClient) -> None:
    about = client.get("/om").text
    nav = about[about.index('<nav class="top"') : about.index("</nav>")]
    assert nav.count("<a ") == 2 and 'href="/om" aria-current="page"' in nav  # one page for the week and the search (jb 2026-10-13)
    assert "Slik virker det" in about
    assert "Les http://testserver/llms.txt først" in about  # a prompt to paste into an agent (jb 2026-10-13)
    llms = client.get("/llms.txt").text
    assert "http://testserver/api/plan" in llms and "kjøttdeig" in llms
    assert "- [melkefri](http://testserver/api/plan?q=melkefri)" in llms  # a link per rule: agents need not write URLs
    robots = client.get("/robots.txt").text
    assert "Allow: /api/" in robots and "Sitemap: http://testserver/sitemap.xml" in robots
    assert robots.startswith("User-agent: ChatGPT-User\nUser-agent: Claude-User\nUser-agent: Perplexity-User\nAllow: /\n")
    assert "<loc>http://testserver/om</loc>" in client.get("/sitemap.xml").text
    assert client.get("/helse").text == "ok"
    assert client.get("/favicon.ico").headers["content-type"] == "image/svg+xml"


def test_headers(client: TestClient) -> None:
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert 'rel="service-desc"' in r.headers["Link"]
    assert r.headers["Cache-Control"] == "no-cache"  # the week is drawn anew on every visit
    assert client.get("/om").headers["Cache-Control"] == "public, max-age=300"
    assert "HX-Request" in r.headers["Vary"]
    css = client.get(main.static_url("app.css"))
    assert css.headers["Cache-Control"].endswith("immutable")


def test_canonical_host_redirects_everything_but_health(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "CANONICAL_HOST", "matris.app")
    r = client.get("/om?x=1", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "https://matris.app/om?x=1"
    assert client.get("/helse").status_code == 200


def test_more_appends_the_next_page(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "PAGE", 1)
    s = snapshot(*(recipe(f"Laks {n}", SALMON) for n in range(4)))
    small = TestClient(main.create_app(Queries(FakeDatasets(s), Household(), Week(days=1, fish=1))))
    html = small.get("/?q=laks").text
    assert html.count('<article class="card"') == 2  # the week, and one idea
    assert 'hx-get="/middager/flere?q=laks&amp;fra=1"' in html and 'Vis flere <span class="n">3 til</span>' in html
    assert 'hx-trigger="intersect once, click"' in html  # loads by itself when scrolled to
    assert '<span class="ahead" hx-get="/middager/flere?q=laks&amp;fra=1" hx-trigger="intersect once"' in html  # and before that
    more = small.get("/middager/flere?q=laks&fra=1", headers=HX).text
    assert more.count('<article class="card"') == 1 and "fra=2" in more and "<html" not in more
    last = small.get("/middager/flere?q=laks&fra=3", headers=HX).text
    assert last.count('<article class="card"') == 1 and "Vis flere" not in last
    r = small.get("/middager/flere?q=laks&fra=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?q=laks&antall=2#forslag"


def test_phone_details(client: TestClient) -> None:
    html = client.get("/").text
    assert "<style>" in html and 'rel="stylesheet"' not in html  # inline: nothing blocks the first paint
    assert "viewport-fit=cover" in html and 'name="theme-color"' in html and 'rel="manifest"' in html
    manifest = client.get("/manifest.webmanifest")
    assert manifest.headers["content-type"] == "application/manifest+json"
    assert manifest.json()["short_name"] == "matris" and len(manifest.json()["icons"]) == 2
    for icon in manifest.json()["icons"]:
        assert client.get(icon["src"]).headers["content-type"] == "image/png"
    assert client.get("/apple-touch-icon.png").headers["content-type"] == "image/png"


def test_light_always() -> None:
    css = (main.HERE / "static" / "app.css").read_text()
    assert "prefers-color-scheme" not in css and "color-scheme: light" in css


def test_head_answers_like_get() -> None:
    client = TestClient(main.app)
    r = client.head("/")
    assert r.status_code == 200 and r.content == b""


def test_the_real_site_renders() -> None:
    html = TestClient(main.app).get("/").text
    assert html.count('<article class="card"') >= 5


def test_offers_are_from_every_store_until_a_place_is_picked() -> None:
    s = snapshot(
        recipe("Kyllinggryte", CHICKEN),
        recipe("Laks i ovn", SALMON),
        offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale", catalog="kiwi-vest")],
        matches={"kyllingfilet": ["sale"]},
        places={"Bergen": ["kiwi-vest"], "Tromsø": ["kiwi-nord"]},
    )
    client = TestClient(main.create_app(Queries(FakeDatasets(s), week=Week(days=2, fish=1))))
    anywhere = client.get("/").text
    assert '<option value="">Hele landet</option>' in anywhere and "\u221236\u00a0kr" in anywhere
    assert '<select id="sted" name="sted" form="sok" hx-get="/middager" hx-include="#sok">' in anywhere
    north = client.get("/?sted=troms%C3%B8").text
    assert '<option value="tromsø" selected>Tromsø</option>' in north and 'class="on"' in north
    assert "\u221236\u00a0kr" not in north  # nothing on sale near Tromsø
    assert 'href="/?q=glutenfri&amp;sted=troms%C3%B8#forslag"' in north  # a chip keeps the place
    week = '<section id="uka" hx-swap-oob="true">'
    tromso = HX | {"HX-Current-URL": "http://testserver/?sted=troms%C3%B8"}
    moved = client.get("/middager?q=&sted=bergen", headers=tromso | {"HX-Trigger": "sted"})
    assert week in moved.text and "\u221236\u00a0kr" in moved.text  # another place, another week
    assert moved.headers["HX-Replace-Url"] == "/?sted=bergen#forslag" and 'id="q"' not in moved.text  # the box stays
    stayed = client.get("/middager?q=kylling&sted=Bergen&uke=1", headers=HX | {"HX-Current-URL": "http://testserver/?sted=bergen"}).text
    assert week not in stayed
    assert client.get("/middager?sted=bergen", follow_redirects=False).headers["location"] == "/?sted=bergen#forslag"
    assert "Bergen, Tromsø" in client.get("/om").text
