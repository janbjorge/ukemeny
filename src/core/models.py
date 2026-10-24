"""The domain's types. Frozen and slotted; nothing here does I/O."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

DINNER = "Middagsrett"
"""matprat.no's dish type for a main course; godt.no's «Middag» tag becomes it (src/pipeline/godt.py)."""


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
"""A row of the vocabulary as stored and written: a level per label key ("gluten": "no", "egg": "maybe"), and
"category", "product" and "source" (Traits)."""
LABELS = ("gluten", "onion", "lactose", "kids", *Item, "fodmap", "carbs", "pregnancy")
"""Every label key an ingredient is asked about."""
HAND = "hand"
"""Traits.source of a row written or fixed by hand."""


@dataclass(frozen=True, slots=True)
class Traits:
    """A row of the vocabulary, datasets/traits.json: what an ingredient name is, whatever the recipe. The rows are kept
    between builds and fixed by hand (docs/plan-model.md); a name without one gets a row drafted once."""

    gluten: Gluten
    onion: Onion
    lactose: Lactose
    kids: Kids
    source: str = ""
    """Who answered: HAND, or the Jev model that drafted the row."""
    contains: Mapping[Item, Level] = field(default_factory=dict, hash=False)
    """Per item, whether the ingredient holds it. An item not here was never asked about."""
    fodmap: Fodmap | None = None
    carbs: Carbs | None = None
    pregnancy: Pregnancy | None = None
    """None: never asked about."""
    category: str = ""
    """Our kind of ingredient (core.matching.CATEGORIES), which every Part with the name takes: "/kjøtt/kylling/høns"."""
    product: str = ""
    """What the name is in the shop, which the offers are matched to: "kyllingfilet" for "kyllingfilet i strimler".
    "" is the name itself."""

    @classmethod
    def of(cls, levels: Levels) -> Traits:
        return cls(
            gluten=Gluten(levels["gluten"]),
            onion=Onion(levels["onion"]),
            lactose=Lactose(levels["lactose"]),
            kids=Kids(levels["kids"]),
            source=levels.get("source", ""),
            contains={item: Level(levels[item]) for item in Item if item in levels},
            fodmap=Fodmap(levels["fodmap"]) if "fodmap" in levels else None,
            carbs=Carbs(levels["carbs"]) if "carbs" in levels else None,
            pregnancy=Pregnancy(levels["pregnancy"]) if "pregnancy" in levels else None,
            category=levels.get("category", ""),
            product=levels.get("product", ""),
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
            "category": self.category,
            "product": self.product,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class Ingredient:
    name: str
    """The product itself, as the source names it: "laksefilet"."""
    text: str
    """The full line: "800 g skinn- og beinfri laksefilet"."""
    amount: float | None
    unit: str
    """In matprat's words: "g", "dl", "stk.", "båt", or "" (godt.no's "fedd" is "båt")."""
    category: str
    """What the source files the line under, in our words (core.matching.CATEGORIES): matprat.no's shelf, "" from
    godt.no, which names none. The build files every ingredient by the vocabulary before a Dish is made
    (app.build.filed); the line's category only counts when a name is new (app.build.draft)."""


@dataclass(frozen=True, slots=True)
class Recipe:
    url: str
    name: str
    dish_types: tuple[str, ...]
    """matprat's dish types: "Middagsrett", "Dessert", "Tilbehør"; for godt.no "Middagsrett" or nothing."""
    main_categories: tuple[str, ...]
    """What the dish is built on: "Fisk og sjømat", "Kylling og høns", "Storfe" (godt.no: its primary tag, "Suppe")."""
    portions: int
    prep_time: str
    """matprat's bucket, such as "Under 20 min" or "Over 60 min"; godt.no's minutes are put in one."""
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
    form: str = ""
    """The form the recipe line asks for, one word of core.dishes.FORMS ("røkt", "hermetisk"), or "" for what the name
    means: told to the offer matcher, so a tin is no tuna for nigiri. The site does not read it."""


@dataclass(frozen=True, slots=True)
class Dish:
    """A dinner as the site keeps it: facts from matprat.no or godt.no, no rules (core.dishes.dish). The method and
    wording stay at the source; the site links to it."""

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
    catalog: str
    """The store's catalog it is in (mattilbud.no's id), which says where it holds (Snapshot.places)."""
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


class Fit(StrEnum):
    """How well an offer is an ingredient (core.ports.OfferMatcher)."""

    EXACT = "exact"
    """The kind the recipe names: «COOP KJØTTDEIG» for kjøttdeig."""
    NEAR = "near"
    """Another or a mixed kind a cook could use instead: «Kjøttdeig av storfe&svin» for kjøttdeig av svin."""


@dataclass(frozen=True, slots=True)
class Offers:
    """This week's offers, and the catalogs of the stores near each place."""

    offers: tuple[Offer, ...]
    places: Mapping[str, tuple[str, ...]]
    """Per place ("Bergen"), the catalogs (Offer.catalog) of the stores near it. A catalog can reach many places."""


class Rule(StrEnum):
    AVOID = "avoid"
    """Leave out any dish with it."""
    NOTE = "note"
    """Mention it, nothing more."""
    OK = "ok"


@dataclass(frozen=True, slots=True)
class Household:
    """What the household cannot eat. Read from profile.yaml; the defaults are ours."""

    onion: Rule = Rule.AVOID
    onion_ok: str | None = None
    """An onion that is fine (ours: vårløk): dishes with it are not left out for onion."""
    gluten: Rule = Rule.AVOID
    garlic: Rule = Rule.NOTE
    lactose_g_per_portion: float | None = 3.0
    """Lactose per adult portion that is still fine. Above it, the dish is left out. None: no limit."""
    kid_notes: bool = True
    """Notes on chili heat and choking risks."""
    avoid: frozenset[Item] = frozenset()
    """Leave out any dinner with an ingredient that holds one of these, or may (Level.MAYBE)."""
    fodmap: bool = False
    """Leave out dinners with a high-FODMAP ingredient that no rule above judges."""
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


@dataclass(frozen=True, slots=True)
class Verdict:
    blocked: str | None
    """Why the recipe does not work for the household, or None."""
    warnings: tuple[Note, ...]
    """Things to check or keep in mind; the recipe fits as is."""
    lactose_g: float
    """Lactose per portion."""


@dataclass(frozen=True, slots=True)
class Buy:
    """An ingredient of a dinner that is on offer this week."""

    part: Part
    offers: tuple[Offer, ...]
    """The offers that are the ingredient (Fit.EXACT), cheapest per kg first."""
    weight: float
    """How much a deal on it counts for the dinner (core.matching.weight)."""
    near: tuple[Offer, ...] = ()
    """The offers a cook could use instead (Fit.NEAR), cheapest per kg first."""

    @property
    def best(self) -> Offer:
        return (self.offers or self.near)[0]

    @property
    def sale(self) -> Offer | None:
        """The offer the dinner's saving counts: the cheapest among the exact offers on sale, or, with none, among the
        near ones; the first row on the card (jb 2026-10-24: "I would assume ppl. care about the end price, not how
        mutch is off"; the most kroner off counted Joker's 79,90 kr karbonader over SPAR's 50 kr)."""
        for offers in (self.offers, self.near):
            if discounted := [o for o in offers if o.saving]:
                return min(discounted, key=lambda o: (o.price, -(o.saving or 0.0), o.store))
        return None

    @property
    def sales(self) -> tuple[Offer, ...]:
        """Every offer on sale, the exact ones before the near ones, each the cheapest first, then store: what the card
        lists, `sale` first (jb 2026-10-24: "Show all"). One offer in many catalogs (Obs has one per store) is listed
        once, as `sale` when it is that one."""
        sale = self.sale
        kept: dict[tuple[str, str, float, float | None], Offer] = {}
        for o in (*self.offers, *self.near):
            if o.saving and ((key := (o.store, o.heading, o.price, o.pre_price)) not in kept or o == sale):
                kept[key] = o
        return tuple(sorted(kept.values(), key=lambda o: (o not in self.offers, o.price, -(o.saving or 0.0), o.store)))


MAIN_WEIGHT = 1.0
"""A main vegetable in a dish without meat or fish: from about 400 g."""


@dataclass(frozen=True, slots=True)
class Dinner:
    dish: Dish
    verdict: Verdict
    buys: tuple[Buy, ...]
    score: float
    """Rating and prep time; breaks ties after the kroner off."""
    protein: str = "vegetar"
    """The main protein's group: fisk, kylling, svin, ... (core.matching.main_protein)."""
    main: str = ""
    """The main protein ingredient ("kyllingfilet"), or "" for a dish without meat or fish."""

    @property
    def deal(self) -> Buy | None:
        """The discount the card shows: the most important ingredient with one (its `sale`)."""
        return next((b for b in self.buys if b.sale), None)

    @property
    def deals(self) -> tuple[Buy, ...]:
        """Every ingredient with a discount, most important first; two ingredients with the same offer count once."""
        seen: set[str] = set()
        found = []
        for b in self.buys:
            if b.sale and b.sale.id not in seen:
                seen.add(b.sale.id)
                found.append(b)
        return tuple(found)

    @property
    def saving(self) -> float:
        """Kroner off every discounted ingredient, as the catalogs have it (per pack, not per portion: jb 2026-10-22,
        "its a rabbit hole")."""
        return sum((b.sale.saving or 0.0) for b in self.deals if b.sale)

    @property
    def on_sale(self) -> bool:
        """The main protein is discounted this week; without meat or fish, a main vegetable.
        Discounted bacon on the side does not make lutefisk a dinner on sale."""
        if self.main:
            return any(b.sale for b in self.buys if b.part.name == self.main)
        return any(b.sale for b in self.buys if b.weight >= MAIN_WEIGHT)


@dataclass(frozen=True, slots=True)
class Tally:
    """The counts behind an answer: where the offers are from and how many, and how many dinners fit the rules."""

    place: str | None
    """Where the offers are from: the stores near this place, or (None) every store."""
    offers: int
    stores: tuple[str, ...]
    considered: int
    """Dinner recipes looked at."""
    fitting: int
    """Of those, dinners that fit the household and save enough to be shown (core.ranking.FLOOR_KR)."""
    on_sale: int
    """Of those, dinners with the main ingredient on sale (Dinner.on_sale)."""


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
    """Every dinner on matprat.no and godt.no."""
    traits: Mapping[str, Traits]
    """Per ingredient name."""
    offers: tuple[Offer, ...]
    """This week's grocery offers, from the stores near every place."""
    matches: Mapping[str, tuple[str, ...]]
    """Per ingredient name, the ids of the discounted offers a cook can buy as it; not meat, fish or shellfish
    (`served`)."""
    places: Mapping[str, tuple[str, ...]]
    """Per place, the catalogs (Offer.catalog) of the stores near it (Offers.places)."""
    served: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    """Per dinner (Dish.url), per meat, fish or shellfish ingredient, the ids of the discounted offers a cook can buy
    as it for that dinner (core.matching.per_dinner)."""
    near: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """As `matches`, the offers a cook could use instead (Fit.NEAR)."""
    near_served: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    """As `served`, the offers a cook could use instead (Fit.NEAR)."""
