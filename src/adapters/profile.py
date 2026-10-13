"""profile.yaml: what the household cannot eat, where it shops, and what a week looks like.

Validated with pydantic, so a typo gets a clear error. The site, the CLI and the offline build read it.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.models import Household, Rule
from core.ranking import Week

PROFILE = Path(__file__).parents[2] / "profile.yaml"
TEMPLATE = Path(__file__).with_name("profile.example.yaml")

GROCERS = (
    "Bunnpris",
    "Coop Extra",
    "Coop Marked",
    "Coop Mega",
    "Coop Prix",
    "Europris",
    "Extra",
    "Joker",
    "KIWI",
    "Matkroken",
    "MENY",
    "Obs",
    "REMA 1000",
    "SPAR",
)
"""Grocery chains on mattilbud.no. The same area also has furniture, hardware and electronics
catalogs; "Spar Kjøp" is building supplies, not SPAR."""


class ProfileError(Exception):
    """profile.yaml is missing or wrong. The message says how to fix it."""


class _Diet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    onion: Rule = Rule.AVOID
    onion_substitute: str | None = None
    gluten: Rule = Rule.AVOID
    garlic: Rule = Rule.NOTE
    lactose: float | None = Field(default=3.0, ge=0)
    swaps: bool = True


class _Shopping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    near: str = ""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=15, gt=0, le=100)
    stores: list[str] = list(GROCERS)


class _Week(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dinners: int = Field(default=5, ge=1, le=14)
    fish: int = Field(default=2, ge=0)
    on_sale_only: bool = True


class _Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diet: _Diet = _Diet()
    small_kids: bool = False
    shopping: _Shopping
    week: _Week = _Week()


@dataclass(frozen=True, slots=True)
class Shopping:
    near: str
    lat: float
    lng: float
    radius_km: float
    stores: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Profile:
    household: Household
    week: Week
    shopping: Shopping


def load(path: Path = PROFILE) -> Profile:
    if not path.exists():
        raise ProfileError(f"No profile at {path}. Run `matris profile` to create one.")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ProfileError(f"{path} is not valid YAML: {e}") from None
    try:
        p = _Profile.model_validate(raw or {})
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'file'}: {err['msg']}" for err in e.errors())
        raise ProfileError(f"{path}: {problems}") from None
    if unknown := set(p.shopping.stores) - set(GROCERS):
        raise ProfileError(f"{path}: shopping.stores: unknown {', '.join(sorted(unknown))}; known are {', '.join(GROCERS)}")
    diet = p.diet
    return Profile(
        household=Household(
            onion=diet.onion,
            onion_substitute=diet.onion_substitute or None,
            gluten=diet.gluten,
            garlic=diet.garlic,
            lactose_g_per_portion=diet.lactose,
            swaps=diet.swaps,
            kid_notes=p.small_kids,
        ),
        week=Week(days=p.week.dinners, fish=p.week.fish, on_sale_only=p.week.on_sale_only),
        shopping=Shopping(p.shopping.near, p.shopping.lat, p.shopping.lng, p.shopping.radius_km, tuple(p.shopping.stores)),
    )
