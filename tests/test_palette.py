"""Every colour pair on the page meets its contrast target (jb 2026-10-13: "really poor contranst").

APCA (SAPC 0.0.98G, the WCAG 3 draft) for how text reads at its size, WCAG 2 as the floor. Colours are read
from app.css, so a change there is checked here.
"""

import re

import pytest

from adapters.web.main import HERE

CSS = (HERE / "static" / "app.css").read_text()
ROOT = dict(re.findall(r"--([\w-]+): (#[0-9a-f]{6})", CSS[CSS.index(":root") : CSS.index("}")]))
PROTEINS = {
    name: dict(re.findall(r"--([\w-]+): (#[0-9a-f]{6})", body)) for name, body in re.findall(r'\[data-protein="([^"]+)"\] \{([^}]*)\}', CSS)
}
WHITE = "#ffffff"
TEXT, LABEL, GLYPH, EDGE = 75, 75, 45, 15
"""APCA Lc: 14-17 px text and 14 px bold labels 75 (fluent reading), a star 45, a card edge 15."""


def rgb(hex_: str) -> tuple[float, ...]:
    return tuple(int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5))


def wcag(fg: str, bg: str) -> float:
    def lum(h: str) -> float:
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def apca(fg: str, bg: str) -> float:
    def y(h: str) -> float:
        r, g, b = (c**2.4 for c in rgb(h))
        v = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
        return v + (0.022 - v) ** 1.414 if v < 0.022 else v

    t, b = y(fg), y(bg)
    if b > t:
        s = (b**0.56 - t**0.57) * 1.14
        return 0.0 if s < 0.1 else (s - 0.027) * 100
    s = (b**0.65 - t**0.62) * 1.14
    return 0.0 if s > -0.1 else -(s + 0.027) * 100


def test_the_maths_matches_published_values() -> None:
    assert round(apca("#000000", WHITE), 2) == 106.04
    assert round(apca(WHITE, "#000000"), 2) == 107.88
    assert round(apca("#888888", WHITE), 2) == 63.06
    assert round(wcag("#777777", WHITE), 2) == 4.48


v = ROOT
PAIRS = [
    ("title on a card", v["text-primary"], v["surface-1"], TEXT),
    ("grey text on a card", v["text-muted"], v["surface-1"], TEXT),
    ("grey text on the page", v["text-muted"], v["surface-0"], TEXT),
    ("grey text on the search panel", v["text-muted"], v["surface-2"], TEXT),
    ("a link on the page", v["accent"], v["surface-0"], TEXT),
    ("a link on the search panel", v["accent"], v["surface-2"], TEXT),
    ("Bytt on a card", v["accent-strong"], v["surface-1"], LABEL),
    ("the current page in the menu", v["accent-strong"], v["accent-soft"], LABEL),
    ("a chosen chip", WHITE, v["accent"], LABEL),
    ("a chosen diet chip", WHITE, v["good"], LABEL),
    ("a discount", v["sale-ink"], v["sale"], LABEL),
    ("a marked word", v["text-primary"], v["mark"], TEXT),
    ("the star", v["star"], v["surface-1"], GLYPH),
    ("a card's edge on the page", v["hairline"], v["surface-0"], EDGE),
    ("a chip's edge on the search panel", v["hairline"], v["surface-2"], EDGE),
    *[(f"the {p} label", c["p-ink"], c["p-soft"], LABEL) for p, c in PROTEINS.items()],
    *[(f"a chosen {p} chip", WHITE, c["p"], LABEL) for p, c in PROTEINS.items()],
    *[(f"the {p} edge on the page", c["p"], v["surface-0"], GLYPH) for p, c in PROTEINS.items()],
]


@pytest.mark.parametrize(("what", "fg", "bg", "target"), PAIRS, ids=[p[0] for p in PAIRS])
def test_contrast(what: str, fg: str, bg: str, target: int) -> None:
    assert abs(apca(fg, bg)) >= target, f"{what}: Lc {apca(fg, bg):.1f} < {target}"
    if target >= LABEL:
        assert wcag(fg, bg) >= 4.5, f"{what}: WCAG {wcag(fg, bg):.2f}"


def test_every_protein_has_a_colour() -> None:
    from adapters.web.params import KNOWN_PROTEINS

    assert set(PROTEINS) == set(KNOWN_PROTEINS)
