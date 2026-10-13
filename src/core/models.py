"""The domain's types. Frozen and slotted; nothing here does I/O."""

from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class Traits:
    """What an ingredient is, regardless of recipe. Classified once per ingredient name."""

    gluten: Gluten
    onion: Onion
    lactose: Lactose
    kids: Kids
    model: str = ""


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
