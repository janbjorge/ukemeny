"""The domain's types. Frozen and slotted; nothing here does I/O."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

DINNER = "Middagsrett"
"""matprat.no's dish type for a main course."""


class Gluten(StrEnum):
    NO = "no"
    MAYBE = "maybe"
    """Some brands add wheat (stock cubes, sausages, spice mixes): check the label."""
    YES = "yes"


class Onion(StrEnum):
    NONE = "none"
    GARLIC = "garlic"
    MAYBE = "maybe"
    """Processed products that often contain onion powder: check the label."""
    ONION = "onion"


class Lactose(StrEnum):
    NONE = "none"
    TRACE = "trace"
    """Butter, aged hard cheese."""
    SOME = "some"
    """Cream, sour cream, cream cheese."""
    HIGH = "high"
    """Milk, yoghurt."""


class Kids(StrEnum):
    OK = "ok"
    SPICY = "spicy"
    CHOKING = "choking"
    """Whole nuts and similar."""


class Item(StrEnum):
    """Something an ingredient can hold, asked about one by one: the EU allergens besides gluten, and what
    vegetarians, vegans, pork-free and alcohol-free diets leave out (METHOD.md §1)."""

    MILK = "milk"
    EGG = "egg"
    FISH = "fish"
    CRUSTACEAN = "crustacean"
    MOLLUSC = "mollusc"
    TREE_NUT = "tree_nut"
    PEANUT = "peanut"
    SOY = "soy"
    SESAME = "sesame"
    CELERY = "celery"
    MUSTARD = "mustard"
    SULPHITE = "sulphite"
    LUPIN = "lupin"
    LEGUME = "legume"
    MEAT = "meat"
    """Meat or poultry, or made from them: kjøttkraft, gelatin, smult."""
    ANIMAL = "animal"
    """Anything of animal origin, honey included."""
    PORK = "pork"
    ALCOHOL = "alcohol"


class Level(StrEnum):
    NO = "no"
    MAYBE = "maybe"
    """Some brands add it (buljong, ferdigsauser): a rule that leaves the item out leaves this out too."""
    YES = "yes"


class Fodmap(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class Carbs(StrEnum):
    """Carbohydrate per 100 g as sold."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Pregnancy(StrEnum):
    """Mattilsynet's advice for pregnant women."""

    OK = "ok"
    LIMIT = "limit"
    AVOID = "avoid"


type Levels = Mapping[str, str]
"""An ingredient's labels as stored and written: level per label key ("gluten": "no", "egg": "maybe"),
and "model": the model that answered."""
LABELS = ("gluten", "onion", "lactose", "kids", *Item, "fodmap", "carbs", "pregnancy")
"""Every label key an ingredient is asked about."""


@dataclass(frozen=True, slots=True)
class Traits:
    """What an ingredient is, regardless of recipe. Each label is asked once per ingredient name."""

    gluten: Gluten
    onion: Onion
    lactose: Lactose
    kids: Kids
    model: str = ""
    contains: Mapping[Item, Level] = field(default_factory=dict, hash=False)
    """Per item, whether the ingredient holds it. An item not here was never asked about."""
    fodmap: Fodmap | None = None
    carbs: Carbs | None = None
    pregnancy: Pregnancy | None = None
    """None: never asked about."""

    @classmethod
    def of(cls, levels: Levels) -> Traits:
        return cls(
            gluten=Gluten(levels["gluten"]),
            onion=Onion(levels["onion"]),
            lactose=Lactose(levels["lactose"]),
            kids=Kids(levels["kids"]),
            model=levels.get("model", ""),
            contains={item: Level(levels[item]) for item in Item if item in levels},
            fodmap=Fodmap(levels["fodmap"]) if "fodmap" in levels else None,
            carbs=Carbs(levels["carbs"]) if "carbs" in levels else None,
            pregnancy=Pregnancy(levels["pregnancy"]) if "pregnancy" in levels else None,
        )

    def levels(self) -> dict[str, str]:
        optional = {"fodmap": self.fodmap, "carbs": self.carbs, "pregnancy": self.pregnancy}
        return {
            "gluten": self.gluten.value,
            "onion": self.onion.value,
            "lactose": self.lactose.value,
            "kids": self.kids.value,
            **{item.value: level.value for item, level in self.contains.items()},
            **{key: value.value for key, value in optional.items() if value is not None},
            "model": self.model,
        }


@dataclass(frozen=True, slots=True)
class Ingredient:
    name: str
    """The product itself, as matprat names it: "laksefilet"."""
    text: str
    """The full line: "800 g skinn- og beinfri laksefilet"."""
    amount: float | None
    unit: str
    """As written by matprat: "g", "dl", "stk.", "båt", or ""."""
    category: str
    """matprat's grocery category: "/fisk og sjømat", "/kjøtt/kylling/høns"."""


@dataclass(frozen=True, slots=True)
class Recipe:
    url: str
    name: str
    dish_types: tuple[str, ...]
    """matprat's dish types: "Middagsrett", "Dessert", "Tilbehør"."""
    main_categories: tuple[str, ...]
    """What the dish is built on: "Fisk og sjømat", "Kylling og høns", "Storfe"."""
    portions: int
    prep_time: str
    """matprat's bucket, such as "Under 20 min" or "Over 60 min"."""
    rating: float | None
    rating_count: int
    ingredients: tuple[Ingredient, ...]

    @property
    def is_dinner(self) -> bool:
        return DINNER in self.dish_types

    @property
    def main(self) -> str:
        return self.main_categories[0] if self.main_categories else ""


@dataclass(frozen=True, slots=True)
class Part:
    """An ingredient as the site keeps it: facts, no judgement. Every rule (lactose, onion, main
    protein, how much a discount counts) is worked out from these and the traits at runtime."""

    name: str
    category: str
    """matprat's grocery department: "/kjøtt/kylling/høns", "/melk/melkeprodukter"."""
    grams: float | None
    """Per portion, rounded to 5 g; None when matprat's unit has no weight ("en klype")."""
    unit: str
    """matprat's unit without the dot ("g", "dl", "stk"), so liquids can be told apart."""


@dataclass(frozen=True, slots=True)
class Dish:
    """A dinner as the site keeps it: facts from matprat, no rules (core.dishes.dish). The method and
    wording stay on matprat.no; the site links to it."""

    url: str
    name: str
    portions: int
    prep_time: str
    """matprat's bucket, such as "Under 20 min" or "Over 60 min"."""
    rating: float | None
    rating_count: int
    parts: tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class RecipeRef:
    """A recipe page listed by the source, before it is fetched."""

    url: str
    lastmod: str


@dataclass(frozen=True, slots=True)
class Offer:
    id: str
    store: str
    heading: str
    description: str
    price: float
    pre_price: float | None
    per_kg: float | None
    """NOK per kg when the catalog says or the pack size gives it."""
    valid_until: date

    @property
    def discount(self) -> float | None:
        if self.pre_price and self.pre_price > self.price:
            return (self.pre_price - self.price) / self.pre_price
        return None

    @property
    def saving(self) -> float | None:
        """Kroner off, as the catalog has it: the price before minus the price now."""
        return self.pre_price - self.price if self.pre_price and self.pre_price > self.price else None

    @property
    def unit_price(self) -> float:
        """For ranking offers of the same product: per kg when known."""
        return self.per_kg if self.per_kg is not None else self.price


class Rule(StrEnum):
    AVOID = "avoid"
    """Swap it out; skip the dish when it is built on it."""
    NOTE = "note"
    """Mention it, nothing more."""
    OK = "ok"


@dataclass(frozen=True, slots=True)
class Household:
    """What the household cannot eat. Read from profile.yaml; the defaults are ours."""

    onion: Rule = Rule.AVOID
    onion_substitute: str | None = None
    """An onion that is fine and stands in for onion in most dishes (ours: vårløk). With one,
    only dishes with onion in the name are skipped; without, also dishes with lots of onion."""
    gluten: Rule = Rule.AVOID
    garlic: Rule = Rule.NOTE
    lactose_g_per_portion: float | None = 3.0
    """Lactose per adult portion that is still fine. Above it, dairy gets a lactose-free
    swap. None: no limit."""
    swaps: bool = True
    """False: skip any recipe that needs a swap other than lactose-free dairy."""
    kid_notes: bool = True
    """Notes on chili heat and choking risks."""
    avoid: frozenset[Item] = frozenset()
    """Leave out any dinner with an ingredient that holds one of these, or may (Level.MAYBE)."""
    fodmap: bool = False
    """Leave out dinners with a high-FODMAP ingredient that no swap above takes care of."""
    carbs_g_per_portion: float | None = None
    """Leave out dinners with more carbohydrate per portion than this. None: no limit."""
    pregnant: bool = False
    """Leave out dinners with an ingredient Mattilsynet advises pregnant women against or to limit."""


class Problem(StrEnum):
    GLUTEN = "gluten"
    ONION = "onion"
    GARLIC = "garlic"
    LACTOSE = "lactose"
    KIDS = "kids"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Note:
    problem: Problem
    ingredient: str
    advice: str
    swap: str = ""
    """A swap in a few words, for a card: "glutenfri pasta", "vårløk for løk". Empty for a note."""


@dataclass(frozen=True, slots=True)
class Verdict:
    blocked: str | None
    """Why the recipe does not work for the household, or None."""
    swaps: tuple[Note, ...]
    """Changes needed to make the recipe fit."""
    warnings: tuple[Note, ...]
    """Things to check or keep in mind; the recipe fits as is."""
    lactose_g: float
    """Lactose per portion before swaps."""


@dataclass(frozen=True, slots=True)
class Buy:
    """An ingredient of a dinner that is on offer this week."""

    part: Part
    offers: tuple[Offer, ...]
    """Cheapest per kg first."""
    weight: float
    """How much a deal on it counts for the dinner (core.matching.weight)."""

    @property
    def best(self) -> Offer:
        return self.offers[0]

    @property
    def sale(self) -> Offer | None:
        """The offer with the biggest discount, if any is discounted."""
        discounted = [o for o in self.offers if o.discount]
        return max(discounted, key=lambda o: o.discount or 0.0) if discounted else None


MAIN_WEIGHT = 1.0
"""A main vegetable in a dish without meat or fish: from about 400 g."""


@dataclass(frozen=True, slots=True)
class Dinner:
    dish: Dish
    verdict: Verdict
    buys: tuple[Buy, ...]
    score: float
    """Rating and prep time; breaks ties after swaps and discounts."""
    protein: str = "vegetar"
    """The main protein's group: fisk, kylling, svin, ... (core.matching.main_protein)."""
    main: str = ""
    """The main protein ingredient ("kyllingfilet"), or "" for a dish without meat or fish."""

    @property
    def deal(self) -> Buy | None:
        """The discount the card shows: the most important ingredient with one (its `sale`)."""
        return next((b for b in self.buys if b.sale), None)

    @property
    def sale(self) -> float:
        """How much of the dinner is discounted: weight times discount, summed."""
        return sum(b.weight * (b.sale.discount or 0.0) for b in self.buys if b.sale)

    @property
    def on_sale(self) -> bool:
        """The main protein is discounted this week; without meat or fish, a main vegetable.
        Discounted bacon on the side does not make lutefisk a dinner on sale."""
        if self.main:
            return any(b.sale for b in self.buys if b.part.name == self.main)
        return any(b.sale for b in self.buys if b.weight >= MAIN_WEIGHT)


@dataclass(frozen=True, slots=True)
class Plan:
    dinners: tuple[Dinner, ...]
    offers: int
    stores: tuple[str, ...]
    considered: int
    """Dinner recipes looked at."""
    fitting: int
    """Of those, recipes that fit the household (possibly with swaps)."""
    on_sale: int
    """Of those, dinners with a main ingredient on sale."""


@dataclass(frozen=True, slots=True)
class RefreshReport:
    listed: int
    fetched: int
    failed: int
    dinners: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything the site needs, built offline with Jev (src/pipeline/datasets.py) and read
    at start-up. Nothing in it depends on the household."""

    built: datetime
    dishes: tuple[Dish, ...]
    """Every dinner on matprat.no."""
    traits: Mapping[str, Traits]
    """Per ingredient name."""
    offers: tuple[Offer, ...]
    """This week's grocery offers."""
    matches: Mapping[str, tuple[str, ...]]
    """Per ingredient name, the ids of the offers a cook can buy as it."""
