"""In-memory adapters for every output port, and builders for domain objects."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from core.dishes import dish
from core.errors import SourceUnavailableError
from core.matching import per_dinner
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
    Offers,
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
    category: str = "",
    product: str = "",
    piece_g: float | None = None,
) -> Traits:
    """An ingredient with every label asked: it holds nothing, unless told otherwise."""
    return Traits(
        gluten,
        onion,
        lactose,
        kids,
        "",
        {item: Level.NO for item in Item} | dict(contains or {}),
        fodmap,
        carbs,
        pregnancy,
        category,
        product,
        piece_g,
    )


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
    catalog: str = "",
    per_kg: float | None = None,
    pre_price: float | None = None,
    id: str | None = None,
    description: str = "",
    size: float | None = None,
    size_to: float | None = None,
    unit: str = "",
    pieces: int = 1,
) -> Offer:
    """`catalog` defaults to the store's name: one catalog per chain. `size` in `unit` is what the price buys (400 g; 1 kg
    for goods priced by weight), `pieces` the packs a multi-buy prices."""
    return Offer(
        id=id or f"{store}:{heading}:{price}",
        store=store,
        catalog=catalog or store,
        heading=heading,
        description=description,
        price=price,
        pre_price=pre_price,
        per_kg=per_kg,
        valid_until=date(2026, 10, 18),
        size=size,
        size_to=size_to,
        unit=unit,
        pieces=pieces,
    )


SIDE = ingredient("potet", 200, "g", "/poteter")
"""A side on sale (SIDE_OFFER, 25 kr off; SIDE_MATCH): the site only shows dinners that save core.ranking.FLOOR_KR
(app.queries), and 50 g per portion is too little to make a dinner without meat or fish «på tilbud»."""
SIDE_OFFER = offer("POTETER", 20, pre_price=45, id="potet", size=1000, size_to=2000, unit="g")
"""A bag of 1 to 2 kg: a line through it is indirect pricing, the midpoint (core.units)."""
SIDE_MATCH = {"potet": ["potet"]}


@dataclass
class FakeClassifier:
    """Answers from `known`, PLAIN for anything else, and records what was asked: (name, labels), and per name the
    category it came with."""

    known: Mapping[str, Traits] = field(default_factory=dict)
    asked: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    labels: tuple[str, ...] = LABELS
    context: dict[str, str] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=dict)
    """Grams per piece per name, for `weigh`; a name not here gets None."""
    weighed: list[str] = field(default_factory=list)

    async def classify(self, ingredient: Ingredient, labels: Iterable[str]) -> dict[str, str | float]:
        keys = tuple(labels)
        self.asked.append((ingredient.name, keys))
        self.context[ingredient.name] = ingredient.category
        levels = self.known.get(ingredient.name, PLAIN).levels()
        return {key: levels[key] for key in keys} | {"source": "fake"}

    async def weigh(self, ingredient: Ingredient) -> float | None:
        self.weighed.append(ingredient.name)
        self.context[ingredient.name] = ingredient.category
        return self.weights.get(ingredient.name)


@dataclass
class FakeCategories:
    """Files a name under `known[name]`, or else the first category offered, and records what was asked: (name,
    categories)."""

    known: Mapping[str, str] = field(default_factory=dict)
    asked: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    async def category(self, ingredient: str, categories: Mapping[str, Sequence[str]]) -> str:
        self.asked.append((ingredient, tuple(categories)))
        return self.known.get(ingredient, next(iter(categories)))


@dataclass
class FakeOffers:
    offers: list[Offer] = field(default_factory=list)
    places: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    async def current(self) -> Offers:
        return Offers(tuple(self.offers), dict(self.places))


@dataclass
class FakeMatcher:
    """An offer is the product when its heading contains `matches[product]`, unless the dinner wants another form:
    `wrong` names a word in an offer's description that rules it out for a dinner, as a tin for nigiri."""

    matches: Mapping[str, str] = field(default_factory=dict)
    wrong: Mapping[str, str] = field(default_factory=dict)
    """Per dinner, a word in an offer's description that rules it out there: {"Nigiri": "boks"}."""
    asked: list[tuple[str, int, str, str]] = field(default_factory=list)
    """(product, offers, form, dinner) per request."""

    async def rank(self, product: str, offers: Sequence[Offer], form: str = "", dish: str = "") -> dict[str, float]:
        self.asked.append((product, len(offers), form, dish))
        word, bad = self.matches.get(product), self.wrong.get(dish)
        return {o.id: float(bool(word and word in o.heading.lower() and not (bad and bad in o.description))) for o in offers}


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
    places: Mapping[str, Sequence[str]] | None = None,
) -> Snapshot:
    """A snapshot where every ingredient is PLAIN unless `known` says otherwise. `matches`: per ingredient name, filed
    as the build does: meat, fish and shellfish under every dinner with it (Snapshot.served). `places`: per place, its
    catalogs."""
    names = {i.name for r in recipes for i in r.ingredients}
    traits = {name: (known or {}).get(name, PLAIN) for name in names}
    dishes = tuple(dish(r) for r in recipes)
    found = {name: tuple(ids) for name, ids in (matches or {}).items()}
    served: dict[str, dict[str, tuple[str, ...]]] = {}
    for d in dishes:
        for p in d.parts:
            if per_dinner(p) and p.name in found:
                served.setdefault(d.url, {})[p.name] = found[p.name]
    return Snapshot(
        built=datetime(2026, 10, 13, 12, tzinfo=UTC),
        dishes=dishes,
        traits=traits,
        offers=tuple(offers),
        matches=found,
        places={place: tuple(ids) for place, ids in (places or {}).items()},
        served=served,
    )


@dataclass
class FakeDatasets:
    data: Snapshot

    def snapshot(self) -> Snapshot:
        return self.data
