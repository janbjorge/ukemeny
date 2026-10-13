"""Query-string validation shared by the pages and the JSON API, with pydantic v2.

Validation never fails: an unknown protein is ignored, numbers are capped, a long search is cut, so an
old or hand-edited link still shows a page.
"""

from typing import Annotated
from urllib.parse import urlencode

from pydantic import BaseModel, BeforeValidator, ConfigDict

from core.matching import PROTEINS, VEGETARIAN
from core.search import Tag, protein_word

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


def _text(value: object) -> str:
    return " ".join(str(value).split())[:MAX_SEARCH]


class DinnerQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    q: Annotated[str, BeforeValidator(_text)] = ""
    """A search in plain bokmål (core.search)."""
    protein: Annotated[str | None, BeforeValidator(_protein)] = None
    tilbud: Annotated[bool, BeforeValidator(_flag)] = False
    antall: Annotated[int, BeforeValidator(_count)] = DEFAULT_DINNERS

    @classmethod
    def of(cls, **given: str | None) -> DinnerQuery:
        """From query parameters, leaving out empty ones."""
        return cls.model_validate({k: v for k, v in given.items() if v})

    def text(self) -> str:
        """The whole search: `protein` and `tilbud` (older links, the API) are words in it too."""
        words = (self.q, protein_word(self.protein) if self.protein else "", Tag.ON_SALE.value if self.tilbud else "")
        return " ".join(w for w in words if w)


def link(text: str, antall: int | None = None) -> str:
    """The query string for a search, without defaults: "q=rask+kylling"."""
    return urlencode({k: v for k, v in {"q": text, "antall": antall}.items() if v and v != DEFAULT_DINNERS})
