from pathlib import Path

import aiosqlite

from core.models import Gluten, Lactose, RecipeRef
from pipeline.store import (
    SCHEMA,
    Sqlite,
    SqliteOfferMatchStore,
    SqliteRecipeStore,
    SqliteTraitsStore,
)
from tests.fakes import ingredient, recipe, traits

DINNER = recipe("Kyllinggryte", ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns"))


async def test_recipes_round_trip(tmp_path: Path) -> None:
    async with Sqlite.open(tmp_path / "db" / "matris.sqlite3") as db:
        recipes = SqliteRecipeStore(db)
        empty = "https://www.matprat.no/oppskrifter/kos/ingen/"
        await recipes.save(RecipeRef(DINNER.url, "2026-10-01"), DINNER)
        await recipes.save(RecipeRef(empty, "2026-10-01"), None)
        assert await recipes.dinners() == [DINNER]
        assert await recipes.known() == {DINNER.url: "2026-10-01", empty: "2026-10-01"}

        await recipes.save(RecipeRef(DINNER.url, "2026-10-12"), DINNER)
        assert (await recipes.known())[DINNER.url] == "2026-10-12"


async def test_labels_round_trip(tmp_path: Path) -> None:
    async with Sqlite.open(tmp_path / "matris.sqlite3") as db:
        store = SqliteTraitsStore(db)
        flour = traits(gluten=Gluten.YES).levels()
        cream = traits(lactose=Lactose.SOME).levels()
        await store.save_many({"hvetemel": flour, "matfløte": cream})
        assert await store.get_many(["hvetemel", "matfløte", "ukjent"]) == {"hvetemel": flour, "matfløte": cream}
        await store.save_many({"hvetemel": {"egg": "no"}})  # a label added later; the others stay
        assert (await store.get_many(["hvetemel"]))["hvetemel"] == {**flour, "egg": "no"}


async def test_the_old_traits_table_is_copied_once(tmp_path: Path) -> None:
    path = tmp_path / "matris.sqlite3"
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS label")[0])
        await db.execute("INSERT INTO traits VALUES ('løk', 'no', 'onion', 'none', 'ok', 'jev-1.13.0', '2026-10-13')")
        await db.commit()
    async with Sqlite.open(path) as db:
        store = SqliteTraitsStore(db)
        old = {"gluten": "no", "onion": "onion", "lactose": "none", "kids": "ok", "model": "jev-1.13.0"}
        assert await store.get_many(["løk"]) == {"løk": old}
        await store.save_many({"løk": {"onion": "maybe"}})
    async with Sqlite.open(path) as db:  # opening again does not copy over the newer answer
        assert (await SqliteTraitsStore(db).get_many(["løk"]))["løk"]["onion"] == "maybe"


async def test_labels_lookup_handles_many_names(tmp_path: Path) -> None:
    async with Sqlite.open(tmp_path / "matris.sqlite3") as db:
        store = SqliteTraitsStore(db)
        many = {f"ingrediens {i}": traits().levels() for i in range(1_200)}
        await store.save_many(many)
        assert len(await store.get_many(many)) == 1_200


async def test_offer_matches_round_trip(tmp_path: Path) -> None:
    async with Sqlite.open(tmp_path / "matris.sqlite3") as db:
        store = SqliteOfferMatchStore(db)
        await store.save_many({("kyllingfilet", "kyllingbryst"): 0.9, ("egg", "kinderegg"): 0.0})
        found = await store.get_many([("kyllingfilet", "kyllingbryst"), ("egg", "egg")])
        assert found == {("kyllingfilet", "kyllingbryst"): 0.9}
