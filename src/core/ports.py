"""Output ports: what the core and the use cases need from the outside world."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Protocol

from core.models import Ingredient, Levels, Offer, Recipe, RecipeRef, Snapshot


class Datasets(Protocol):
    """What the site reads: the snapshot built offline (src/adapters/datasets.py)."""

    def snapshot(self) -> Snapshot: ...


# The offline build (src/app/build.py, wired in src/pipeline/datasets.py).


class RecipeSource(Protocol):
    """Where recipes come from: matprat.no. Raises SourceUnavailableError."""

    async def index(self) -> Sequence[RecipeRef]:
        """Every recipe page the source lists, with when it last changed."""
        ...

    async def fetch(self, url: str) -> Recipe | None:
        """The recipe, or None if the page is gone or holds no recipe."""
        ...


class RecipeStore(Protocol):
    async def known(self) -> Mapping[str, str]:
        """lastmod per stored recipe URL, including pages that held no recipe."""
        ...

    async def save(self, ref: RecipeRef, recipe: Recipe | None) -> None: ...

    async def dinners(self) -> list[Recipe]: ...


class TraitsStore(Protocol):
    """Classified ingredients, per (name, label), so each label is asked about each name only once."""

    async def get_many(self, names: Iterable[str]) -> dict[str, dict[str, str]]:
        """The labels stored per name (core.models.Levels); a name with none is left out."""
        ...

    async def save_many(self, levels: Mapping[str, Levels]) -> None:
        """Add or replace these labels; others stored for the name stay."""
        ...


class OfferMatchStore(Protocol):
    """Earlier answers to "is this offer that ingredient?", by ingredient name and offer heading.
    Headings come back week after week, so each pair is asked once."""

    async def get_many(self, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], float]: ...

    async def save_many(self, answers: Mapping[tuple[str, str], float]) -> None: ...


class OfferSource(Protocol):
    """This week's grocery offers near home: mattilbud.no's catalogs."""

    async def current(self) -> list[Offer]:
        """Every offer valid today. Raises SourceUnavailableError."""
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
        """These labels of the ingredient's name, and "model"; its grocery category is context."""
        ...


class OfferMatcher(Protocol):
    """Which of these offers is this recipe ingredient?"""

    async def rank(self, ingredient: str, offers: Sequence[Offer]) -> Mapping[str, float]:
        """Per offer id, the probability that a cook can buy it as the ingredient."""
        ...
