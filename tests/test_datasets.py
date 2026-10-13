from pathlib import Path

from adapters.datasets import JsonDatasets, write
from core.models import Gluten
from tests.fakes import ingredient, offer, recipe, snapshot, traits


def test_snapshot_round_trip(tmp_path: Path) -> None:
    s = snapshot(
        recipe("Kyllinggryte", ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns"), ingredient("hvetemel", 2, "ss", "/korn")),
        known={"hvetemel": traits(gluten=Gluten.YES)},
        offers=[offer("KYLLINGBRYST", 99, pre_price=135, per_kg=141.0, id="a", catalog="kiwi-vest")],
        matches={"kyllingfilet": ["a"]},
        places={"Bergen": ["kiwi-vest", "rema"], "Stavanger": ["kiwi-vest"]},
    )
    sizes = write(s, tmp_path)
    assert set(sizes) == {"dishes.json", "traits.json", "offers.json"}
    assert JsonDatasets(tmp_path).snapshot() == s
    text = (tmp_path / "traits.json").read_text()
    assert text.endswith("}\n") and '\n  "hvetemel": {\n' in text  # Formatted like `jq .`


def test_the_committed_snapshot_reads() -> None:
    s = JsonDatasets().snapshot()
    assert len(s.dishes) > 1000
    assert all(p.name in s.traits for d in s.dishes for p in d.parts)
    ids = {o.id for o in s.offers}
    assert all(set(found) <= ids for found in s.matches.values())
    # Every offer holds somewhere. Not every catalog near a place has offers: Tjek listed one for Coop Mega's «Høstmat»
    # and served none (2026-10-13)
    assert s.places and {o.catalog for o in s.offers} <= {c for near in s.places.values() for c in near}


def test_the_committed_snapshot_holds_no_recipe_text() -> None:
    text = Path(__file__).parent.parent.joinpath("datasets", "dishes.json").read_text()
    for key in ('"text"', '"amount"', '"ingredients"', '"steps"'):
        assert key not in text
