"""Query-string validation shared by the pages and the JSON API, with pydantic v2.

Validation never fails: an unknown protein is ignored, numbers are capped, so an old or
hand-edited link still shows a page.
"""

from typing import Annotated
from urllib.parse import urlencode

from pydantic import BaseModel, BeforeValidator, ConfigDict

from core.matching import PROTEINS, VEGETARIAN

KNOWN_PROTEINS = (*dict.fromkeys(PROTEINS.values()), "kjøtt", VEGETARIAN)
MAX_DINNERS = 100


def _protein(value: object) -> str | None:
    return value if isinstance(value, str) and value in KNOWN_PROTEINS else None


def _flag(value: object) -> bool:
    return str(value).lower() in {"1", "true", "ja", "on"}


def _count(value: object) -> int:
    digits = "".join(c for c in str(value) if c.isdigit())
    return min(max(int(digits), 1), MAX_DINNERS) if digits else 30


class DinnerQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    protein: Annotated[str | None, BeforeValidator(_protein)] = None
    tilbud: Annotated[bool, BeforeValidator(_flag)] = False
    antall: Annotated[int, BeforeValidator(_count)] = 30

    def query(self) -> str:
        """The shareable query string for these choices, without defaults."""
        parts = {"protein": self.protein, "tilbud": "1" if self.tilbud else None}
        return urlencode({k: v for k, v in parts.items() if v})
