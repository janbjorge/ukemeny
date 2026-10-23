"""Amounts in one unit per kind, for the kroner a head (docs/plan-per-person.md): mass in g, volume in ml, pieces in stk,
and a recipe's container (a boks, a pk) as one pack of an offer. Every other word a source uses is turned into one of
these at the edge (core.dishes for a recipe line, pipeline.tjek for an offer) or into nothing; the arithmetic here never
sees a dl or a kg. Not kg and l: the recipes and the packs are whole numbers in g and ml, and dishes.json already holds
grams per portion (jb 2026-10-23: "we should just do all our calculations in grams or kilograms ... you do the
reserach").

One formula: kroner a head = the saving, divided by what the price buys, times what the recipe wants a head, with both
amounts in the same unit. When they are in the same unit to begin with that is direct pricing, straight math from what
both sides say; a bridge (a piece weight, a gram a ml) or an estimate (the midpoint of a size range) makes it indirect
(core.models.Pricing)."""

import math
import re
from collections.abc import Iterable, Mapping
from statistics import median

from core.models import Dish, Offer, Part, Pricing

MASS: Mapping[str, float] = {"g": 1.0, "kg": 1000.0}
"""A recipe's mass units in g."""
VOLUME: Mapping[str, float] = {"ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0, "liter": 1000.0, "ss": 15.0, "ts": 5.0}
"""A recipe's volume units in ml (the same numbers as core.diet.GRAMS_PER_UNIT, which counts a ml as a gram)."""
CONTAINERS = frozenset({"boks", "pk", "pakke", "beger", "pose", "glass"})
"""Recipe units that name a pack: «1 boks hakkede tomater» is one pack of the offer."""
PIECE = "stk"
PACK = "pk"
"""The unit of a container line and of the packs an offer's price buys."""

type Amount = tuple[float, str]
"""(how much, unit): g, ml, stk or pk."""

CAP: Mapping[str, float] = {"g": 1000.0, "ml": 1000.0, PIECE: 20.0, PACK: 5.0}
"""A head, more than this is no portion: a batch recipe for «1 portion» (a kilo of kjøttdeig for pølser), or a wrong piece
weight. No figure rather than a number."""

MOST_LOTS = 10
MOST_WEIGHED = 10_000.0
"""For the whole recipe, more than ten lots of a pack, or ten kilos or litres of goods priced by weight, is no dinner's
shopping: the offer is not the product the recipe means (a whole turkey against a 110 g pack of fillet, a stew against a
stew mix), or a piece weight is wrong. Then the catalog's saving counts once, as the card had it before."""

_OFFER_UNITS: Mapping[str, tuple[float, str]] = {
    "kg": (1000.0, "g"),
    "l": (1000.0, "ml"),
    "g": (1.0, "g"),
    "ml": (1.0, "ml"),
    PIECE: (1.0, PIECE),
}
"""Offer.unit in g, ml or stk: the factor and the unit."""


def counted(unit: str) -> bool:
    """Whether a recipe line counts pieces (Part.pieces): any unit that is not a mass, a volume or nothing: stk, båt,
    skive, boks, bunt, potte, kvist."""
    return bool(unit) and unit not in MASS and unit not in VOLUME


_STATED = re.compile(r"ca\.?\s*(\d+(?:[,.]\d+)?)\s*(g|kg)\b")


def stated_weight(name: str) -> float | None:
    """Grams per piece a name carries itself: «kylling (ca. 1500 g)», «kalkun, ca. 5 kg». None otherwise."""
    if match := _STATED.search(name.lower()):
        return float(match.group(1).replace(",", ".")) * MASS[match.group(2)]
    return None


def implied_weights(dishes: Iterable[Dish], least: int = 3) -> dict[str, float]:
    """What the recipes say a piece weighs, per name weighed in one recipe and counted in another («600 g kyllingfilet»
    for four, «4 kyllingfileter» for four): the median grams a head over its g lines divided by the median pieces a head
    over its stk lines, for names with `least` lines of each kind. No Jev in it: the check on Traits.piece_g
    (docs/plan-per-person.md, the guards)."""
    weighed: dict[str, list[float]] = {}
    pieces: dict[str, list[float]] = {}
    for d in dishes:
        for p in d.parts:
            if p.unit in MASS and p.grams:
                weighed.setdefault(p.name, []).append(p.grams)
            elif p.unit == PIECE and p.pieces:
                pieces.setdefault(p.name, []).append(p.pieces)
    return {
        name: median(weighed[name]) / median(pieces[name])
        for name in sorted(pieces)
        if len(pieces[name]) >= least and len(weighed.get(name, ())) >= least
    }


def per_portion(part: Part) -> Amount | None:
    """What the recipe wants a head: (grams, g) for a mass; (grams, ml) for a volume, since the rough table counts a ml
    as a gram; (pieces, stk) for stk; (pieces, pk) for a container. None for other piece words (a skive, a båt, a bunt:
    nothing to price them by) and for a line with no amount."""
    if part.unit in MASS or part.unit in VOLUME:
        return None if part.grams is None else (part.grams, "g" if part.unit in MASS else "ml")
    if part.pieces is None:
        return None
    if part.unit == PIECE:
        return part.pieces, PIECE
    if part.unit in CONTAINERS:
        return part.pieces, PACK
    return None


def bought(offer: Offer) -> Amount | None:
    """What the offer's price buys, in g, ml or stk: the packs times one pack's size, a range at its midpoint."""
    if offer.size is None or offer.unit not in _OFFER_UNITS:
        return None
    size = (offer.size + offer.size_to) / 2 if offer.size_to else offer.size
    factor, unit = _OFFER_UNITS[offer.unit]
    return offer.pieces * size * factor, unit


def packed(offer: Offer) -> bool:
    """Sold as packs (g, ml or stk of content), not priced by weight: what a recipe's container can be one of."""
    return offer.unit in ("g", "ml", PIECE)


def _met(part: Part, offer: Offer, piece_g: float | None) -> tuple[float, float, str, Pricing] | None:
    """Where the recipe's line and the offer meet: what the recipe wants a head in the offer's unit, what the price buys
    in it, that unit (g, ml, stk or pk) and how they met (the table in docs/plan-per-person.md). `piece_g` is the name's
    grams per stk from the vocabulary (Traits.piece_g), the one bridge between pieces and weight; None when not known.
    None when a side says no amount, the two do not meet, or a head is past CAP."""
    wanted, have = per_portion(part), bought(offer)
    if wanted is None or have is None:
        return None
    amount, unit = wanted
    total, in_unit = have
    pricing = Pricing.INDIRECT if offer.size_to else Pricing.DIRECT
    if unit == PACK:
        if not packed(offer):
            return None
        total, in_unit = float(offer.pieces), PACK
    elif unit == in_unit:
        pass
    elif unit == PIECE and in_unit == "g" and piece_g:
        amount, pricing = amount * piece_g, Pricing.INDIRECT
    elif unit == "g" and in_unit == PIECE and piece_g:
        amount, pricing = amount / piece_g, Pricing.INDIRECT
    elif {unit, in_unit} == {"g", "ml"}:
        pricing = Pricing.INDIRECT  # A solid by volume at a gram a ml, as the rough table has it
    else:
        return None
    if amount > CAP[in_unit] or total <= 0:
        return None
    return amount, total, in_unit, pricing


def price(part: Part, offer: Offer, piece_g: float | None) -> tuple[float, Pricing] | None:
    """Kroner a head on this line, and how: the saving divided by what the price buys, times what the recipe wants a
    head (`_met`). None without a saving, or when the two do not meet."""
    met = _met(part, offer, piece_g)
    if met is None or not offer.saving:
        return None
    amount, total, _, pricing = met
    return offer.saving / total * amount, pricing


def needed(part: Part, offer: Offer, piece_g: float | None, portions: int) -> float:
    """Kroner off this line for what the recipe needs, the card's number (jb 2026-10-23: "say the recepie calls for 2kg
    of chicken, we should then make sure that we multiplie up the savings if the chickon on sale is ex. 1kg"). Priced
    by weight or volume (per kg, per l, per 100 g): the saving times the need's share of what the price buys, so 2 kg
    against a kilo price counts twice and 300 g counts 0,3. Sold as packs: the saving on every lot the price buys («2
    for 80» is one lot of two), as many lots as the need fills, at least one. The catalog's saving once when a side
    says no amount, the two do not meet (`_met`) or the need is past MOST_LOTS or MOST_WEIGHED, as the card had it
    before; 0 without a saving."""
    saving = offer.saving or 0.0
    met = _met(part, offer, piece_g)
    if not saving or met is None:
        return saving
    amount, total, _, _ = met
    need = amount * portions
    if not packed(offer):
        return saving * need / total if need <= MOST_WEIGHED else saving
    lots = max(1, math.ceil(round(need / total, 6)))
    return saving * lots if lots <= MOST_LOTS else saving
