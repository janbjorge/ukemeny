"""Query-string validation shared by the pages and the JSON API, with pydantic v2.

Validation never fails: an unknown protein is ignored, numbers are capped, a long search is cut, so an
old or hand-edited link still shows a page.
"""

import secrets
from typing import Annotated
from urllib.parse import urlencode

from pydantic import BaseModel, BeforeValidator, ConfigDict

from core.matching import PROTEINS, VEGETARIAN
from core.search import Order, Tag, protein_word

KNOWN_PROTEINS = (*dict.fromkeys(PROTEINS.values()), "kjøtt", VEGETARIAN)
MAX_DINNERS = 100
DEFAULT_DINNERS = 30
MAX_SEARCH = 200
"""Characters; nobody types more for a dinner."""


def _protein(value: object) -> str | None:
    return value if isinstance(value, str) and value in KNOWN_PROTEINS else None


def _flag(value: object) -> bool:
    return str(value).lower() in {"1", "true", "ja", "on"}


def _count(value: object) -> int:
    digits = "".join(c for c in str(value) if c.isdigit())[:4]
    return min(max(int(digits), 1), MAX_DINNERS) if digits else DEFAULT_DINNERS


def _order(value: object) -> Order | None:
    return next((o for o in Order if o.value == value), None)


def _text(value: object) -> str:
    return " ".join(str(value).split())[:MAX_SEARCH]


class DinnerQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    q: Annotated[str, BeforeValidator(_text)] = ""
    """A search in plain bokmål (core.search)."""
    protein: Annotated[str | None, BeforeValidator(_protein)] = None
    tilbud: Annotated[bool, BeforeValidator(_flag)] = False
    antall: Annotated[int, BeforeValidator(_count)] = DEFAULT_DINNERS
    sted: Annotated[str, BeforeValidator(_text)] = ""
    """Where the offers are from: a place as Snapshot.places names it, in any case (Queries.place); empty for every store."""
    sorter: Annotated[Order | None, BeforeValidator(_order)] = None
    """The biggest discount first, as a share or in kroner, instead of the ranking."""

    @classmethod
    def of(cls, **given: str | None) -> DinnerQuery:
        """From query parameters, leaving out empty ones."""
        return cls.model_validate({k: v for k, v in given.items() if v})

    def text(self) -> str:
        """The whole search: `protein` and `tilbud` (older links, the API) are words in it too."""
        words = (self.q, protein_word(self.protein) if self.protein else "", Tag.ON_SALE.value if self.tilbud else "")
        return " ".join(w for w in words if w)


def link(text: str, antall: int | None = None, place: str | None = None, order: Order | None = None) -> str:
    """The query string for a search: "q=rask+kylling", with "sted" (lower case), "sorter" and "antall" only when given."""
    given = {"q": text, "sted": place and place.lower(), "sorter": order, "antall": antall}
    return urlencode({k: v for k, v in given.items() if v})


def seed(value: str | None) -> int | None:
    """The visit's draw of the week (`uke`, core.ranking.plan): the number given; None when missing or nonsense."""
    digits = "".join(c for c in str(value or "") if c.isdigit())[:9]
    return int(digits) if digits else None


def new_seed() -> int:
    """A new draw of the week: on a first visit, and for «Nye middager»."""
    return secrets.randbits(30)


def offset(value: str | None) -> int:
    """Where "Vis flere" starts: a count of dinners already shown, 0 when missing or nonsense."""
    digits = "".join(c for c in str(value or "") if c.isdigit())[:4]
    return int(digits) if digits else 0
