"""Tests for the conversation meta-intent slice of the query contract.

"Summarize our discussion" / "what did you recommend earlier?" must be answered
from the persisted transcript with NO new database query: a deterministic
detector sets `RoutingContext.conversation_intent`, the graph short-circuits to
the transcript handler, and that handler reuses the prose-only fallback render.

Run:  pytest tests/test_meta_intent.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents.common.meta_intent import (
    conversation_intent_of,
    detect_conversation_intent,
    is_meta_intent,
)
from core.schemas.routing import RoutingContext


# ── deterministic detector ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Summarize our discussion",
        "Can you recap this conversation?",
        "sum up the chat so far",
        "give me a summary",
        "write me a quick tldr",
        "what have we discussed?",
        "what have we covered so far",
    ],
)
def test_detect_summarize(query):
    assert detect_conversation_intent(query) == "summarize_chat"


@pytest.mark.parametrize(
    "query",
    [
        "What did you recommend earlier?",
        "what did we conclude?",
        "what were your recommendations",
        "what decisions have we made so far?",
        "remind me what we found",
        "what did we talk about?",
    ],
)
def test_detect_recall(query):
    assert detect_conversation_intent(query) == "recall_previous"


@pytest.mark.parametrize(
    "query",
    [
        "What is Zurich's premium in Canada in 2024?",
        "Why did premium decline?",
        "What do you recommend for the Cyber book?",  # present tense = fresh ask
        "Compare Chubb vs peers by product.",
        "Show me a chart of NPS by year.",
    ],
)
def test_detect_neutral_not_meta(query):
    assert detect_conversation_intent(query) is None


# ── helpers over RoutingContext ──────────────────────────────────────────────


def _ctx(intent: str) -> RoutingContext:
    return RoutingContext(
        table_family="premium",
        intent_type="followup",
        conversation_intent=intent,
    )


def test_conversation_intent_of_and_is_meta():
    assert conversation_intent_of(_ctx("summarize_chat")) == "summarize_chat"
    assert conversation_intent_of(_ctx("summarize_chat").model_dump()) == "summarize_chat"
    assert is_meta_intent(_ctx("summarize_chat")) is True
    assert is_meta_intent(_ctx("recall_previous")) is True
    assert is_meta_intent(_ctx("analyze")) is False
    # Safe defaults on missing/legacy shapes.
    assert conversation_intent_of(None) == "analyze"
    assert is_meta_intent({}) is False
    legacy = RoutingContext(table_family="premium", intent_type="new_question")
    assert is_meta_intent(legacy) is False  # default 'analyze'


# ── graph router short-circuit ───────────────────────────────────────────────


def test_after_context_filler_routes_meta_to_conversation_node():
    from core.graph.main import _after_context_filler

    assert _after_context_filler({"routing_context": _ctx("summarize_chat")}) == "conversation_node"
    assert _after_context_filler({"routing_context": _ctx("recall_previous")}) == "conversation_node"
    assert _after_context_filler({"routing_context": _ctx("analyze")}) == "clarify_decide"
    assert _after_context_filler({}) == "clarify_decide"


# ── transcript formatting (pure) ─────────────────────────────────────────────


def test_format_transcript_keeps_both_sides_and_drops_artifacts():
    from core.agents.conversation import _format_transcript

    chat = {
        "messages": [
            {"type": "HumanMessage", "content": "Zurich premium in Canada?"},
            {"type": "AIMessage", "content": "Premium was $57.6M, down 9% YoY."},
            {"type": "SQLOutputForCharts", "chart_data": {"chart_type": "bar"}},
            {"type": "HumanMessage", "content": "And vs peers?"},
            {"type": "AIMessage", "content": "About 8% below the peer average."},
        ]
    }
    out = _format_transcript(chat)
    assert "User: Zurich premium in Canada?" in out
    assert "Analyst: Premium was $57.6M, down 9% YoY." in out
    assert "Analyst: [chart]" in out
    assert "Analyst: About 8% below the peer average." in out


def test_format_transcript_empty():
    from core.agents.conversation import _format_transcript

    assert _format_transcript(None) == ""
    assert _format_transcript({"messages": []}) == ""


# ── conversation node ────────────────────────────────────────────────────────


def _state(intent: str, content: str = "summarize our discussion") -> dict:
    return {
        "messages": [type("M", (), {"content": content})()],
        "routing_context": _ctx(intent),
        "user_id": "1",
        "thread_id": "t-123",
    }


def test_conversation_node_empty_transcript_skips_llm(monkeypatch):
    from core.agents import conversation as conv

    monkeypatch.setattr(conv, "load_conversation", lambda u, t: None)

    def _boom(messages):
        raise AssertionError("must not call the LLM when there is no transcript")

    monkeypatch.setattr(conv.Initialization, "llm_creative", type("L", (), {"invoke": staticmethod(_boom)}))

    out = conv.conversation_node(_state("summarize_chat"))
    assert out["current_route"] == "fallback"
    assert out["followup_questions"] == []
    assert "nothing to summarize" in out["out_of_scope_answer"].lower()


def test_conversation_node_summarizes_from_transcript(monkeypatch):
    from core.agents import conversation as conv

    chat = {
        "messages": [
            {"type": "HumanMessage", "content": "Zurich premium in Canada?"},
            {"type": "AIMessage", "content": "Premium $57.6M, down 9% YoY; share loss."},
        ]
    }
    monkeypatch.setattr(conv, "load_conversation", lambda u, t: chat)

    captured = {}

    class _Resp:
        content = "### Key findings\nZurich premium fell **9%**."

    def _invoke(messages):
        captured["system"] = messages[0].content
        captured["human"] = messages[1].content
        return _Resp()

    monkeypatch.setattr(conv.Initialization, "llm_creative", type("L", (), {"invoke": staticmethod(_invoke)}))

    out = conv.conversation_node(_state("summarize_chat"))
    assert out["current_route"] == "fallback"
    assert out["followup_questions"] == []
    assert out["out_of_scope_answer"] == "### Key findings\nZurich premium fell **9%**."
    # The transcript reached the model; the summarize contract was used.
    assert "Premium $57.6M, down 9% YoY" in captured["human"]
    assert "summarize the conversation" in captured["system"].lower()


def test_conversation_node_recall_uses_recall_contract(monkeypatch):
    from core.agents import conversation as conv

    monkeypatch.setattr(
        conv, "load_conversation",
        lambda u, t: {"messages": [{"type": "AIMessage", "content": "Recommend defending Property."}]},
    )
    captured = {}

    class _Resp:
        content = "You recommended defending Property."

    def _invoke(messages):
        captured["system"] = messages[0].content
        return _Resp()

    monkeypatch.setattr(conv.Initialization, "llm_creative", type("L", (), {"invoke": staticmethod(_invoke)}))

    out = conv.conversation_node(_state("recall_previous", "what did you recommend earlier?"))
    assert out["out_of_scope_answer"] == "You recommended defending Property."
    assert "recall something from earlier" in captured["system"].lower()
