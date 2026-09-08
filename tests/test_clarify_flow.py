"""The clarification loop: when it fires, and how it asks.

The reported defects this pins:

  * two questions arrived side by side, so the card read as a form rather than a
    conversation;
  * a question that already named a carrier (or a country, or a year) was still
    stopped to be asked for another filter;
  * clarification was, in practice, only about missing filters — a genuinely
    unclear question had no way to reach a human.

The flow covered is the real one:

    routing context -> clarify_decide -> the rendered card -> one answer at a
    time -> clarify_gate resumes with every answer

Run:  pytest tests/test_clarify_flow.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest
from dash.development.base_component import Component
from langchain_core.messages import HumanMessage

import core.graph.hitl as hitl
from core.agents.common.mandatory_filters import MandatoryFilterGate
from core.schemas.hitl import ClarifyDecision, ClarifyOption, ClarifyQuestion
from core.schemas.routing import QueryEntities, RoutingContext
from ui.components.chatbot import clarify_card


def ctx(**kwargs) -> RoutingContext:
    context = RoutingContext(table_family="premium", intent_type="new_question")
    for key, value in kwargs.items():
        setattr(context, key, value)
    return context


class _Decider:
    """A stand-in for the LLM ambiguity classifier."""

    def __init__(self, decision: ClarifyDecision) -> None:
        self.decision = decision
        self.calls = 0

    def __call__(self, **_kwargs) -> ClarifyDecision:
        self.calls += 1
        return self.decision


_SILENT = ClarifyDecision(needs_clarification=False, reason="clear")
_CONFUSED = ClarifyDecision(
    needs_clarification=True,
    reason="'performance' could mean premium or broker score",
    question=ClarifyQuestion(
        header="Measure",
        question="Do you mean premium performance or broker-survey performance?",
        options=[
            ClarifyOption(label="Premium", description="Written premium"),
            ClarifyOption(label="Broker survey", description="Broker scores"),
        ],
    ),
)


def walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


def classes(node) -> list:
    return [(getattr(n, "className", "") or "") for n in walk(node)]


def open_questions(card) -> list:
    return [
        str(n.children)
        for n in walk(card)
        if (getattr(n, "className", "") or "") == "clarify-card-question"
    ]


# ── when the filter gate stays quiet ────────────────────────────────────────


def gate() -> MandatoryFilterGate:
    return MandatoryFilterGate()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resolved_filters": {"Carrier_Group": ["ZURICH GROUP"]}},
        {"resolved_filters": {"Country": ["Canada"]}},
        {"timeframe_hint": "2024"},
        {"inherited_carrier": "Zurich"},
        {"inherited_country": "United Kingdom"},
        {"inherited_year": "2024"},
        {"entities": QueryEntities(carriers=["Zurich"])},
        {"entities": QueryEntities(countries=["Canada"])},
        {"entities": QueryEntities(years=["2024"])},
        # A resolved year has no `entity_columns` role, so it is matched by name.
        {"resolved_filters": {"Year": ["2024"]}},
        {"resolved_filters": {"Survey_Year": ["2026"]}},
    ],
)
def test_any_one_of_carrier_country_or_year_scopes_the_turn(kwargs):
    """Naming ONE of the three is enough; the analyst can answer from there."""
    assert gate().missing_mandatory_filters(ctx(**kwargs)) == []


def test_a_turn_scoped_by_nothing_is_the_one_that_is_stopped():
    missing = gate().missing_mandatory_filters(ctx(resolved_filters={}))
    assert [req.role for req in missing] == ["carrier", "country"]


def test_a_product_alone_does_not_scope_the_turn():
    """Carrier / country / year say WHAT the question is about; a product does not."""
    missing = gate().missing_mandatory_filters(
        ctx(resolved_filters={"Product_Line": ["Property"]})
    )
    assert [req.role for req in missing] == ["carrier", "country"]


def test_an_out_of_scope_turn_never_clarifies():
    assert gate().missing_mandatory_filters(
        RoutingContext(table_family="fallback", intent_type="new_question")
    ) == []


# ── a confused question still reaches a human ───────────────────────────────


def test_an_unclear_question_clarifies_even_though_it_is_fully_scoped(monkeypatch):
    """Clarification is about MEANING too, not only about missing filters."""
    decider = _Decider(_CONFUSED)
    monkeypatch.setattr(hitl, "_CLARIFY_DECIDER", decider)
    state = {
        "messages": [HumanMessage(content="how is Zurich performing in Canada?", id="m1")],
        "routing_context": ctx(
            resolved_filters={"Carrier_Group": ["ZURICH GROUP"], "Country": ["Canada"]}
        ),
    }
    questions = hitl.clarify_decide(state)["clarify_questions"]
    assert decider.calls == 1, "the classifier must still run on a scoped turn"
    assert [q["kind"] for q in questions] == ["ambiguity"]
    assert "premium performance" in questions[0]["question"]


def test_a_clear_scoped_question_asks_nothing(monkeypatch):
    monkeypatch.setattr(hitl, "_CLARIFY_DECIDER", _Decider(_SILENT))
    state = {
        "messages": [HumanMessage(content="Zurich premium in Canada 2024", id="m1")],
        "routing_context": ctx(resolved_filters={"Carrier_Group": ["ZURICH GROUP"]}),
    }
    assert hitl.clarify_decide(state)["clarify_questions"] is None


# ── one question at a time ──────────────────────────────────────────────────


def two_questions() -> dict:
    return {
        "kind": "clarify",
        "questions": [
            {
                "id": "mandatory:carrier",
                "header": "Carrier",
                "question": "Which carrier would you like me to analyze?",
                "options": [{"label": "Zurich"}, {"label": "Chubb"}],
                "allow_free_text": True,
            },
            {
                "id": "mandatory:country",
                "header": "Country",
                "question": "Which market/country should I focus on?",
                "options": [{"label": "Canada"}, {"label": "United Kingdom"}],
                "allow_free_text": True,
            },
        ],
    }


def test_the_card_asks_the_first_question_and_only_the_first():
    card = clarify_card(two_questions())
    assert open_questions(card) == ["Which carrier would you like me to analyze?"]


def test_answering_the_first_reveals_the_second():
    payload = two_questions()
    payload["answers"] = {"mandatory:carrier": "Zurich"}
    card = clarify_card(payload)
    assert open_questions(card) == ["Which market/country should I focus on?"]


def test_an_answered_question_collapses_to_its_answer():
    payload = two_questions()
    payload["answers"] = {"mandatory:carrier": "Zurich"}
    card = clarify_card(payload)
    settled = [n for n in walk(card) if (getattr(n, "className", "") or "") == "clarify-answered"]
    assert len(settled) == 1
    values = [
        str(n.children)
        for n in walk(card)
        if (getattr(n, "className", "") or "") == "clarify-done-value"
    ]
    assert values == ["Zurich"]
    # Its option buttons are gone, not merely disabled — a row of dead buttons
    # above the live question is noise.
    labels = [
        str(n.children)
        for n in walk(card)
        if (getattr(n, "className", "") or "") == "clarify-option-label"
    ]
    assert "Chubb" not in labels


def test_the_card_says_where_you_are_in_the_sequence():
    card = clarify_card(two_questions())
    steps = [
        str(n.children)
        for n in walk(card)
        if (getattr(n, "className", "") or "") == "clarify-step-label"
    ]
    assert steps == ["Question 1 of 2"]
    pips = [c for c in classes(card) if c.split(" ")[0] == "clarify-pip"]
    assert len(pips) == 2 and any("current" in c for c in pips)


def test_a_single_question_needs_no_step_counter():
    payload = two_questions()
    payload["questions"] = payload["questions"][:1]
    assert not any(c == "clarify-steps" for c in classes(clarify_card(payload)))


def test_the_gate_still_resumes_with_every_answer():
    """Sequencing is a change of pace in the UI, not of the graph's contract."""
    questions = two_questions()["questions"]
    answers = hitl._normalize_answers(
        {"mandatory:carrier": "Zurich", "mandatory:country": "Canada"}, questions
    )
    assert answers == {"mandatory:carrier": "Zurich", "mandatory:country": "Canada"}
