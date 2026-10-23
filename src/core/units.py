"""Amounts in one unit per kind, for the kroner a head (docs/plan-per-person.md): mass in g, volume in ml, pieces in stk,
and a recipe's container (a boks, a pk) as one pack of an offer. Every other word a source uses is turned into one of
these at the edge (core.dishes for a recipe line, pipeline.tjek for an offer) or into nothing; the arithmetic here never
sees a dl or a kg. Not kg and l: the recipes and the packs are whole numbers in g and ml, and dishes.json already holds
grams per portion (jb 2026-10-23: "we should just do all our calculations in grams or kilograms ... you do the
reserach")."""

from collections.abc import Mapping

MASS: Mapping[str, float] = {"g": 1.0, "kg": 1000.0}
"""A recipe's mass units in g."""
VOLUME: Mapping[str, float] = {"ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0, "liter": 1000.0, "ss": 15.0, "ts": 5.0}
"""A recipe's volume units in ml (the same numbers as core.diet.GRAMS_PER_UNIT, which counts a ml as a gram)."""
CONTAINERS = frozenset({"boks", "pk", "pakke", "beger", "pose", "glass"})
"""Recipe units that name a pack: «1 boks hakkede tomater» is one pack of the offer."""
PIECE = "stk"


def counted(unit: str) -> bool:
    """Whether a recipe line counts pieces (Part.pieces): any unit that is not a mass, a volume or nothing: stk, båt,
    skive, boks, bunt, potte, kvist."""
    return bool(unit) and unit not in MASS and unit not in VOLUME
