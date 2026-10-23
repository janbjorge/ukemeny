"""Output ports: what the core and the use cases need from the outside world."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Protocol

from core.models import Ingredient, Levels, Offer, Offers, Recipe, RecipeRef, Snapshot


class Datasets(Protocol):
    """What the site reads: the snapshot built offline (src/adapters/datasets.py)."""

    def snapshot(self) -> Snapshot: ...


# The offline build (src/app/build.py, wired in src/pipeline/datasets.py).


class RecipeSource(Protocol):
    """Where recipes come from: matprat.no and godt.no. Raises SourceUnavailableError."""

    async def index(self) -> Sequence[RecipeRef]:
        """Every recipe page the source lists, with when it last changed."""
        ...

    async def fetch(self, url: str) -> Recipe | None:
        """The recipe, or None if the page is gone or holds no recipe."""
        ...


class OfferSource(Protocol):
    """This week's grocery offers near each place: mattilbud.no's catalogs."""

    async def current(self) -> Offers:
        """Every offer valid today, and which catalogs reach each place. Raises SourceUnavailableError."""
        ...


# Classifiers. Each decision is its own port, so models can be swapped independently.
# Both raise ClassifierUnavailableError when they cannot answer.


class IngredientClassifier(Protocol):
    """What an ingredient holds: gluten, onion, lactose, allergens, meat, FODMAP and more (core.models.LABELS)."""

    @property
    def labels(self) -> Collection[str]:
        """Every label it can answer."""
        ...

    async def classify(self, ingredient: Ingredient, labels: Iterable[str]) -> Levels:
        """These labels of the ingredient's name, and "source", the model that answered; its category is context."""
        ...

    async def weigh(self, ingredient: Ingredient) -> float | None:
        """Grams per piece («1 stk») of the ingredient's name, the whole item as a recipe means by one piece; its category
        is context (Traits.piece_g, docs/plan-per-person.md). None when it cannot say."""
        ...


class CategoryClassifier(Protocol):
    """Which of our categories (core.matching.CATEGORIES) a new ingredient name belongs to, when neither its recipe line
    nor a name with the same words says (app.build.draft)."""

    async def category(self, ingredient: str, categories: Mapping[str, Sequence[str]]) -> str:
        """One of `categories`, each given with ingredient names filed there."""
        ...


class OfferMatcher(Protocol):
    """Which of these offers is this product?"""

    async def rank(self, product: str, offers: Sequence[Offer], form: str = "", dish: str = "") -> Mapping[str, float]:
        """Per offer id, the probability that a cook can buy it as the product (a name in the vocabulary, or what it
        stands for: Traits.product), in `form` (Part.form: "røkt", "hermetisk"; "" for what the name means) for the
        dinner `dish`, when given."""
        ...
