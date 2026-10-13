from pathlib import Path

import pytest

from adapters import profile
from core.models import Household, Rule
from core.ranking import Week


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(text)
    return path


def test_template_is_our_household() -> None:
    p = profile.load(profile.TEMPLATE)
    assert p.household == Household(
        onion=Rule.AVOID,
        onion_substitute="vårløk",
        gluten=Rule.AVOID,
        garlic=Rule.NOTE,
        lactose_g_per_portion=3.0,
        swaps=True,
        kid_notes=True,
    )
    assert p.week == Week(days=5, fish=2, on_sale_only=True)
    assert p.place == "Stavanger"


def test_the_profile_in_the_repo_is_the_template() -> None:
    assert profile.PROFILE.read_text() == profile.TEMPLATE.read_text()


def test_defaults_and_overrides(tmp_path: Path) -> None:
    p = profile.load(
        write(
            tmp_path,
            """
diet:
  garlic: avoid
  lactose:
small_kids: false
week: {dinners: 7, on_sale_only: false}
""",
        )
    )
    h = p.household
    assert (h.onion, h.onion_substitute, h.garlic, h.lactose_g_per_portion, h.kid_notes) == (Rule.AVOID, None, Rule.AVOID, None, False)
    assert p.week == Week(days=7, fish=2, on_sale_only=False)
    assert p.place is None  # every store


def test_missing_profile_says_how_to_make_one(tmp_path: Path) -> None:
    with pytest.raises(profile.ProfileError, match="matris profile"):
        profile.load(tmp_path / "profile.yaml")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("diet: {onions: avoid}", "diet.onions"),
        ("diet: {onion: never}", "diet.onion"),
        ("shopping: {lat: 1, lng: 1}", "shopping"),
        ("place: [", "not valid YAML"),
    ],
)
def test_mistakes_get_clear_errors(tmp_path: Path, text: str, problem: str) -> None:
    with pytest.raises(profile.ProfileError, match=problem):
        profile.load(write(tmp_path, text))
