"""Tests for the IntentClassifier node (Layer 2 of the analyst architecture).

The classifier finalizes the turn's intent on top of the context filler's
`routing_context`: it re-decides `analysis_depth` (dedicated classifier), folds
the deterministic directive detectors over the raw query, and flags conversation
meta-requests. It must NOT make table/column decisions — those stay downstream.

Run:  pytest tests/test_intent_classifier.py -q -o pythonpath=.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from core.agents import intent_classifier as ic
from core.schemas.routing import RoutingContext


@pytest.fixture(autouse=True)
def _no_op_usage(monkeypatch):
    """The node wraps the depth call in `Initialization.dspy_usage`, which needs a
    configured dspy LM. Tests inject a stub classifier, so neutralize the token
    tracker to a no-op context manager."""

    @contextmanager
    def _noop(*args, **kwargs):
        yield

    monkeypatch.setattr(ic.Initialization, "dspy_usage", _noop)


def _classifier(depth: str = "analytical") -> ic.IntentClassifier:
    """An IntentClassifier whose depth classifier is a stub returning `depth`."""
    return ic.IntentClassifier(depth_classifier=lambda **kwargs: depth)


def _state(query: str, *, history: list[str] | None = None) -> dict:
    messages: list = []
    for prior in history or []:
        messages.append(HumanMessage(content=prior))
        messages.append(AIMessage(content="…"))
    messages.append(HumanMessage(content=query))
    return {
        "messages": messages,
        "routing_context": RoutingContext(
            table_family="premium", intent_type="new_question"
        ),
    }


# ── depth re-decision ────────────────────────────────────────────────────────


def test_depth_classifier_overwrites_analysis_depth():
    state = _state("How is Zurich performing vs peers?")
    out = _classifier("analytical").classify_intent(state)
    assert out["routing_context"].analysis_depth == "analytical"


def test_fallback_family_skips_depth_call():
    state = _state("what's the weather?")
    state["routing_context"].table_family = "fallback"
    state["routing_context"].analysis_depth = "lookup"

    def _boom(**kwargs):
        raise AssertionError("depth classifier must not run for a fallback turn")

    out = ic.IntentClassifier(depth_classifier=_boom).classify_intent(state)
    assert out["routing_context"].analysis_depth == "lookup"


# ── directive overlay (fold) ─────────────────────────────────────────────────


def test_directive_overlay_suppresses_charts():
    state = _state("Zurich premium in Canada, no chart please")
    rc = _classifier().classify_intent(state)["routing_context"]
    assert rc.output_directives.charts == "none"
    assert rc.output_directives.source == "deterministic"


def test_directive_overlay_pins_charts_for_presentation():
    state = _state("just show me the visual for Zurich premium")
    rc = _classifier().classify_intent(state)["routing_context"]
    assert rc.output_directives.presentation == "chart_only"
    assert rc.output_directives.charts == "required"


def test_no_directive_leaves_defaults_untouched():
    state = _state("What is Zurich's premium in Canada in 2024?")
    rc = _classifier("lookup").classify_intent(state)["routing_context"]
    assert rc.output_directives.charts == "auto"
    assert rc.output_directives.source == ""


# ── conversation meta-intent ─────────────────────────────────────────────────


def test_meta_intent_only_fires_with_prior_conversation():
    # First turn: a meta phrase has nothing to recap -> stays 'analyze'.
    first = _state("summarize our discussion")
    rc_first = _classifier().classify_intent(first)["routing_context"]
    assert rc_first.conversation_intent == "analyze"

    # With prior turns, the same phrase becomes a meta request.
    later = _state("summarize our discussion", history=["Zurich premium?"])
    rc_later = _classifier().classify_intent(later)["routing_context"]
    assert rc_later.conversation_intent == "summarize_chat"


# ── defensive guard ──────────────────────────────────────────────────────────


def test_missing_routing_context_passes_through():
    assert _classifier().classify_intent({"messages": []}) == {}
