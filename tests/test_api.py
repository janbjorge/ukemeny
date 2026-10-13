from fastapi.testclient import TestClient

from adapters.web import main
from app.queries import Queries
from core.models import Household
from core.ranking import Week
from tests.fakes import FakeDatasets, ingredient, offer, recipe, snapshot

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
SALMON = ingredient("laksefilet", 600, "g", "/fisk og sjømat")
KYLLING = recipe("Kyllinggryte", CHICKEN)

s = snapshot(
    KYLLING, recipe("Laks i ovn", SALMON), offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale")], matches={"kyllingfilet": ["sale"]}
)
client = TestClient(main.create_app(Queries(FakeDatasets(s), Household(), Week(days=2, fish=1))))


def test_plan() -> None:
    body = client.get("/api/plan").json()
    assert (body["considered"], body["fitting"], body["on_sale"], body["stores"]) == (2, 2, 1, ["KIWI"])
    first = body["dinners"][0]
    assert first["rank"] == 1 and first["protein"] in {"kylling", "fisk"}
    sale = next(d for d in body["dinners"] if d["name"] == "Kyllinggryte")["discounts"][0]
    assert sale == {
        "ingredient": "kyllingfilet",
        "store": "KIWI",
        "offer": "KYLLINGBRYST",
        "price": 99.0,
        "before": 135.0,
        "discount_percent": 27,
        "valid_until": "2026-10-18",
    }


def test_cors_is_open() -> None:
    r = client.get("/api/plan", headers={"Origin": "https://chat.openai.com"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_dinners_filters() -> None:
    names = [d["name"] for d in client.get("/api/middager?protein=fisk").json()["dinners"]]
    assert names == ["Laks i ovn"]
    names = [d["name"] for d in client.get("/api/middager?tilbud=1").json()["dinners"]]
    assert names == ["Kyllinggryte"]
    assert len(client.get("/api/middager?antall=1").json()["dinners"]) == 1


def test_dinners_search() -> None:
    body = client.get("/api/middager", params={"q": "laksefilt i ovn"}).json()
    assert [d["name"] for d in body["dinners"]] == ["Laks i ovn"]
    assert body["search"]["query"] == "laksefilet ovn"
    assert body["search"]["corrected"] == [{"typed": "laksefilt", "used": "laksefilet"}]
    assert body["search"]["understood"][0] == {"kind": "with", "text": "laksefilet", "label": "Med laksefilet"}
    assert body["dinners"][0]["matched"] == ["laksefilet"]
    body = client.get("/api/middager", params={"q": "kylling", "tilbud": "1"}).json()
    assert body["search"]["query"] == "kylling på tilbud" and body["search"]["total"] == 1
    body = client.get("/api/middager", params={"q": "fisk på tilbud"}).json()
    assert body["dinners"] == [] and [c["text"] for c in body["search"]["without"]] == ["fisk", "på tilbud"]


def test_api_root_points_at_the_schema() -> None:
    for path in ("/api", "/api/"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/api/openapi.json"


def test_recipe_and_not_found() -> None:
    body = client.get("/api/oppskrift", params={"url": KYLLING.url}).json()
    assert body["fits"] is True and body["recipe"]["protein"] == "kylling"
    assert "ingredients" not in body["recipe"]
    r = client.get("/api/oppskrift", params={"url": "https://www.matprat.no/oppskrifter/kos/nei/"})
    assert r.status_code == 404


def test_openapi_names_this_server() -> None:
    schema = client.get("/api/openapi.json").json()
    assert schema["servers"] == [{"url": "http://testserver/api"}]
    assert {"/plan", "/middager", "/oppskrift"} <= set(schema["paths"])
