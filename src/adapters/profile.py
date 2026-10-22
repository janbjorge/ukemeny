"""profile.yaml: what the household cannot eat and where it shops.

Validated with pydantic, so a typo gets a clear error. Only the CLI reads it.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.models import Household, Rule

PROFILE = Path(__file__).parents[2] / "profile.yaml"
TEMPLATE = Path(__file__).with_name("profile.example.yaml")


class ProfileError(Exception):
    """profile.yaml is missing or wrong. The message says how to fix it."""


class _Diet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    onion: Rule = Rule.AVOID
    onion_ok: str | None = None
    gluten: Rule = Rule.AVOID
    garlic: Rule = Rule.NOTE
    lactose: float | None = Field(default=3.0, ge=0)


class _Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diet: _Diet = _Diet()
    small_kids: bool = False
    place: str | None = None


@dataclass(frozen=True, slots=True)
class Profile:
    household: Household
    place: str | None
    """Where the household shops: the offers are from the stores near it. None: every store."""


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
    diet = p.diet
    return Profile(
        household=Household(
            onion=diet.onion,
            onion_ok=diet.onion_ok or None,
            gluten=diet.gluten,
            garlic=diet.garlic,
            lactose_g_per_portion=diet.lactose,
            kid_notes=p.small_kids,
        ),
        place=p.place or None,
    )
