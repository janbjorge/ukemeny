"""Logfire records what was asked and how it went, never who asked."""

from collections.abc import Mapping

import orjson
from fastapi.testclient import TestClient
from logfire.testing import CaptureLogfire, get_collected_metrics

from adapters.datasets import JsonDatasets
from adapters.web import main

client = TestClient(main.app)
VISITOR = "203.0.113.7"
FLY = {"Fly-Client-IP": VISITOR, "X-Forwarded-For": f"{VISITOR}, 66.241.124.233", "Fly-Region": "arn", "HX-Request": "true"}


def _spans(capfire: CaptureLogfire) -> list[tuple[str, Mapping[str, object]]]:
    """Each span's name and attributes. Lists come as JSON text."""
    return [(s["name"], s["attributes"]) for s in capfire.exporter.exported_spans_as_dict()]


def _named(capfire: CaptureLogfire, name: str) -> Mapping[str, object]:
    return next(attrs for n, attrs in _spans(capfire) if n == name)


def _root(capfire: CaptureLogfire, path: str) -> Mapping[str, object]:
    """The request span's attributes."""
    return next(attrs for _, attrs in _spans(capfire) if attrs.get("http.target") == path)


def test_spans_keep_the_query_and_the_edge_region_and_drop_the_visitors_address(capfire: CaptureLogfire) -> None:
    client.get("/middager?q=kylling", headers=FLY)
    attrs = _root(capfire, "/middager")
    assert attrs["http.url"] == "http://testserver/middager?q=kylling"
    assert attrs["http.request.header.fly_region"] == ("arn",)
    assert attrs["http.request.header.fly_client_ip"] == attrs["http.request.header.x_forwarded_for"] == ("[REDACTED]",)
    assert attrs["net.peer.ip"] == "x"  # the client address, "testclient" here
    assert VISITOR not in orjson.dumps([_spans(capfire), get_collected_metrics(capfire.metrics_reader)], default=str).decode()


def test_health_check_is_not_traced(capfire: CaptureLogfire) -> None:
    client.get("/helse")
    assert not [attrs for _, attrs in _spans(capfire) if attrs.get("http.target") == "/helse"]


def test_spans_record_where_the_visit_came_from(capfire: CaptureLogfire) -> None:
    headers = {"Referer": "https://example.org/some/thread/", "Sec-Fetch-Site": "cross-site"}
    client.get("/?utm_source=a&utm_medium=b&xclid=c", headers=headers)
    attrs = _root(capfire, "/")
    assert attrs["visit.referrer"] == "example.org"
    assert "some/thread" not in orjson.dumps(attrs, default=str).decode()
    assert attrs["visit.fetch_site"] == "cross-site"
    assert (attrs["visit.utm_source"], attrs["visit.utm_medium"], attrs["visit.click_id"]) == ("a", "b", "xclid")


def test_links_within_the_site_are_not_a_referrer(capfire: CaptureLogfire) -> None:
    client.get("/om", headers={"Referer": "http://testserver/", "Sec-Fetch-Site": "same-origin"})
    attrs = _root(capfire, "/om")
    assert "visit.referrer" not in attrs
    assert attrs["visit.fetch_site"] == "same-origin"


def test_a_search_says_what_it_understood_and_is_counted(capfire: CaptureLogfire) -> None:
    client.get("/api/middager?q=glutenfri+kyllign")
    search = _named(capfire, "search {text}")
    assert search["route"] == "/api/middager"
    assert orjson.loads(str(search["search.rules"])) == ["glutenfri"]
    assert orjson.loads(str(search["search.corrected"])) == ["kyllign → kylling"]
    assert search["search.total"] != 0
    metrics = {m["name"]: m["data"]["data_points"] for m in get_collected_metrics(capfire.metrics_reader)}
    assert [p["attributes"] for p in metrics["matris.searches"]] == [{"route": "/api/middager", "found": True}]
    assert [p["attributes"] for p in metrics["matris.search.rules"]] == [{"rule": "glutenfri", "route": "/api/middager"}]


def test_a_fragment_says_whether_it_was_kept(capfire: CaptureLogfire) -> None:
    for _ in range(2):
        client.get("/middager?q=laks+rask", headers={"HX-Request": "true", "HX-Trigger": "q"})
    assert [attrs["fragment.kept"] for _, attrs in _spans(capfire) if "fragment.kept" in attrs] == [False, True]


def test_head_is_marked(capfire: CaptureLogfire) -> None:
    client.head("/om")
    assert _root(capfire, "/om")["http.request.method_original"] == "HEAD"


def test_start_and_stop_are_logged(capfire: CaptureLogfire) -> None:
    with TestClient(main.app):
        pass
    assert _named(capfire, "ready")["dataset.dishes"] == len(JsonDatasets().snapshot().dishes)
    assert _named(capfire, "stopping after {uptime} s and {served} requests")
