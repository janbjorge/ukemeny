from pathlib import Path

from core.models import Gluten, Lactose, RecipeRef
from pipeline.store import (
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


async def test_traits_round_trip(tmp_path: Path) -> None:
    async with Sqlite.open(tmp_path / "matris.sqlite3") as db:
        store = SqliteTraitsStore(db)
        flour = traits(gluten=Gluten.YES)
        cream = traits(lactose=Lactose.SOME)
        await store.save_many({"hvetemel": flour, "matfløte": cream})
        assert await store.get_many(["hvetemel", "matfløte", "ukjent"]) == {
            "hvetemel": flour,
            "matfløte": cream,
        }


async def test_traits_lookup_handles_many_names(tmp_path: Path) -> None:
    async with Sqlite.open(tmp_path / "matris.sqlite3") as db:
        store = SqliteTraitsStore(db)
        many = {f"ingrediens {i}": traits() for i in range(1_200)}
        await store.save_many(many)
        assert len(await store.get_many(many)) == 1_200


async def test_offer_matches_round_trip(tmp_path: Path) -> None:
    async with Sqlite.open(tmp_path / "matris.sqlite3") as db:
        store = SqliteOfferMatchStore(db)
        await store.save_many({("kyllingfilet", "kyllingbryst"): 0.9, ("egg", "kinderegg"): 0.0})
        found = await store.get_many([("kyllingfilet", "kyllingbryst"), ("egg", "egg")])
        assert found == {("kyllingfilet", "kyllingbryst"): 0.9}
