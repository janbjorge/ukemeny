"""The site: pages, the HTMX fragment and its no-JS fallback, headers."""

import pytest
from fastapi.testclient import TestClient

from adapters.web import main
from app.queries import Queries
from core.models import Household, Onion
from tests.fakes import SIDE, SIDE_MATCH, SIDE_OFFER, FakeDatasets, ingredient, offer, recipe, snapshot, traits

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
        recipe("Kyllinggryte", CHICKEN, ONION, SIDE, rating=4.6, rating_count=12),
        recipe("Laks i ovn", SALMON, SIDE),
        recipe("Torsk med bacon", COD, SIDE),
        known={"løk": traits(onion=Onion.ONION)},
        offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale", size=700, unit="g"), SIDE_OFFER],
        matches={"kyllingfilet": ["sale"], **SIDE_MATCH},
    )
    queries = Queries(FakeDatasets(s))  # as on the site: no rules until searched for
    return TestClient(main.create_app(queries))


def test_front_page_is_the_search_with_no_rules_until_picked(client: TestClient) -> None:
    html = client.get("/").text
    assert "<h1>Finn en middag</h1>" in html
    assert 'id="uka"' not in html and "Nye middager" not in html  # no week on the page (jb 2026-10-14)
    assert all(n in html for n in ("Kyllinggryte", "Laks i ovn", "Torsk med bacon"))  # the list leaves nothing out
    assert '<span class="sum">\u221261\u00a0kr</span> <span class="n">på 2 varer</span>' in html  # 135 to 99 kr, 45 to 20 kr
    assert 'kyllingfilet</span><span class="store">KIWI</span><span class="lead"></span><span class="off">\u221236\u00a0kr</span>' in html
    assert "per person" not in html  # the kroner a head are in the API and the CLI, not on the card (jb 2026-10-23)
    assert "%" not in html[html.index('class="cards"') :]  # no percent (jb 2026-10-22)
    assert "Bytt:" not in html and "Glutenfritt" not in html  # no rules on the page until a visitor picks them
    for gone in ("ting å sjekke", "Også på tilbud", "Prøv for eksempel", "Søker etter", "Uten bytter"):
        assert gone not in html
    picked = client.get("/?q=uten+l%C3%B8k").text
    assert "Bytt" not in picked  # nothing is swapped (jb 2026-10-22)
    assert 'hx-get="/middager" hx-trigger="mousedown, click" hx-sync="this:drop" aria-current="true">Uten løk</a>' in picked
    for private in ("IBS", "intoleran", "år gammel"):
        assert private not in html


def test_cards_are_calm(client: TestClient) -> None:
    s = snapshot(recipe("Laks i ovn", SALMON, SIDE, rating=4.6, rating_count=3), offers=[SIDE_OFFER], matches=SIDE_MATCH)
    page = TestClient(main.create_app(Queries(FakeDatasets(s)))).get("/").text
    assert "★" not in page  # 3 ratings are too few to show
    assert "Sterk" not in page


def test_an_old_sort_link_still_opens(client: TestClient) -> None:
    r = client.get("/middager?q=kylling&sorter=kroner", headers=HX)
    assert r.headers["HX-Replace-Url"] == "/?q=kylling#forslag"  # «Sorter» is gone (jb 2026-10-22)
    ideas = r.text
    assert '<span class="sum">\u221261\u00a0kr</span>' in ideas
    assert '<span class="off">\u221236\u00a0kr</span>' in ideas and '<span class="off">\u221225\u00a0kr</span>' in ideas


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
    assert "På tilbud" not in html  # no chip (jb 2026-10-22)
    assert f'hx-get="/middager?q=kylling+eller+fisk"{GO} data-protein="fisk">Fisk <span class="n">2</span>' in html
    assert 'data-protein="kylling" aria-current="true">Kylling</a>' in html
    assert '<span class="off">Godt likt</span>' in html  # nothing would match
    assert 'hx-get="/middager?q=kylling+uten+l%C3%B8k" hx-trigger="mousedown, click" hx-sync="this:drop">Uten løk</a>' in html
    assert 'aria-label="Allergier">' in html and f'hx-get="/middager?q=kylling+uten+egg"{GO}>Uten egg</a>' in html
    assert ">Lav FODMAP</a>" in html and ">Vegetar</a>" in html
    assert "Sorter" not in html and "Rabatt" not in html and "sorter" not in html  # one order (jb 2026-10-22: "remove the entire; Sorter")
    proteins_row = html[html.index('class="chips proteins"') :]
    assert "Vegetar" not in proteins_row[: proteins_row.index("</nav>")]  # a rule in Kosthold, not a main protein
    proteins = html[html.index('class="chips proteins"') :]
    assert proteins.index(">Alle ") < proteins.index(">Kylling<")  # in the order written: a panel shows every chip
    assert 'class="picked"><a href="/#forslag" hx-get="/middager"' in html and 'aria-label="Fjern Kylling">Kylling' in html
    none_left = client.get("/middager?q=kylling+vegansk", headers=HX).text
    assert 'aria-label="Fjern Kylling">Kylling' in none_left and 'data-protein="kylling" aria-current="true">Kylling</a>' in none_left
    both = client.get("/middager?q=kylling+eller+fisk", headers=HX).text
    assert f'hx-get="/middager?q=fisk"{GO} data-protein="kylling" aria-current="true">Kylling</a>' in both
    assert f'hx-get="/middager?q=kylling"{GO} data-protein="fisk" aria-current="true">Fisk</a>' in both


def test_the_box_follows_chips_but_not_typing(client: TestClient) -> None:
    clicked = client.get("/middager?q=fisk", headers=HX).text
    assert 'id="q"' in clicked and 'hx-swap-oob="true"' in clicked
    typed = client.get("/middager?q=fisk", headers=HX | {"HX-Trigger": "q"}).text
    assert 'id="q"' not in typed


def test_unknown_choices_still_show_a_page(client: TestClient) -> None:
    assert client.get("/?protein=enhjørning&antall=abc&tilbud=kanskje").status_code == 200
    assert client.get("/?q=" + "x" * 5000 + "&antall=99999999999").status_code == 200


def test_about_llms_robots_sitemap_health(client: TestClient) -> None:
    about = client.get("/om").text
    nav = about[about.index('<nav class="top"') : about.index("</nav>")]
    assert nav.count("<a ") == 2 and 'href="/om" aria-current="page"' in nav  # one page for the search (jb 2026-10-13)
    assert "Slik virker det" in about
    assert "mattilbud" not in about  # no pricing sources on the page (jb 2026-10-22)
    assert "sparer deg minst 20 kroner" in about  # the floor (jb 2026-10-22)
    assert "Les http://testserver/llms.txt først" in about  # a prompt to paste into an agent (jb 2026-10-13)
    llms = client.get("/llms.txt").text
    assert "api/plan" not in llms and "kjøttdeig" in llms  # no week (jb 2026-10-22)
    assert "- [melkefri](http://testserver/api/middager?q=melkefri)" in llms  # a link per rule: agents need not write URLs
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
    assert r.headers["Cache-Control"] == client.get("/om").headers["Cache-Control"] == "public, max-age=300"
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
    s = snapshot(*(recipe(f"Laks {n}", SALMON, SIDE) for n in range(4)), offers=[SIDE_OFFER], matches=SIDE_MATCH)
    small = TestClient(main.create_app(Queries(FakeDatasets(s), Household())))
    html = small.get("/?q=laks").text
    assert html.count('<article class="card"') == 1
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
    client = TestClient(main.create_app(Queries(FakeDatasets(s))))
    anywhere = client.get("/").text
    assert '<option value="">Hele landet</option>' in anywhere and "\u221236\u00a0kr" in anywhere
    assert '<select id="sted" name="sted" form="sok" hx-get="/middager" hx-include="#sok">' in anywhere
    north = client.get("/?sted=troms%C3%B8").text
    assert '<option value="tromsø" selected>Tromsø</option>' in north and 'class="on"' in north
    assert "\u221236\u00a0kr" not in north  # nothing on sale near Tromsø
    assert 'href="/?q=glutenfri&amp;sted=troms%C3%B8#forslag"' in north  # a chip keeps the place
    moved = client.get("/middager?q=&sted=bergen", headers=HX | {"HX-Trigger": "sted"})
    assert "\u221236\u00a0kr" in moved.text  # another place, other offers
    assert moved.headers["HX-Replace-Url"] == "/?sted=bergen#forslag" and 'id="q"' not in moved.text  # the box stays
    assert client.get("/middager?sted=bergen", follow_redirects=False).headers["location"] == "/?sted=bergen#forslag"
    assert "Bergen, Tromsø" in client.get("/om").text
