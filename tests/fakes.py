"""In-memory adapters for every output port, and builders for domain objects."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from core.dishes import dish
from core.errors import SourceUnavailableError
from core.models import (
    LABELS,
    Carbs,
    Fodmap,
    Gluten,
    Ingredient,
    Item,
    Kids,
    Lactose,
    Level,
    Offer,
    Onion,
    Pregnancy,
    Recipe,
    RecipeRef,
    Snapshot,
    Traits,
)


def traits(
    gluten: Gluten = Gluten.NO,
    onion: Onion = Onion.NONE,
    lactose: Lactose = Lactose.NONE,
    kids: Kids = Kids.OK,
    *,
    contains: Mapping[Item, Level] | None = None,
    fodmap: Fodmap | None = Fodmap.LOW,
    carbs: Carbs | None = Carbs.NONE,
    pregnancy: Pregnancy | None = Pregnancy.OK,
) -> Traits:
    """An ingredient with every label asked: it holds nothing, unless told otherwise."""
    return Traits(gluten, onion, lactose, kids, "", {item: Level.NO for item in Item} | dict(contains or {}), fodmap, carbs, pregnancy)


PLAIN = traits()


def ingredient(name: str, amount: float | None = None, unit: str = "", category: str = "/diverse") -> Ingredient:
    return Ingredient(name, f"{amount or ''} {unit} {name}".strip(), amount, unit, category)


def recipe(
    name: str,
    *ingredients: Ingredient,
    main: str = "Kylling og høns",
    portions: int = 4,
    prep_time: str = "20\u201340 min",
    rating: float | None = None,
    rating_count: int = 0,
) -> Recipe:
    return Recipe(
        url=f"https://www.matprat.no/oppskrifter/familien/{name.lower().replace(' ', '-')}/",
        name=name,
        dish_types=("Middagsrett",),
        main_categories=(main,) if main else (),
        portions=portions,
        prep_time=prep_time,
        rating=rating,
        rating_count=rating_count,
        ingredients=ingredients,
    )


def offer(
    heading: str,
    price: float = 50.0,
    *,
    store: str = "KIWI",
    per_kg: float | None = None,
    pre_price: float | None = None,
    id: str | None = None,
) -> Offer:
    return Offer(
        id=id or f"{store}:{heading}:{price}",
        store=store,
        heading=heading,
        description="",
        price=price,
        pre_price=pre_price,
        per_kg=per_kg,
        valid_until=date(2026, 10, 18),
    )


@dataclass
class FakeClassifier:
    """Answers from `known`, PLAIN for anything else, and records what was asked: (name, labels)."""

    known: Mapping[str, Traits] = field(default_factory=dict)
    asked: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    labels: tuple[str, ...] = LABELS

    async def classify(self, ingredient: Ingredient, labels: Iterable[str]) -> dict[str, str]:
        keys = tuple(labels)
        self.asked.append((ingredient.name, keys))
        levels = self.known.get(ingredient.name, PLAIN).levels()
        return {key: levels[key] for key in keys} | {"model": "fake"}


@dataclass
class FakeOffers:
    offers: list[Offer] = field(default_factory=list)

    async def current(self) -> list[Offer]:
        return list(self.offers)


@dataclass
class FakeMatcher:
    """An offer is the ingredient when its heading contains `matches[ingredient]`."""

    matches: Mapping[str, str] = field(default_factory=dict)
    asked: list[tuple[str, int]] = field(default_factory=list)

    async def rank(self, ingredient: str, offers: Sequence[Offer]) -> dict[str, float]:
        self.asked.append((ingredient, len(offers)))
        word = self.matches.get(ingredient)
        return {o.id: float(bool(word) and word in o.heading.lower()) for o in offers}


@dataclass
class FakeSource:
    pages: dict[str, Recipe | None] = field(default_factory=dict)
    lastmod: dict[str, str] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    fetched: list[str] = field(default_factory=list)

    async def index(self) -> list[RecipeRef]:
        return [RecipeRef(url, self.lastmod.get(url, "2026-10-01")) for url in self.pages]

    async def fetch(self, url: str) -> Recipe | None:
        self.fetched.append(url)
        if url in self.failing:
            raise SourceUnavailableError("fake", "down")
        return self.pages[url]


def snapshot(
    *recipes: Recipe,
    known: Mapping[str, Traits] | None = None,
    offers: Sequence[Offer] = (),
    matches: Mapping[str, Sequence[str]] | None = None,
) -> Snapshot:
    """A snapshot where every ingredient is PLAIN unless `known` says otherwise."""
    names = {i.name for r in recipes for i in r.ingredients}
    traits = {name: (known or {}).get(name, PLAIN) for name in names}
    return Snapshot(
        built=datetime(2026, 10, 13, 12, tzinfo=UTC),
        dishes=tuple(dish(r) for r in recipes),
        traits=traits,
        offers=tuple(offers),
        matches={name: tuple(ids) for name, ids in (matches or {}).items()},
    )


@dataclass
class FakeDatasets:
    data: Snapshot

    def snapshot(self) -> Snapshot:
        return self.data
