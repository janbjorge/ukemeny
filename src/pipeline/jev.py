"""TypeSafe Jev adapters, one per classifier port. https://docs.typesafe.ai

Each question is one literal judgment about public data (an ingredient name and its
matprat grocery department, an offer heading); nothing about the household is sent.
Criteria name Norwegian examples, which moved Jev from guessing to right on purre,
risnudler, tamari and matfløte in a probe of 50 ingredients. The department fixed 28 of 36
wrong answers on rarer words (reker, svinebog, multer). Turning probabilities into labels
is done here, in code.
"""

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import httpx2
from typesafe_sdk import Choice, JSONContent, Noul, Score, SystemOneResponse, TypeSafeError

from core.errors import ClassifierUnavailableError
from core.models import (
    Gluten,
    Ingredient,
    Kids,
    Lactose,
    Offer,
    Onion,
    Traits,
)

type Question = Noul | Choice | Score

# Jev list price per million input tokens; output is free. docs.typesafe.ai/models
PRICE_PER_MTOK = 0.042


class SystemOneClient(Protocol):
    async def system_one(self, state: JSONContent, questions: Mapping[str, Question]) -> SystemOneResponse: ...


@dataclass
class Jev:
    """One client shared by the Jev adapters, with a cap on requests in flight."""

    client: SystemOneClient
    max_in_flight: int = 8
    calls: int = field(default=0, init=False)
    tokens: int = field(default=0, init=False)
    seconds: float = field(default=0.0, init=False)
    _slots: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self._slots = asyncio.Semaphore(self.max_in_flight)

    def status(self) -> str:
        cost = self.tokens / 1e6 * PRICE_PER_MTOK
        return f"Jev: {self.calls:,} calls · {self.tokens:,} tokens ≈ ${cost:.3f}"

    async def ask(self, name: str, state: JSONContent, questions: Mapping[str, Question]) -> SystemOneResponse:
        async with self._slots:
            started = time.monotonic()
            try:
                response = await self.client.system_one(state, questions)
            except (TypeSafeError, httpx2.HTTPError) as e:
                raise ClassifierUnavailableError(name, str(e)) from e
            finally:
                self.calls += 1
                self.seconds += time.monotonic() - started
            if response.usage is not None:
                self.tokens += response.usage.input_tokens or 0
            return response


GLUTEN = Choice(
    instructions="Does the Norwegian grocery ingredient `ingredient`, sold in the `category` "
    "department, contain gluten as normally sold in Norway?",
    criteria={
        "yes": "Made from wheat (hvete), rye (rug), barley (bygg), spelt or malt: mel, pasta, "
        "spaghetti, nudler av hvete, brød, lefser, tortilla, couscous, bulgur, panko, kavring, "
        "soyasaus, østerssaus, øl",
        "maybe": "Processed products where some brands add wheat: buljong, kraft, "
        "krydderblandinger, pølser, fiskeboller, kjøttkaker, sauser, havre that is not "
        "labelled gluten-free",
        "no": "Naturally gluten-free: meat, fish, eggs, dairy, vegetables, fruit, rice, "
        "risnudler, glassnudler, maize/mais, maisenna, potet, potetmel, quinoa, oils, plain "
        "spices (malt kanel, malt ingefær: «malt» means ground), tamari, and anything "
        "labelled glutenfri",
    },
)
ONION = Choice(
    instructions="Is the Norwegian grocery ingredient `ingredient`, sold in the `category` "
    "department, an onion-family vegetable, or does it normally contain one?",
    criteria={
        "onion": "Onion family: løk, gul løk, rødløk, sjalottløk, vårløk, purre, purreløk, "
        "perleløk, løkpulver, stekt løk, and products with onion in them",
        "garlic": "Garlic: hvitløk, hvitløkspulver, and products where garlic is the main flavour",
        "maybe": "Processed products that often contain onion powder: buljong, kraft, krydderblandinger, ferdigsauser, pølser",
        "none": "No onion or garlic: gressløk (chives), meat, fish, dairy, grains, other vegetables, fruit, plain spices",
    },
)
LACTOSE = Choice(
    instructions="How much lactose does the Norwegian grocery ingredient `ingredient`, sold in the `category` department, contain?",
    criteria={
        # "vann" was "high" until water, salt and sugar were named here.
        "none": "No lactose: anything that is not dairy (vann, salt, sukker, egg, oils, coconut "
        "milk, meat, fish, vegetables, rice, noodles, stock), or dairy labelled laktosefri",
        "trace": "Almost none: butter (smør), aged hard cheese (parmesan, norvegia, jarlsberg, revet ost, cheddar), feta, mozzarella",
        "some": "Some lactose: matfløte, kremfløte, rømme, crème fraîche, kremost, kesam, cottage cheese",
        "high": "A lot of lactose: melk, lettmelk, helmelk, kulturmelk, yoghurt, milk powder, brunost",
    },
)
KIDS = Choice(
    instructions="Is the Norwegian grocery ingredient `ingredient`, sold in the `category` department, a problem in a dinner for toddlers?",
    criteria={
        "spicy": "Hot chili heat: chili, chilipepper, cayenne, jalapeño, sriracha, sambal oelek, harissa, tabasco",
        "choking": "A choking risk when whole: whole nuts, peanøtter, mandler, cashewnøtter, pinjekjerner",
        "ok": "Fine for small children: everything else, including mild spices, paprika, pepper, ginger, muskatnøtt and sweet chili sauce",
    },
)


def _label(probabilities: Mapping[str, float], hard: str, maybe: str) -> str | None:
    """`hard` when it is likely; `maybe` when it and `hard` together are likely."""
    if probabilities.get(hard, 0.0) >= 0.5:
        return hard
    if probabilities.get(hard, 0.0) + probabilities.get(maybe, 0.0) >= 0.5:
        return maybe
    return None


def _likeliest(probabilities: Mapping[str, float], labels: Sequence[str]) -> str:
    return max(labels, key=lambda label: probabilities.get(label, 0.0))


def _traits(response: SystemOneResponse) -> Traits:
    gluten = response.choices["gluten"].probabilities
    onion = response.choices["onion"].probabilities
    lactose = response.choices["lactose"].probabilities
    kids = response.choices["kids"].probabilities
    dairy = lactose.get("some", 0.0) + lactose.get("high", 0.0) >= 0.5
    worst = _likeliest(kids, ("spicy", "choking"))
    return Traits(
        gluten=Gluten(_label(gluten, "yes", "maybe") or "no"),
        onion=Onion(_label(onion, "onion", "maybe") or ("garlic" if onion.get("garlic", 0.0) >= 0.5 else "none")),
        lactose=Lactose(_likeliest(lactose, ("some", "high") if dairy else ("none", "trace"))),
        kids=Kids(worst if kids.get(worst, 0.0) >= 0.5 else "ok"),
        model=response.model,
    )


@dataclass
class JevIngredientClassifier:
    """Implements core.ports.IngredientClassifier: four Choices in one request per ingredient."""

    jev: Jev

    async def classify(self, ingredient: Ingredient) -> Traits:
        response = await self.jev.ask(
            "ingredient",
            {"ingredient": ingredient.name, "category": ingredient.category},
            {"gluten": GLUTEN, "onion": ONION, "lactose": LACTOSE, "kids": KIDS},
        )
        return _traits(response)


QUESTIONS_PER_CALL = 100


def _offer_question(offer: Offer) -> Noul:
    return Noul(
        instructions=f"Can a cook buy the grocery offer «{offer.heading}: {offer.description[:90]}» as the recipe ingredient `ingredient`?",
        criteria={
            "true": "Yes: it is that product, in any brand, size or cut that a recipe means by the name",
            "false": "No: a different product, a different cut or animal part, or a ready meal, "
            "pålegg, snack, sweet, or a marinated, breaded or pre-cooked version",
        },
    )


@dataclass
class JevOfferMatcher:
    """Implements core.ports.OfferMatcher with one yes/no question per offer, all in one request.

    A single Choice over the offers split its probability between several right answers
    (KYLLINGFILET and KYLLINGBRYST) and dropped some. Questions that pointed at `offers[i]`
    in a list mixed offers up (KINDEREGG for "egg"). Each question carries its own offer.
    Offers with the same heading (one product at several chains) are asked about once.
    """

    jev: Jev

    async def rank(self, ingredient: str, offers: Sequence[Offer]) -> Mapping[str, float]:
        groups: dict[str, list[Offer]] = {}
        for offer in offers:
            groups.setdefault(offer.heading.strip().upper(), []).append(offer)
        options = list(groups.values())
        scores: dict[str, float] = {}
        for start in range(0, len(options), QUESTIONS_PER_CALL):
            chunk = options[start : start + QUESTIONS_PER_CALL]
            response = await self.jev.ask(
                "offer matcher",
                {"ingredient": ingredient},
                {str(i): _offer_question(group[0]) for i, group in enumerate(chunk)},
            )
            for i, group in enumerate(chunk):
                probability = response.nouls[str(i)].noul
                scores.update((offer.id, probability) for offer in group)
        return scores
