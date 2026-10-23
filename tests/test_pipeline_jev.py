from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest
from typesafe_sdk import (
    Choice,
    ChoiceAnswer,
    JSONContent,
    NoulAnswer,
    Score,
    ScoreAnswer,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    Usage,
)

from core.errors import ClassifierUnavailableError
from core.models import LABELS, Carbs, Fodmap, Gluten, Kids, Lactose, Level, Onion, Pregnancy, Traits
from pipeline.jev import (
    AS_NAMED,
    QUESTIONS_PER_CALL,
    WEIGHT_BANDS,
    Jev,
    JevCategoryClassifier,
    JevIngredientClassifier,
    JevOfferMatcher,
    Question,
    grams_per_piece,
    ingredient_labels,
)
from tests.fakes import ingredient, offer

KYLLING = ingredient("kyllingfilet", 600, "g", "/kjøtt/kylling/høns")
X = ingredient("x")


def choice(probabilities: Mapping[str, float]) -> ChoiceAnswer:
    best = max(probabilities, key=lambda k: probabilities[k])
    return ChoiceAnswer(choice=best, confidence=probabilities[best], probabilities=dict(probabilities))


@dataclass
class FakeClient:
    """Answers every call with the same choices and records what was asked."""

    answers: Mapping[str, Mapping[str, float]]
    calls: list[tuple[JSONContent, Mapping[str, Question]]] = field(default_factory=list)
    error: Exception | None = None

    async def system_one(self, state: JSONContent, questions: Mapping[str, Question]) -> SystemOneResponse:
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        return SystemOneResponse(
            model="jev-1.13.0",
            answers={name: choice(p) for name, p in self.answers.items()},
            usage=Usage(input_tokens=900, output_tokens=0),
        )


@dataclass
class FakeNoulClient:
    """Answers each yes/no question by name; unnamed questions get 0."""

    answers: Mapping[str, float]
    calls: list[tuple[JSONContent, Mapping[str, Question]]] = field(default_factory=list)

    async def system_one(self, state: JSONContent, questions: Mapping[str, Question]) -> SystemOneResponse:
        self.calls.append((state, questions))
        return SystemOneResponse(
            model="jev-1.13.0",
            answers={name: NoulAnswer(noul=self.answers.get(name, 0.0)) for name in questions},
            usage=Usage(input_tokens=100, output_tokens=0),
        )


PLAIN = {
    "gluten": {"no": 0.9, "maybe": 0.05, "yes": 0.05},
    "onion": {"none": 0.9, "garlic": 0.05, "maybe": 0.03, "onion": 0.02},
    "lactose": {"none": 0.9, "trace": 0.1},
    "kids": {"ok": 0.95, "spicy": 0.05},
}
FOUR = tuple(PLAIN)


async def test_classifier_sends_only_the_ingredient_name() -> None:
    client = FakeClient(PLAIN)
    jev = Jev(client)
    levels = await JevIngredientClassifier(jev).classify(KYLLING, FOUR)
    traits = Traits.of(levels)
    assert (traits.gluten, traits.onion, traits.lactose, traits.kids) == (
        Gluten.NO,
        Onion.NONE,
        Lactose.NONE,
        Kids.OK,
    )
    assert traits.source == "jev-1.13.0"
    state, questions = client.calls[0]
    assert state == {"ingredient": "kyllingfilet", "category": "/kjøtt/kylling/høns"}
    assert set(questions) == set(FOUR)
    assert jev.tokens == 900 and jev.calls == 1


async def test_the_registry_holds_every_label_and_asks_them_in_one_request() -> None:
    classifier = JevIngredientClassifier(Jev(client := FakeClient({key: {"no": 1.0} for key in LABELS})))
    assert classifier.labels == LABELS
    levels = await classifier.classify(X, LABELS)
    assert len(client.calls) == 1 and set(levels) == {*LABELS, "source"}
    with pytest.raises(ValueError, match="twice"):
        ingredient_labels().contains("egg", "egg", yes="", maybe="", no="")


async def test_only_the_labels_asked_for_are_sent() -> None:
    client = FakeClient({"egg": {"yes": 0.9, "no": 0.1}, "fodmap": {"low": 0.8, "high": 0.2}})
    levels = await JevIngredientClassifier(Jev(client)).classify(X, ["egg", "fodmap"])
    assert set(client.calls[0][1]) == {"egg", "fodmap"}
    assert levels == {"egg": "yes", "fodmap": "low", "source": "jev-1.13.0"}


async def level(key: str, answer: dict[str, float]) -> str:
    return (await JevIngredientClassifier(Jev(FakeClient({key: answer}))).classify(X, [key]))[key]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"yes": 0.7, "maybe": 0.2, "no": 0.1}, Gluten.YES),
        ({"yes": 0.3, "maybe": 0.3, "no": 0.4}, Gluten.MAYBE),
        ({"yes": 0.1, "maybe": 0.3, "no": 0.6}, Gluten.NO),
    ],
)
async def test_gluten_labels(answer: dict[str, float], expected: Gluten) -> None:
    assert await level("gluten", answer) == expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"onion": 0.55, "maybe": 0.1, "garlic": 0.05, "none": 0.3}, Onion.ONION),
        ({"onion": 0.3, "maybe": 0.25, "garlic": 0.05, "none": 0.4}, Onion.MAYBE),
        ({"onion": 0.05, "maybe": 0.05, "garlic": 0.85, "none": 0.05}, Onion.GARLIC),
        ({"onion": 0.05, "maybe": 0.05, "garlic": 0.4, "none": 0.5}, Onion.NONE),
    ],
)
async def test_onion_labels(answer: dict[str, float], expected: Onion) -> None:
    assert await level("onion", answer) == expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"none": 0.3, "trace": 0.1, "some": 0.2, "high": 0.4}, Lactose.HIGH),
        ({"none": 0.1, "trace": 0.1, "some": 0.7, "high": 0.1}, Lactose.SOME),
        # Unsure between "high" and not dairy at all: not dairy wins.
        ({"none": 0.4, "trace": 0.2, "some": 0.1, "high": 0.3}, Lactose.NONE),
        ({"none": 0.1, "trace": 0.8, "some": 0.05, "high": 0.05}, Lactose.TRACE),
    ],
)
async def test_lactose_labels(answer: dict[str, float], expected: Lactose) -> None:
    assert await level("lactose", answer) == expected


async def test_kids_label() -> None:
    assert await level("kids", {"ok": 0.2, "spicy": 0.75, "choking": 0.05}) == Kids.SPICY


@pytest.mark.parametrize(
    ("key", "answer", "expected"),
    [
        ("milk", {"yes": 0.6, "maybe": 0.1, "no": 0.3}, Level.YES),
        ("celery", {"yes": 0.2, "maybe": 0.35, "no": 0.45}, Level.MAYBE),  # buljong: some brands add it
        ("egg", {"yes": 0.1, "maybe": 0.2, "no": 0.7}, Level.NO),
        ("fodmap", {"high": 0.3, "moderate": 0.3, "low": 0.4}, Fodmap.MODERATE),
        ("carbs", {"none": 0.1, "low": 0.2, "medium": 0.3, "high": 0.4}, Carbs.HIGH),
        ("pregnancy", {"avoid": 0.6, "limit": 0.1, "ok": 0.3}, Pregnancy.AVOID),
    ],
)
async def test_new_labels(key: str, answer: dict[str, float], expected: str) -> None:
    assert await level(key, answer) == expected


@dataclass
class FakeScoreClient:
    """Answers every score question with the same expected band and confidence."""

    score: float
    confidence: float = 0.9
    calls: list[tuple[JSONContent, Mapping[str, Question]]] = field(default_factory=list)

    async def system_one(self, state: JSONContent, questions: Mapping[str, Question]) -> SystemOneResponse:
        self.calls.append((state, questions))
        return SystemOneResponse(
            model="jev-1.14.0",
            answers={
                name: ScoreAnswer(score=self.score, confidence=self.confidence, legend={}, probabilities={int(self.score): 1.0})
                for name in questions
            },
            usage=Usage(input_tokens=200, output_tokens=0),
        )


async def test_a_piece_weight_is_a_band_read_as_grams() -> None:
    client = FakeScoreClient(4.5)  # A 50/50 between 80 to 160 g and 160 to 320 g
    assert await JevIngredientClassifier(Jev(client)).weigh(KYLLING) == 160
    state, questions = client.calls[0]
    assert state == {"ingredient": "kyllingfilet", "category": "/kjøtt/kylling/høns"}
    question = questions["piece_g"]
    assert isinstance(question, Score) and len(question.criteria) == len(WEIGHT_BANDS) == 10
    assert "one piece" in str(question.instructions) and "egg" in str(question.criteria[3])
    assert (grams_per_piece(0), grams_per_piece(3), grams_per_piece(9)) == (7.1, 57, 3600)


async def test_category_is_the_likeliest_of_those_offered_and_only_the_name_is_sent() -> None:
    client = FakeClient({"category": {"/fisk og sjømat": 0.6, "/pasta/ris": 0.3, "/annet": 0.1}})
    shelves = {"/fisk og sjømat": ("torskefilet", "laksefilet"), "/pasta/ris": ("jasminris",)}
    assert await JevCategoryClassifier(Jev(client)).category("kveite", shelves) == "/fisk og sjømat"
    state, questions = client.calls[0]
    assert state == {"ingredient": "kveite"}  # No dinner: the first by URL put erter in /egg
    question = questions["category"]
    assert isinstance(question, Choice)
    assert dict(question.criteria) == {"/fisk og sjømat": ["torskefilet", "laksefilet"], "/pasta/ris": ["jasminris"]}


async def test_matcher_asks_once_per_heading_and_scores_each_offer() -> None:
    kiwi = offer("KYLLINGFILET", 99, store="KIWI")
    rema = offer("Kyllingfilet ", 109, store="REMA 1000")
    sausage = offer("KYLLINGPØLSER", 39)
    client = FakeNoulClient({"0": 0.9, "1": 0.05})
    scores = await JevOfferMatcher(Jev(client)).rank("kyllingfilet", [kiwi, rema, sausage])
    assert scores == {kiwi.id: 0.9, rema.id: 0.9, sausage.id: 0.05}
    state, questions = client.calls[0]
    assert state == {"ingredient": "kyllingfilet"}
    assert set(questions) == {"0", "1"}
    assert "KYLLINGPØLSER" in str(questions["1"].instructions)


async def test_matcher_asks_with_the_form_and_the_dinner() -> None:
    tin = offer("Tunfisk", 15, store="MENY")
    client = FakeNoulClient({"0": 0.1})
    await JevOfferMatcher(Jev(client)).rank("tunfisk", [tin], "", "Hjemmelaget nigiri sushi")
    state, questions = client.calls[0]
    assert state == {"ingredient": "tunfisk", "form": AS_NAMED, "dish": "Hjemmelaget nigiri sushi"}
    assert "`form`" in str(questions["0"].instructions) and "canned" in str(questions["0"].criteria)
    await JevOfferMatcher(Jev(client)).rank("tunfisk", [tin], "hermetisk", "Tunfisksalat")
    assert client.calls[1][0] == {"ingredient": "tunfisk", "form": "hermetisk", "dish": "Tunfisksalat"}


async def test_matcher_splits_long_lists() -> None:
    many = [offer(f"KYLLING {i}") for i in range(QUESTIONS_PER_CALL + 1)]
    client = FakeNoulClient({str(i): 0.5 for i in range(QUESTIONS_PER_CALL)})
    scores = await JevOfferMatcher(Jev(client)).rank("kyllingfilet", many)
    assert len(client.calls) == 2
    assert len(scores) == QUESTIONS_PER_CALL + 1


async def test_errors_become_classifier_unavailable() -> None:
    client = FakeClient(PLAIN, error=TypeSafeAPIConnectionError("down"))
    with pytest.raises(ClassifierUnavailableError):
        await JevIngredientClassifier(Jev(client)).classify(X, FOUR)
