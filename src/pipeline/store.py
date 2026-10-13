"""SQLite caches for the offline build: recipes, Jev's ingredient traits and offer matches. One file, no server.

Recipes are stored as JSON, since they are only ever read whole. Pages that held no recipe
are stored too (data NULL), so a refresh does not fetch them again until they change.
"""

import asyncio
import dataclasses
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import aiosqlite
import orjson

from adapters.datasets import recipe_from_dict
from core.models import (
    Gluten,
    Kids,
    Lactose,
    Onion,
    Recipe,
    RecipeRef,
    Traits,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe (
    url TEXT PRIMARY KEY,
    lastmod TEXT NOT NULL,
    dinner INTEGER NOT NULL,
    data TEXT  -- JSON; NULL when the page held no recipe
);
CREATE TABLE IF NOT EXISTS offer_match (
    ingredient TEXT NOT NULL,
    heading TEXT NOT NULL,  -- normalized offer heading
    probability REAL NOT NULL,
    asked_at TEXT NOT NULL,
    PRIMARY KEY (ingredient, heading)
);
CREATE TABLE IF NOT EXISTS traits (
    name TEXT PRIMARY KEY,
    gluten TEXT NOT NULL,
    onion TEXT NOT NULL,
    lactose TEXT NOT NULL,
    kids TEXT NOT NULL,
    model TEXT NOT NULL,
    classified_at TEXT NOT NULL
);
"""

_CHUNK = 500
"""Names per IN (...) query, well under SQLite's limit on bound parameters."""


@dataclass
class Sqlite:
    db: aiosqlite.Connection
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    @asynccontextmanager
    async def open(cls, path: Path) -> AsyncGenerator[Self]:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(SCHEMA)
            await db.commit()
            yield cls(db)


def recipe_to_json(recipe: Recipe) -> str:
    return orjson.dumps(dataclasses.asdict(recipe)).decode()


def recipe_from_json(text: str) -> Recipe:
    return recipe_from_dict(orjson.loads(text))


@dataclass
class SqliteRecipeStore:
    """Implements core.ports.RecipeStore."""

    sqlite: Sqlite

    async def known(self) -> dict[str, str]:
        async with self.sqlite.db.execute("SELECT url, lastmod FROM recipe") as rows:
            return {url: lastmod async for url, lastmod in rows}

    async def save(self, ref: RecipeRef, recipe: Recipe | None) -> None:
        async with self.sqlite.lock:
            await self.sqlite.db.execute(
                "INSERT INTO recipe (url, lastmod, dinner, data) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (url) DO UPDATE SET lastmod = excluded.lastmod, "
                "dinner = excluded.dinner, data = excluded.data",
                (
                    ref.url,
                    ref.lastmod,
                    bool(recipe and recipe.is_dinner),
                    recipe_to_json(recipe) if recipe else None,
                ),
            )
            await self.sqlite.db.commit()

    async def dinners(self) -> list[Recipe]:
        async with self.sqlite.db.execute("SELECT data FROM recipe WHERE dinner AND data IS NOT NULL ORDER BY url") as rows:
            return [recipe_from_json(data) async for (data,) in rows]


@dataclass
class SqliteTraitsStore:
    """Implements core.ports.TraitsStore."""

    sqlite: Sqlite

    async def get_many(self, names: Iterable[str]) -> dict[str, Traits]:
        wanted = list(dict.fromkeys(names))
        found: dict[str, Traits] = {}
        for start in range(0, len(wanted), _CHUNK):
            chunk = wanted[start : start + _CHUNK]
            async with self.sqlite.db.execute(
                f"SELECT name, gluten, onion, lactose, kids, model FROM traits WHERE name IN ({', '.join('?' * len(chunk))})",
                chunk,
            ) as rows:
                async for name, gluten, onion, lactose, kids, model in rows:
                    found[name] = Traits(Gluten(gluten), Onion(onion), Lactose(lactose), Kids(kids), model)
        return found

    async def save_many(self, traits: Mapping[str, Traits]) -> None:
        now = datetime.now(UTC).isoformat()
        async with self.sqlite.lock:
            await self.sqlite.db.executemany(
                "INSERT OR REPLACE INTO traits (name, gluten, onion, lactose, kids, model, classified_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(name, t.gluten, t.onion, t.lactose, t.kids, t.model, now) for name, t in traits.items()],
            )
            await self.sqlite.db.commit()


@dataclass
class SqliteOfferMatchStore:
    """Implements core.ports.OfferMatchStore."""

    sqlite: Sqlite

    async def get_many(self, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], float]:
        wanted = set(pairs)
        names = sorted({name for name, _ in wanted})
        found: dict[tuple[str, str], float] = {}
        for start in range(0, len(names), _CHUNK):
            chunk = names[start : start + _CHUNK]
            async with self.sqlite.db.execute(
                f"SELECT ingredient, heading, probability FROM offer_match WHERE ingredient IN ({', '.join('?' * len(chunk))})",
                chunk,
            ) as rows:
                async for name, heading, probability in rows:
                    if (name, heading) in wanted:
                        found[name, heading] = probability
        return found

    async def save_many(self, answers: Mapping[tuple[str, str], float]) -> None:
        now = datetime.now(UTC).isoformat()
        async with self.sqlite.lock:
            await self.sqlite.db.executemany(
                "INSERT OR REPLACE INTO offer_match (ingredient, heading, probability, asked_at) VALUES (?, ?, ?, ?)",
                [(name, heading, p, now) for (name, heading), p in answers.items()],
            )
            await self.sqlite.db.commit()
