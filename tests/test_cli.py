import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from adapters import cli, profile
from app.queries import Queries
from core.models import Household, Onion
from core.ranking import Week
from tests.fakes import FakeDatasets, ingredient, offer, recipe, snapshot, traits

CHICKEN = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
ONION = ingredient("løk", 1, "stk.", "/grønnsaker")
KYLLING = recipe("Kyllinggryte", CHICKEN, ONION)
runner = CliRunner()


@pytest.fixture(autouse=True)
def fixture_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    s = snapshot(
        KYLLING,
        known={"løk": traits(onion=Onion.ONION)},
        offers=[offer("KYLLINGBRYST", 99, pre_price=135, id="sale")],
        matches={"kyllingfilet": ["sale"]},
    )
    q = Queries(FakeDatasets(s), Household(onion_substitute="vårløk"), Week(days=1, fish=0))
    monkeypatch.setattr(cli, "queries", lambda as_json: q)


def test_plan_json_is_one_document() -> None:
    r = runner.invoke(cli.app, ["plan", "--json"])
    assert r.exit_code == 0
    body = json.loads(r.stdout)
    assert body["dinners"][0]["swaps"] == [{"ingredient": "løk", "problem": "onion", "advice": "bruk vårløk i stedet"}]
    assert body["dinners"][0]["discounts"][0]["discount_percent"] == 27


def test_plan_text_is_bokmal() -> None:
    out = runner.invoke(cli.app, ["plan"]).stdout
    assert "1 av 1 middager passer" in out and "bytt: løk: bruk vårløk i stedet" in out and "på tilbud: kyllingfilet -27%" in out


def test_candidates_and_check_json() -> None:
    body = json.loads(runner.invoke(cli.app, ["candidates", "--json", "--on-sale"]).stdout)
    assert [d["name"] for d in body["dinners"]] == ["Kyllinggryte"]
    body = json.loads(runner.invoke(cli.app, ["check", KYLLING.url, "--json"]).stdout)
    assert body["fits"] is True and body["recipe"]["url"] == KYLLING.url
    assert "ingredients" not in body["recipe"]  # The recipe stays on matprat.no


def test_candidates_search_without_quotes() -> None:
    out = runner.invoke(cli.app, ["candidates", "kyllign", "på", "tilbud"]).stdout
    assert "Søker etter: Kylling · På tilbud" in out and "Fant ikke «kyllign», så søker etter «kylling»." in out
    assert "1 middag passer" in out and "1. Kyllinggryte" in out
    body = json.loads(runner.invoke(cli.app, ["candidates", "fisk", "--json"]).stdout)
    assert body["dinners"] == [] and body["search"]["without"][0]["text"] == "fisk"
    out = runner.invoke(cli.app, ["candidates", "kylling", "uten", "kylling"]).stdout
    assert "Ingen middager passer alt dette. Prøv å fjerne" in out


def test_errors_are_json_in_json_mode() -> None:
    r = runner.invoke(cli.app, ["check", "https://www.matprat.no/oppskrifter/kos/nei/", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.stdout) == {
        "error": {"kind": "not_found", "message": "Fant ingen middag på https://www.matprat.no/oppskrifter/kos/nei/"}
    }


def test_missing_profile_is_a_setup_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(profile, "PROFILE", tmp_path / "profile.yaml")
    r = runner.invoke(cli.app, ["plan", "--json"])
    assert r.exit_code == 1 and json.loads(r.stdout)["error"]["kind"] == "setup"
