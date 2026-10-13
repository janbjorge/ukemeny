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
