"""TypeSafe Jev adapters, one per classifier port. https://docs.typesafe.ai

Each question is one literal judgment about public data (an ingredient name and its
grocery department, an offer heading); nothing about the household is sent.
Criteria name Norwegian examples, which moved Jev from guessing to right on purre,
risnudler, tamari and matfløte in a probe of 50 ingredients. The department fixed 28 of 36
wrong answers on rarer words (reker, svinebog, multer). Turning probabilities into labels
is done here, in code.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import httpx2
from typesafe_sdk import Choice, JSONContent, Noul, Score, SystemOneResponse, TypeSafeError

from core.errors import ClassifierUnavailableError
from core.models import Ingredient, Item, Offer

type Question = Noul | Choice | Score

log = logging.getLogger("matris.jev")

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
        return f"Jev: {self.calls:,} calls, {self.tokens:,} tokens, ~${cost:.3f}"

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
            tokens = (response.usage.input_tokens or 0) if response.usage is not None else 0
            self.tokens += tokens
            log.debug(
                "Jev %s %r: %d questions, %d tokens, %.1f s",
                name,
                state.get("ingredient") if isinstance(state, dict) else state,
                len(questions),
                tokens,
                time.monotonic() - started,
            )
            return response


type Reader = Callable[[Mapping[str, float]], str]
"""Turns Jev's probabilities for one label into its level."""


@dataclass(frozen=True, slots=True)
class Label:
    """One question about an ingredient, and how its answer becomes a level."""

    choice: Choice
    read: Reader


def _label(probabilities: Mapping[str, float], hard: str, maybe: str) -> str | None:
    """`hard` when it is likely; `maybe` when it and `hard` together are likely."""
    if probabilities.get(hard, 0.0) >= 0.5:
        return hard
    if probabilities.get(hard, 0.0) + probabilities.get(maybe, 0.0) >= 0.5:
        return maybe
    return None


def _likeliest(probabilities: Mapping[str, float], labels: Sequence[str]) -> str:
    return max(labels, key=lambda label: probabilities.get(label, 0.0))


def _strict(probabilities: Mapping[str, float]) -> str:
    return _label(probabilities, "yes", "maybe") or "no"


def _onion(p: Mapping[str, float]) -> str:
    return _label(p, "onion", "maybe") or ("garlic" if p.get("garlic", 0.0) >= 0.5 else "none")


def _lactose(p: Mapping[str, float]) -> str:
    dairy = p.get("some", 0.0) + p.get("high", 0.0) >= 0.5
    return _likeliest(p, ("some", "high") if dairy else ("none", "trace"))


def _kids(p: Mapping[str, float]) -> str:
    worst = _likeliest(p, ("spicy", "choking"))
    return worst if p.get(worst, 0.0) >= 0.5 else "ok"


class Labels:
    """The registry of questions asked about an ingredient, by label key (core.models.LABELS). Each answer is
    stored per (ingredient, label), so a label added later is only asked for the pairs not stored."""

    def __init__(self) -> None:
        self._labels: dict[str, Label] = {}

    def add(self, key: str, instructions: str, criteria: Mapping[str, str], read: Reader) -> None:
        if key in self._labels:
            raise ValueError(f"label {key} added twice")
        self._labels[key] = Label(Choice(instructions=instructions, criteria=dict(criteria)), read)

    def contains(self, key: str, what: str, *, yes: str, maybe: str, no: str) -> None:
        """The common shape: does it hold `what`? Yes, maybe (some brands add it), or no."""
        self.add(
            key,
            f"Does the Norwegian grocery ingredient `ingredient`, sold in the `category` department, contain {what} "
            "as normally sold in Norway?",
            {"yes": yes, "maybe": maybe, "no": no},
            _strict,
        )

    def keys(self) -> tuple[str, ...]:
        return tuple(self._labels)

    def questions(self, keys: Iterable[str]) -> dict[str, Question]:
        return {key: self._labels[key].choice for key in keys}

    def read(self, response: SystemOneResponse, keys: Iterable[str]) -> dict[str, str]:
        return {key: self._labels[key].read(response.choices[key].probabilities) for key in keys}


def ingredient_labels() -> Labels:
    """Every question about an ingredient. Criteria name Norwegian examples (see the module docstring)."""
    labels = Labels()
    labels.add(
        "gluten",
        "Does the Norwegian grocery ingredient `ingredient`, sold in the `category` department, contain gluten as normally sold in Norway?",
        {
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
        _strict,
    )
    labels.add(
        "onion",
        "Is the Norwegian grocery ingredient `ingredient`, sold in the `category` department, an onion-family vegetable, "
        "or does it normally contain one?",
        {
            "onion": "Onion family: løk, gul løk, rødløk, sjalottløk, vårløk, purre, purreløk, "
            "perleløk, løkpulver, stekt løk, and products with onion in them",
            "garlic": "Garlic: hvitløk, hvitløkspulver, and products where garlic is the main flavour",
            "maybe": "Processed products that often contain onion powder: buljong, kraft, krydderblandinger, ferdigsauser, pølser",
            "none": "No onion or garlic: gressløk (chives), meat, fish, dairy, grains, other vegetables, fruit, plain spices",
        },
        _onion,
    )
    labels.add(
        "lactose",
        "How much lactose does the Norwegian grocery ingredient `ingredient`, sold in the `category` department, contain?",
        {
            # "vann" was "high" until water, salt and sugar were named here.
            "none": "No lactose: anything that is not dairy (vann, salt, sukker, egg, oils, coconut "
            "milk, meat, fish, vegetables, rice, noodles, stock), or dairy labelled laktosefri",
            "trace": "Almost none: butter (smør), aged hard cheese (parmesan, norvegia, jarlsberg, revet ost, cheddar), feta, mozzarella",
            "some": "Some lactose: matfløte, kremfløte, rømme, crème fraîche, kremost, kesam, cottage cheese",
            "high": "A lot of lactose: melk, lettmelk, helmelk, kulturmelk, yoghurt, milk powder, brunost",
        },
        _lactose,
    )
    labels.add(
        "kids",
        "Is the Norwegian grocery ingredient `ingredient`, sold in the `category` department, a problem in a dinner for toddlers?",
        {
            "spicy": "Hot chili heat: chili, chilipepper, cayenne, jalapeño, sriracha, sambal oelek, harissa, tabasco",
            "choking": "A choking risk when whole: whole nuts, peanøtter, mandler, cashewnøtter, pinjekjerner",
            "ok": "Fine for small children: everything else, including mild spices, paprika, pepper, ginger, muskatnøtt and "
            "sweet chili sauce",
        },
        _kids,
    )
    # The EU allergens besides gluten (Mattilsynet's list), jb 2026-10-13: "We need a shiton of kosthold filters"
    labels.contains(
        Item.MILK,
        "milk or anything made from milk",
        yes="melk, laktosefri melk, fløte, matfløte, rømme, crème fraîche, yoghurt, smør, ost, parmesan, kremost, brunost, "
        "myseost, melkepulver, pesto",
        maybe="Processed products where some brands add milk: ferdigsauser, kjøttkaker, fiskekaker, pølser, margarin",
        # Probe 2026-10-13: vineddik and eggnudler were "yes", and every mushroom "maybe", until named here
        no="kokosmelk, havremelk, soyamelk, mandelmelk, plantebasert smør, peanøttsmør, kakaosmør, egg, eggnudler, vineddik "
        "and other eddik, sopp (every mushroom: sjampinjong, aromasopp, portobello, steinsopp), akevitt, vodka, vin, øl",
    )
    labels.contains(
        Item.EGG,
        "egg",
        yes="egg, eggeplomme, eggehvite, majones, aioli, remulade, hollandaise, eggnudler, fersk pasta",
        maybe="Processed products where some brands add egg: fiskekaker, kjøttkaker, panerte produkter, dressinger",
        # Probe 2026-10-13: dijonsennep, ørretrogn and laksekotelett were "yes" until named here
        no="tørket pasta of durum, risnudler, sennep, dijonsennep, fish roe (rogn, kaviar: fish, not egg), fish steaks "
        "(laksekotelett), everything without egg",
    )
    labels.contains(
        Item.FISH,
        "fish",
        # godt.no probe 2026-10-14: uer and breiflabb were "no" until named here
        yes="all fish (laks, torsk, sei, makrell, tunfisk, sild, uer, breiflabb, kveite, steinbit), ansjos, kaviar, fiskesaus, "
        "worcestershiresaus, fiskeboller, fiskekraft, bonito, dashi",
        maybe="Products that sometimes hold fish: caesardressing, asiatiske krydderpastaer",
        no="skalldyr and bløtdyr (asked separately), tang, nori, sylteagurk and other pickles, everything else",
    )
    labels.contains(
        Item.CRUSTACEAN,
        "crustaceans (skalldyr)",
        yes="reker, krabbe, hummer, kreps, sjøkreps, scampi, rekepasta",
        maybe="sjømatblanding, thailandsk karripasta (often holds shrimp paste), fiskesuppebase",
        no="blåskjell, kamskjell, blekksprut (asked separately), fish, everything else",
    )
    labels.contains(
        Item.MOLLUSC,
        "molluscs (bløtdyr)",
        yes="blåskjell, kamskjell, østers, hjerteskjell, blekksprut, akkar, snegler, østerssaus",
        maybe="sjømatblanding",
        no="reker, krabbe (asked separately), fish, everything else",
    )
    labels.contains(
        Item.TREE_NUT,
        "tree nuts",
        yes="mandler, hasselnøtter, valnøtter, cashewnøtter, pistasjnøtter, pekannøtter, paranøtter, macadamianøtter, marsipan, nøtteolje",
        maybe="pinjekjerner, pesto, müsli, nøtteblandinger",
        no="kokos, muskatnøtt, peanøtter (asked separately), everything else",
    )
    labels.contains(
        Item.PEANUT,
        "peanuts",
        yes="peanøtter, peanøttsmør, peanøttolje, sataysaus",
        maybe="asiatiske sauser and krydderpastaer, nøtteblandinger",
        no="other nuts, everything else",
    )
    labels.contains(
        Item.SOY,
        "soy",
        yes="soyasaus, tamari, tofu, edamame, soyabønner, miso, soyamelk, teriyakisaus, hoisinsaus",
        maybe="østerssaus, ferdigsauser, pølser, vegetarprodukter",
        no="fiskesaus, everything else",
    )
    labels.contains(
        Item.SESAME,
        "sesame",
        yes="sesamfrø, sesamolje, tahini, hummus",
        maybe="dukkah, za'atar, asiatiske sauser, hamburgerbrød",
        no="everything else",
    )
    labels.contains(
        Item.CELERY,
        "celery",
        yes="stangselleri, sellerirot, sellerisalt, selleripulver, suppegrønnsaker",
        maybe="buljong, kraft, ferdigsupper, krydderblandinger",
        no="other vegetables, everything else",
    )
    labels.contains(
        Item.MUSTARD,
        "mustard",
        yes="sennep, dijonsennep, grov sennep, sennepsfrø, sennepspulver",
        maybe="majones, remulade, dressinger, karri (karripulver often holds sennepsfrø), krydderblandinger, pølser",
        no="everything else",
    )
    labels.contains(
        Item.SULPHITE,
        "sulphites (svoveldioksid)",
        yes="vin, hvitvin, rødvin, portvin, sherry, tørket aprikos, rosiner, vineddik, balsamico",
        maybe="syltede grønnsaker, sylteagurk, sitronsaft på flaske, ferdige potetprodukter",
        no="fresh food, everything else",
    )
    labels.contains(
        Item.LUPIN,
        "lupin",
        yes="lupinmel, lupinbønner",
        maybe="glutenfrie melblandinger",
        no="everything else",
    )
    labels.contains(
        Item.LEGUME,
        "legumes (belgfrukter)",
        yes="erter, sukkererter, kidneybønner, hvite bønner, svarte bønner, brekkbønner, linser, kikerter, hummus, edamame, "
        "soyabønner, peanøtter",
        maybe="vegetarprodukter, ferdigsupper",
        no="everything else",
    )
    # For vegetar, vegansk, pescetarianer, uten svin and uten alkohol
    labels.contains(
        Item.MEAT,
        "meat or poultry, or anything made from them",
        # godt.no probe 2026-10-14: and (duck), elg and bog were "no" until named here
        yes="all meat and poultry (and is duck; gås, rype, elg, hjort; bog is a shoulder cut), bacon, pølser, skinke, "
        "kjøttkraft, kyllingbuljong, oksebuljong, kalvefond, smult, gelatin",
        maybe="buljong or kraft of unnamed kind, ferdigsauser",
        no="fish and shellfish (asked separately), dairy, cheese, egg, sopp (every mushroom: aromasopp, portobello, "
        "steinsopp), everything else",
    )
    labels.contains(
        Item.ANIMAL,
        "anything of animal origin",
        yes="meat, poultry, fish, shellfish, milk, cheese, smør, fløte, egg, majones, honning, gelatin, smult, fiskesaus",
        maybe="ferdigsauser, buljong, pesto, brød, eggnudler",
        # Full run 2026-10-13: vann was "yes" (526 uses) and every mushroom "maybe" until named here
        no="vann, salt, sukker, vegetables, sopp (every mushroom: sjampinjong, aromasopp, portobellosopp, steinsopp), fruit, "
        "grains, tørket pasta, oils, plantebasert smør, kokosmelk, "
        "tofu, spices, akevitt and other spirits, tortillalefser",
    )
    labels.contains(
        Item.PORK,
        "pork",
        yes="svinekjøtt, bacon, skinke, pancetta, chorizo, salami, medisterdeig, svor, smult",
        maybe="pølser, gelatin, kjøttboller, leverpostei",
        no="kjøttdeig and karbonadedeig of beef, everything else",
    )
    labels.contains(
        Item.ALCOHOL,
        "alcohol",
        yes="vin, øl, sherry, portvin, cognac, akevitt, rom, vodka, likør, mirin, sake",
        maybe="vaniljeekstrakt",
        no="vineddik, balsamico, alkoholfri, everything else",
    )
    labels.add(
        "fodmap",
        "How much FODMAP does the Norwegian grocery ingredient `ingredient`, sold in the `category` department, hold in a "
        "normal serving, as rated by Monash University?",
        {
            "high": "løk, hvitløk, the white part of purre, hvete, rug, bønner, linser, kikerter, epler, pærer, mango, vannmelon, "
            "honning, sopp, blomkål, asparges, melk, yoghurt, cashewnøtter, pistasj",
            "moderate": "fine in small amounts: avokado, søtpotet, brokkoli, mais, kokosmelk, mandler",
            "low": "meat, fish, egg, ris, potet, gulrot, squash, tomat, agurk, paprika, spinat, havre, laktosefri melk, "
            "hard cheese, the green part of vårløk and purre, gressløk, oils, plain spices",
        },
        lambda p: _label(p, "high", "moderate") or "low",
    )
    labels.add(
        "carbs",
        "How many grams of carbohydrate per 100 g does the Norwegian grocery ingredient `ingredient`, sold in the `category` "
        "department, have as sold?",
        {
            "none": "under 2 g: meat, fish, egg, oils, smør, cheese, salad leaves, spices",
            "low": "2-10 g: most vegetables (brokkoli, paprika, tomat, løk, gulrot), melk, fløte, nuts",
            "medium": "10-40 g: poteter, søtpotet, mais, kokte bønner, linser, frukt",
            "high": "over 40 g: mel, ris, pasta, nudler, brød, sukker, honning, sirup, havregryn, couscous",
        },
        lambda p: _likeliest(p, ("none", "low", "medium", "high")),
    )
    labels.add(
        "pregnancy",
        "Does Mattilsynet advise pregnant women against the Norwegian grocery ingredient `ingredient`, sold in the `category` department?",
        {
            "avoid": "røkelaks, gravlaks, rakfisk, raw fish for sushi, lever, leverpostei, spekeskinke, salami, fenalår, "
            "hvalkjøtt, unpasteurised cheese",
            "limit": "tunfisk, stor kveite, gjedde, abbor",
            "ok": "everything else, including fresh fish, meat, pasteurised dairy and egg",
        },
        lambda p: _label(p, "avoid", "limit") or "ok",
    )
    return labels


@dataclass
class JevIngredientClassifier:
    """Implements core.ports.IngredientClassifier: the labels asked for, one Choice each, in one request."""

    jev: Jev
    registry: Labels = field(default_factory=ingredient_labels)

    @property
    def labels(self) -> tuple[str, ...]:
        return self.registry.keys()

    async def classify(self, ingredient: Ingredient, labels: Iterable[str], dish: str = "") -> dict[str, str]:
        keys = tuple(labels)
        state: dict[str, JSONContent] = {"ingredient": ingredient.name, "category": ingredient.category}
        if dish:
            state["dish"] = dish
        response = await self.jev.ask("ingredient", state, self.registry.questions(keys))
        return {**self.registry.read(response, keys), "model": response.model}


@dataclass
class JevDepartmentClassifier:
    """Implements core.ports.DepartmentClassifier: one Choice over the departments, each described by the names filed
    there, and the dish as context. Probed on 200 of matprat's names it was not shown (2026-10-14), without a dish: 158 in
    matprat's own department, and 26 in one that changes a rule, mostly a near miss (frukt for bær, pølser for
    svinekjøtt), some a protein gained or lost (bbq-saus as pølser, smult as melk). 30 names per department, or the kind
    of meat asked apart, did no better; the dish put and, elg, bog and breiflabb right (METHOD.md §2)."""

    jev: Jev

    async def department(self, ingredient: str, departments: Mapping[str, Sequence[str]], dish: str = "") -> str:
        question = Choice(
            instructions="Which department of a Norwegian grocery store sells the recipe ingredient `ingredient`? Each "
            "department lists ingredients a recipe site files there.",
            criteria={department: list(names) for department, names in departments.items()},
        )
        state: dict[str, JSONContent] = {"ingredient": ingredient}
        if dish:
            state["dish"] = dish
        response = await self.jev.ask("department", state, {"department": question})
        probabilities = response.choices["department"].probabilities
        return max(departments, key=lambda department: probabilities.get(department, 0.0))


QUESTIONS_PER_CALL = 100


def _offer_question(offer: Offer, dinner: bool) -> Noul:
    where = " for the dinner `dish`, where the recipe writes `line`" if dinner else ""
    return Noul(
        instructions=f"Can a cook buy the grocery offer «{offer.heading}: {offer.description[:90]}» as the recipe ingredient "
        f"`ingredient`{where}?",
        criteria={
            "true": "Yes: it is that product, in any brand, size or cut that a recipe means by the name, and in a form the dinner can use",
            "false": "No: a different product or animal, a different cut or animal part, a ready meal, pålegg, snack or "
            "sweet, or another form than the recipe means: canned, smoked, cured, salted, dried, marinated, breaded or "
            "pre-cooked when it means raw or fresh, or the other way round",
        },
    )


@dataclass
class JevOfferMatcher:
    """Implements core.ports.OfferMatcher with one yes/no question per offer, all in one request.

    A single Choice over the offers split its probability between several right answers
    (KYLLINGFILET and KYLLINGBRYST) and dropped some. Questions that pointed at `offers[i]`
    in a list mixed offers up (KINDEREGG for "egg"). Each question carries its own offer.
    Offers with the same heading (one product at several chains) are asked about once. With a recipe line and a dinner,
    the form counts: King Oskar's tinned tuna is tunfisk in a tunfisksalat, not in nigiri.
    """

    jev: Jev

    async def rank(self, ingredient: str, offers: Sequence[Offer], line: str = "", dish: str = "") -> Mapping[str, float]:
        groups: dict[str, list[Offer]] = {}
        for offer in offers:
            groups.setdefault(offer.heading.strip().upper(), []).append(offer)
        options = list(groups.values())
        scores: dict[str, float] = {}
        for start in range(0, len(options), QUESTIONS_PER_CALL):
            chunk = options[start : start + QUESTIONS_PER_CALL]
            response = await self.jev.ask(
                "offer matcher",
                {"ingredient": ingredient, "line": line, "dish": dish} if dish else {"ingredient": ingredient},
                {str(i): _offer_question(group[0], bool(dish)) for i, group in enumerate(chunk)},
            )
            for i, group in enumerate(chunk):
                probability = response.nouls[str(i)].noul
                scores.update((offer.id, probability) for offer in group)
        return scores
