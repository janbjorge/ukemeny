from pathlib import Path

import orjson

from adapters.datasets import JsonDatasets, write
from core.models import Gluten, Ingredient
from tests.fakes import ingredient, offer, recipe, snapshot, traits


def test_snapshot_round_trip(tmp_path: Path) -> None:
    bacon = ingredient("bacon", 100, "g", "/kjøtt/svinekjøtt")
    bacon = Ingredient(bacon.name, "100 g røkt bacon", bacon.amount, bacon.unit, bacon.category)
    s = snapshot(
        recipe(
            "Kyllinggryte", ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns"), ingredient("hvetemel", 2, "ss", "/korn"), bacon
        ),
        known={"hvetemel": traits(gluten=Gluten.YES)},
        offers=[
            offer("KYLLINGBRYST", 99, pre_price=135, per_kg=141.0, id="a", catalog="kiwi-vest", size=700, unit="g"),
            offer("GÅRDSEGG", 80, pre_price=117, id="e", catalog="kiwi-vest", size=12, unit="stk", pieces=2),
            offer("FERSK PASTA", 40, pre_price=69.9, id="p", catalog="kiwi-vest", size=250, size_to=500, unit="g"),
        ],
        matches={"kyllingfilet": ["a"]},
        places={"Bergen": ["kiwi-vest", "rema"], "Stavanger": ["kiwi-vest"]},
    )
    assert s.served  # kyllingfilet is meat: matched per dinner
    assert s.dishes[0].parts[2].form == "røkt"
    sizes = write(s, tmp_path)
    assert set(sizes) == {"dishes.json", "traits.json", "offers.json"}
    assert JsonDatasets(tmp_path).snapshot() == s
    text = (tmp_path / "traits.json").read_text()
    assert text.endswith("}\n") and '\n  "hvetemel": {\n' in text  # Formatted like `jq .`


def test_a_dishes_file_from_before_the_pieces_reads_them_from_the_grams(tmp_path: Path) -> None:
    omelette = recipe(
        "Omelett",
        ingredient("egg", 2, "stk.", "/egg"),
        ingredient("hakkede tomater", 1, "boks", "/hermetikk"),
        ingredient("salat", 1, "pose", "/grønnsaker"),
        ingredient("melk", 1, "dl", "/melk/melkeprodukter"),
    )
    write(snapshot(omelette), tmp_path)
    path = tmp_path / "dishes.json"
    document = orjson.loads(path.read_bytes())
    for p in document[0]["parts"]:
        del p["pieces"]
    path.write_bytes(orjson.dumps(document))
    (read,) = JsonDatasets(tmp_path).snapshot().dishes
    assert [p.pieces for p in read.parts] == [0.5, 0.25, None, None]  # 50 g at 100 g a stk; 100 g at 400 g a boks; no pose in the table


def test_an_offers_file_from_before_the_amounts_reads_as_unknown(tmp_path: Path) -> None:
    s = snapshot(
        recipe("Kyllinggryte", ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")),
        offers=[offer("KYLLINGBRYST", 99, size=700, unit="g")],
    )
    write(s, tmp_path)
    path = tmp_path / "offers.json"
    document = orjson.loads(path.read_bytes())
    for o in document["offers"]:
        for key in ("size", "size_to", "unit", "pieces"):
            del o[key]
    path.write_bytes(orjson.dumps(document))
    (read,) = JsonDatasets(tmp_path).snapshot().offers
    assert (read.size, read.size_to, read.unit, read.pieces) == (None, None, "", 1)


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
