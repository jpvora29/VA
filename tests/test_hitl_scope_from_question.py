"""The clarify gate must not interrogate a user about what they plainly said.

The reported failure: "Explain the performance of AXA in singapore for the year
2025?" was stopped to ask which carrier and which country — and it happened on
almost every question.

The cause was structural rather than a bad rule. Every signal `has_scope` read —
`entities`, `resolved_filters`, `inherited_*`, `timeframe_hint` — is written by
the extraction step. A turn whose extraction returned an empty context was
therefore indistinguishable from a turn that named nothing at all, so the gate
did exactly what it was designed to do, on a premise that was wrong.

Reading the raw question cannot repair a bad extraction. It can stop one from
producing an absurd question, which is what these tests pin.
"""
from __future__ import annotations

import pytest

from core.agents.common.mandatory_filters import MandatoryFilterGate
from core.schemas.routing import QueryEntities, RoutingContext


def _context(**kwargs) -> RoutingContext:
    kwargs.setdefault("table_family", "premium")
    kwargs.setdefault("intent_type", "new_question")
    kwargs.setdefault("entities", QueryEntities())
    return RoutingContext(**kwargs)


@pytest.fixture
def gate():
    """A gate with no warehouse behind it, so the year path is tested alone."""
    return MandatoryFilterGate(matcher=lambda flow, column, text: False)


@pytest.fixture
def knows_values():
    """A gate whose matcher recognises the entity names in the fixtures."""
    known = {"axa", "zurich", "singapore", "canada"}

    def matcher(flow: str, column: str, text: str) -> bool:
        return any(name in (text or "").lower() for name in known)

    return MandatoryFilterGate(matcher=matcher)


# --------------------------------------------------------------------------- #
# The reported failure
# --------------------------------------------------------------------------- #


def test_a_fully_specified_question_is_never_asked_to_specify_itself(gate):
    question = "Explain the performance of AXA in singapore for the year 2025?"
    context = _context()  # the empty extraction that caused the bug
    assert gate.has_scope(context, question)
    assert gate.missing_mandatory_filters(context, question) == []


def test_a_year_alone_is_enough_scope_to_run(gate):
    assert gate.has_scope(_context(), "How did premium move in 2024?")


def test_a_named_carrier_is_enough_even_with_no_year(knows_values):
    assert knows_values.has_scope(_context(), "How is Zurich performing?")


def test_a_named_country_is_enough_even_with_no_carrier(knows_values):
    assert knows_values.has_scope(_context(), "How does the Singapore book look?")


# --------------------------------------------------------------------------- #
# The gate still does its job
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("question", [
    "how are things going?",
    "what should I look at?",
    "give me a summary",
    "",
])
def test_a_question_naming_nothing_still_clarifies(gate, question):
    """The gate exists for these; the fix must not disarm it."""
    assert not gate.has_scope(_context(), question)
    assert [r.role for r in gate.missing_mandatory_filters(_context(), question)] == [
        "carrier", "country",
    ]


def test_a_number_that_is_not_a_year_does_not_count_as_scope(gate):
    assert not gate.has_scope(_context(), "show me the top 10 lines")
    assert not gate.has_scope(_context(), "what about the 500 largest clients?")


def test_the_extraction_is_still_believed_when_it_works(gate):
    """The question is a fallback, not a replacement."""
    extracted = _context(entities=QueryEntities(carriers=["AXA"]))
    assert gate.has_scope(extracted, "")


def test_an_unresolvable_warehouse_does_not_force_a_clarification():
    """A matcher that raises means "cannot tell", never "no scope"."""
    def explode(flow, column, text):
        raise RuntimeError("no warehouse")

    gate = MandatoryFilterGate(matcher=explode)
    # The year still carries it, and nothing propagates the error.
    assert gate.has_scope(_context(), "How did AXA do in 2025?")


def test_the_real_matcher_tolerates_a_missing_warehouse():
    """The shipped matcher is the one that must not raise in production."""
    from core.agents.common.mandatory_filters import _fuzzy_matcher

    assert _fuzzy_matcher("nonexistent_flow", "Nonexistent_Column", "AXA") is False


# --------------------------------------------------------------------------- #
# Through the clarify node
# --------------------------------------------------------------------------- #


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


def _decide(question: str, context: RoutingContext):
    from core.graph.hitl import (
        MandatoryFilterSource,
        UnresolvedEntitySource,
        clarify_decide,
    )

    # The LLM ambiguity source is omitted: it needs credentials, and this is a
    # test about the deterministic gate in front of it.
    sources = (MandatoryFilterSource(), UnresolvedEntitySource())
    out = clarify_decide(
        {"messages": [_Message(question)], "routing_context": context},
        sources=sources,
    )
    return [q["id"] for q in (out.get("clarify_questions") or [])]


def test_the_node_lets_a_specified_question_straight_through():
    assert _decide(
        "Explain the performance of AXA in singapore for the year 2025?", _context()
    ) == []


def test_the_node_still_stops_an_unscoped_question():
    assert _decide("how are things going?", _context()) == [
        "mandatory:carrier", "mandatory:country",
    ]


def test_a_fallback_turn_never_clarifies():
    assert _decide("anything at all", _context(table_family="fallback")) == []
