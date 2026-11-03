"""Query-string validation shared by the pages and the JSON API, with pydantic v2.

Validation never fails: an unknown protein is ignored, numbers are capped, a long search is cut, so an
old or hand-edited link still shows a page.
"""

import re
from typing import Annotated
from urllib.parse import urlencode

from pydantic import BaseModel, BeforeValidator, ConfigDict

from core.matching import PROTEINS, VEGETARIAN
from core.menu import Weight
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
    sted: Annotated[str, BeforeValidator(_text)] = ""
    """Where the offers are from: a place as Snapshot.places names it, in any case (Queries.place); empty for every store."""

    @classmethod
    def of(cls, **given: str | None) -> DinnerQuery:
        """From query parameters, leaving out empty ones."""
        return cls.model_validate({k: v for k, v in given.items() if v})

    def text(self) -> str:
        """The whole search: `protein` and `tilbud` (older links, the API) are words in it too."""
        words = (self.q, protein_word(self.protein) if self.protein else "", Tag.ON_SALE.value if self.tilbud else "")
        return " ".join(w for w in words if w)


def _weight(value: object) -> Weight:
    return Weight(str(value)) if value in set(Weight) else Weight.BALANCED


MAX_SWAPS = 30
"""«Bytt» pressed this often on one menu; more is a hand-made link."""
_KEY = re.compile(r"[0-9a-f]{8}")


def _swaps(value: object) -> tuple[str, ...]:
    """Dish keys (core.menu.dish_key) joined by "-"; anything else is dropped."""
    return tuple(k for k in str(value).split("-") if _KEY.fullmatch(k))[:MAX_SWAPS]


def _seed(value: object) -> int | None:
    digits = "".join(c for c in str(value) if c.isdigit())[:9]
    return int(digits) if digits else None


class MenuQuery(BaseModel):
    """The menu's query string (/menu). English names, unlike the front page's older `sted` (jb 2026-11-02: "lets keep
    english in the code")."""

    model_config = ConfigDict(frozen=True)

    q: Annotated[str, BeforeValidator(_text)] = ""
    place: Annotated[str, BeforeValidator(_text)] = ""
    """As DinnerQuery.sted."""
    weight: Annotated[Weight, BeforeValidator(_weight)] = Weight.BALANCED
    seed: Annotated[int | None, BeforeValidator(_seed)] = None
    """Varies the menu (core.menu.plan); none: the page draws one."""
    swap: Annotated[tuple[str, ...], BeforeValidator(_swaps)] = ()
    """The dinners «Bytt» was pressed on, in turn (core.menu.plan `swapped`)."""

    @classmethod
    def of(cls, **given: str | None) -> MenuQuery:
        """From query parameters, leaving out empty ones."""
        return cls.model_validate({k: v for k, v in given.items() if v})


def menu_link(text: str, place: str | None, weight: Weight, seed: int | None, swap: tuple[str, ...] = ()) -> str:
    """The menu's query string: "q=rask&place=bergen&weight=cheapest&seed=48213&swap=1f0c9a2e", the default weight left
    out."""
    given = {
        "q": text,
        "place": place and place.lower(),
        "weight": None if weight is Weight.BALANCED else weight.value,
        "seed": seed,
        "swap": "-".join(swap),
    }
    return urlencode({k: v for k, v in given.items() if v})


def link(text: str, antall: int | None = None, place: str | None = None) -> str:
    """The query string for a search: "q=rask+kylling", with "sted" (lower case) and "antall" only when given."""
    given = {"q": text, "sted": place and place.lower(), "antall": antall}
    return urlencode({k: v for k, v in given.items() if v})


def offset(value: str | None) -> int:
    """Where "Vis flere" starts: a count of dinners already shown, 0 when missing or nonsense."""
    digits = "".join(c for c in str(value or "") if c.isdigit())[:4]
    return int(digits) if digits else 0
