from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from typesafe_sdk import (
    ChoiceAnswer,
    NoulAnswer,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    Usage,
)

from core.errors import ClassifierUnavailableError
from core.models import Gluten, Kids, Lactose, Onion
from pipeline.jev import (
    QUESTIONS_PER_CALL,
    Jev,
    JevIngredientClassifier,
    JevOfferMatcher,
    Question,
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
    calls: list[tuple[Any, Mapping[str, Question]]] = field(default_factory=list)
    error: Exception | None = None

    async def system_one(self, state: Any, questions: Mapping[str, Question]) -> SystemOneResponse:
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
    calls: list[tuple[Any, Mapping[str, Question]]] = field(default_factory=list)

    async def system_one(self, state: Any, questions: Mapping[str, Question]) -> SystemOneResponse:
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


async def test_classifier_sends_only_the_ingredient_name() -> None:
    client = FakeClient(PLAIN)
    jev = Jev(client)
    traits = await JevIngredientClassifier(jev).classify(KYLLING)
    assert (traits.gluten, traits.onion, traits.lactose, traits.kids) == (
        Gluten.NO,
        Onion.NONE,
        Lactose.NONE,
        Kids.OK,
    )
    assert traits.model == "jev-1.13.0"
    state, questions = client.calls[0]
    assert state == {"ingredient": "kyllingfilet", "category": "/kjøtt/kylling/høns"}
    assert set(questions) == {"gluten", "onion", "lactose", "kids"}
    assert jev.tokens == 900 and jev.calls == 1


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"yes": 0.7, "maybe": 0.2, "no": 0.1}, Gluten.YES),
        ({"yes": 0.3, "maybe": 0.3, "no": 0.4}, Gluten.MAYBE),
        ({"yes": 0.1, "maybe": 0.3, "no": 0.6}, Gluten.NO),
    ],
)
async def test_gluten_labels(answer: dict[str, float], expected: Gluten) -> None:
    traits = await JevIngredientClassifier(Jev(FakeClient(PLAIN | {"gluten": answer}))).classify(X)
    assert traits.gluten is expected


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
    traits = await JevIngredientClassifier(Jev(FakeClient(PLAIN | {"onion": answer}))).classify(X)
    assert traits.onion is expected


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
    traits = await JevIngredientClassifier(Jev(FakeClient(PLAIN | {"lactose": answer}))).classify(X)
    assert traits.lactose is expected


async def test_kids_label() -> None:
    answer = {"ok": 0.2, "spicy": 0.75, "choking": 0.05}
    traits = await JevIngredientClassifier(Jev(FakeClient(PLAIN | {"kids": answer}))).classify(X)
    assert traits.kids is Kids.SPICY


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
    assert "KYLLINGPØLSER" in str(questions["1"].instructions)  # type: ignore[union-attr]


async def test_matcher_splits_long_lists() -> None:
    many = [offer(f"KYLLING {i}") for i in range(QUESTIONS_PER_CALL + 1)]
    client = FakeNoulClient({str(i): 0.5 for i in range(QUESTIONS_PER_CALL)})
    scores = await JevOfferMatcher(Jev(client)).rank("kyllingfilet", many)
    assert len(client.calls) == 2
    assert len(scores) == QUESTIONS_PER_CALL + 1


async def test_errors_become_classifier_unavailable() -> None:
    client = FakeClient(PLAIN, error=TypeSafeAPIConnectionError("down"))
    with pytest.raises(ClassifierUnavailableError):
        await JevIngredientClassifier(Jev(client)).classify(X)
