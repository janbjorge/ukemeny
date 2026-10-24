from fastapi.testclient import TestClient

from adapters.web import main
from app.queries import Queries
from core.models import Household
from tests.fakes import SIDE, SIDE_MATCH, SIDE_OFFER, FakeDatasets, ingredient, offer, recipe, snapshot

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
SALMON = ingredient("laksefilet", 600, "g", "/fisk og sjømat")
KYLLING = recipe("Kyllinggryte", CHICKEN)

s = snapshot(
    KYLLING,
    recipe("Laks i ovn", SALMON, SIDE),
    offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale"), SIDE_OFFER],
    matches={"kyllingfilet": ["sale"], **SIDE_MATCH},
)
client = TestClient(main.create_app(Queries(FakeDatasets(s), Household())))


def test_dinners() -> None:
    body = client.get("/api/middager").json()
    assert (body["considered"], body["fitting"], body["on_sale"], body["offers"]) == (2, 2, 1, 2)
    first = body["dinners"][0]
    assert first["rank"] == 1 and first["protein"] == "kylling"  # the most kroner off first
    assert "plan" not in body and "plan" not in body["links"]
    sale = next(d for d in body["dinners"] if d["name"] == "Kyllinggryte")["discounts"][0]
    assert sale == {
        "ingredient": "kyllingfilet",
        "store": "KIWI",
        "offer": "KYLLINGBRYST",
        "price": 99.0,
        "before": 135.0,
        "discount_percent": 27,
        "valid_until": "2026-10-18",
        "fit": "exact",
        "counted": True,
    }


def test_cors_is_open() -> None:
    r = client.get("/api/middager", headers={"Origin": "https://chat.openai.com"})
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


def test_rules_come_from_q() -> None:
    plain = client.get("/api/middager").json()
    ruled = client.get("/api/middager", params={"q": "uten løk glutenfri"}).json()
    assert plain["fitting"] == ruled["fitting"] == 2  # nothing here has onion or gluten
    body = client.get("/api/oppskrift", params={"url": KYLLING.url, "q": "glutenfri"}).json()
    assert body["fits"] is True


def test_api_root_points_at_the_schema() -> None:
    for path in ("/api", "/api/"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/api/openapi.json"


def test_no_notes_name_ingredients() -> None:
    for path in ("/api/middager", f"/api/oppskrift?url={KYLLING.url}"):
        body = client.get(path).json()
        for d in body.get("dinners", [body]):
            assert "notes" not in d


def test_recipe_and_not_found() -> None:
    body = client.get("/api/oppskrift", params={"url": KYLLING.url}).json()
    assert body["fits"] is True and body["recipe"]["protein"] == "kylling"
    assert "ingredients" not in body["recipe"]
    r = client.get("/api/oppskrift", params={"url": "https://www.matprat.no/oppskrifter/kos/nei/"})
    assert r.status_code == 404


def test_openapi_names_this_server() -> None:
    schema = client.get("/api/openapi.json").json()
    assert schema["servers"] == [{"url": "http://testserver/api"}]
    assert set(schema["paths"]) == {"/middager", "/oppskrift"}  # no week (jb 2026-10-22)


def test_answers_link_to_each_rule_so_agents_need_not_write_urls() -> None:
    ruled = client.get("/api/middager", params={"q": "melkefri"}).json()["links"]
    assert ruled["add"]["glutenfri"] == "http://testserver/api/middager?q=melkefri+glutenfri"
    assert ruled["remove"] == {"melkefri": "http://testserver/api/middager"}
    assert ruled["dinners"] == "http://testserver/api/middager?q=melkefri"
    found = client.get("/api/middager", params={"q": "kylling melkefri"}).json()["links"]
    assert found["add"]["uten løk"] == "http://testserver/api/middager?q=kylling+melkefri+uten+l%C3%B8k"
    assert "melkefri" not in found["add"]


def test_a_place_in_answers_and_links() -> None:
    s = snapshot(
        KYLLING,
        offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale", catalog="kiwi-vest")],
        matches={"kyllingfilet": ["sale"]},
        places={"Bergen": ["kiwi-vest"], "Tromsø": ["kiwi-nord"]},
    )
    api = TestClient(main.create_app(Queries(FakeDatasets(s), Household())))
    body = api.get("/api/middager").json()
    assert (body["place"], body["offers"], body["on_sale"]) == (None, 1, 1)
    assert body["links"]["places"] == {
        "Bergen": "http://testserver/api/middager?sted=bergen",
        "Tromsø": "http://testserver/api/middager?sted=troms%C3%B8",
    }
    body = api.get(body["links"]["places"]["Tromsø"]).json()
    assert (body["place"], body["offers"], body["on_sale"]) == ("Tromsø", 0, 0)
    assert body["links"]["remove"] == {"sted": "http://testserver/api/middager"}
    assert list(body["links"]["places"]) == ["Bergen"]
    body = api.get("/api/middager?q=kylling+melkefri&sted=Bergen").json()
    assert body["place"] == "Bergen" and [c["kind"] for c in body["search"]["understood"]] == ["protein", "diet"]
    assert body["links"]["remove"]["sted"] == "http://testserver/api/middager?q=kylling+melkefri"
    assert api.get("/api/middager?sted=gotham").json()["place"] is None  # an unknown place is every store
    body = api.get("/api/middager?q=melkefri&sted=bergen&sorter=kroner").json()  # an old link: `sorter` is ignored
    assert "order" not in body
    assert body["links"]["add"]["vegansk"] == "http://testserver/api/middager?q=melkefri+vegansk&sted=bergen"
    assert "- [Bergen](http://testserver/api/middager?sted=bergen)" in api.get("/llms.txt").text


def test_the_place_is_kept_in_the_browser_not_in_a_cookie() -> None:
    """«Sted» is remembered by the page's own script in localStorage (jb 2026-10-23: "local storage works for me"): no cookie is
    ever set, so pages stay cacheable by their address; the script and the select agree on the name; the address gets the place
    when the script searches with it, as when it is picked; and /om says what is kept."""
    s = snapshot(
        KYLLING,
        offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale", catalog="kiwi-vest")],
        matches={"kyllingfilet": ["sale"]},
        places={"Bergen": ["kiwi-vest"]},
    )
    site = TestClient(main.create_app(Queries(FakeDatasets(s), Household())))
    page = site.get("/")
    fragment = site.get("/middager?sted=bergen", headers={"HX-Request": "true"})
    assert "set-cookie" not in page.headers and "set-cookie" not in fragment.headers
    assert fragment.headers["hx-replace-url"] == "/?sted=bergen#forslag"
    assert 'name="sted"' in page.text and 'getItem("sted")' in page.text and 'removeItem("sted")' in page.text
    assert "Nettleseren din husker stedet du velger" in site.get("/om").text
