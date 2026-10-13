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
    queries = Queries(FakeDatasets(s), Household(onion_substitute="vårløk"), Week(days=2, fish=1))
    return TestClient(main.create_app(queries))


def test_front_page_shows_the_week_and_the_rules(client: TestClient) -> None:
    html = client.get("/").text
    assert "<h1>Ukens middager</h1>" in html
    assert "Uten løk (vårløk går fint)" in html and "Glutenfritt" in html
    assert "Kyllinggryte" in html and "\u221227\u00a0%" in html and "kyllingfilet hos KIWI" in html
    assert "Bytt løk:</b> bruk vårløk i stedet" in html
    assert "og fisk én gang" in html
    for private in ("IBS", "intoleran", "år gammel"):
        assert private not in html


def test_ideas_leave_out_the_week(client: TestClient) -> None:
    html = client.get("/").text
    ideas = html[html.index('id="forslag"') :]
    week = client.get("/api/plan").json()["dinners"]
    for d in week:
        assert d["name"] not in ideas


def test_fragment_filters_and_falls_back_to_the_page(client: TestClient) -> None:
    r = client.get("/middager?protein=fisk", headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert r.headers["HX-Replace-Url"] == "/?protein=fisk#forslag"
    r = client.get("/middager?protein=fisk&tilbud=ja", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?protein=fisk&tilbud=1#forslag"


def test_unknown_choices_still_show_a_page(client: TestClient) -> None:
    assert client.get("/?protein=enhjørning&antall=abc&tilbud=kanskje").status_code == 200


def test_about_llms_robots_sitemap_health(client: TestClient) -> None:
    assert "Slik virker det" in client.get("/om").text
    llms = client.get("/llms.txt").text
    assert "http://testserver/api/plan" in llms and "kjøttdeig" in llms
    robots = client.get("/robots.txt").text
    assert "Allow: /api/" in robots and "Sitemap: http://testserver/sitemap.xml" in robots
    assert "<loc>http://testserver/om</loc>" in client.get("/sitemap.xml").text
    assert client.get("/helse").text == "ok"
    assert client.get("/favicon.ico").headers["content-type"] == "image/svg+xml"


def test_headers(client: TestClient) -> None:
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert 'rel="service-desc"' in r.headers["Link"]
    assert r.headers["Cache-Control"] == "public, max-age=300"
    assert "HX-Request" in r.headers["Vary"]
    css = client.get(main.static_url("app.css"))
    assert css.headers["Cache-Control"].endswith("immutable")


def test_canonical_host_redirects_everything_but_health(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "CANONICAL_HOST", "matris.app")
    r = client.get("/om?x=1", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "https://matris.app/om?x=1"
    assert client.get("/helse").status_code == 200


def test_head_answers_like_get() -> None:
    client = TestClient(main.app)
    r = client.head("/")
    assert r.status_code == 200 and r.content == b""


def test_the_real_site_renders() -> None:
    html = TestClient(main.app).get("/").text
    assert html.count('<article class="card">') >= 5
