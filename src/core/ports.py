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

    async def classify(self, ingredient: Ingredient, labels: Iterable[str], dish: str = "") -> Levels:
        """These labels of the ingredient's name, and "source", the model that answered; its grocery category is
        context, and so is `dish`, a dinner it is in, for an ingredient without one."""
        ...


class DepartmentClassifier(Protocol):
    """Which grocery department an ingredient is filed under, for a source that names none (godt.no)."""

    async def department(self, ingredient: str, departments: Mapping[str, Sequence[str]], dish: str = "") -> str:
        """One of `departments`, each given with ingredient names filed there; `dish`, a dinner it is in, is context."""
        ...


class OfferMatcher(Protocol):
    """Which of these offers is this recipe ingredient?"""

    async def rank(self, ingredient: str, offers: Sequence[Offer], line: str = "", dish: str = "") -> Mapping[str, float]:
        """Per offer id, the probability that a cook can buy it as the ingredient: as the recipe writes it in `line`
        ("200 g tunfisk, av sushikvalitet") for the dinner `dish`, when given."""
        ...
