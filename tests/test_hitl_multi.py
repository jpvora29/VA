"""Tests for multi-question HITL clarification.

The clarify gate now carries a LIST of questions: deterministic "did you mean"
MCQs from the query contract's unresolved entity terms, plus the conservative
LLM ambiguity question. On resume, entity answers are written back into
`routing_context.resolved_filters`.

Run:  pytest tests/test_hitl_multi.py -q -o pythonpath=.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage

import core.graph.hitl as hitl
from core.schemas.hitl import ClarifyDecision, ClarifyOption, ClarifyQuestion
from core.schemas.routing import RoutingContext, UnresolvedTerm


def _ctx(unresolved=(), resolved=None) -> RoutingContext:
    return RoutingContext(
        table_family="premium",
        intent_type="new_question",
        unresolved_terms=list(unresolved),
        resolved_filters=dict(resolved or {}),
    )


class _StubDecider:
    """Stands in for the LLM ambiguity classifier."""

    def __init__(self, decision: ClarifyDecision) -> None:
        self._decision = decision

    def __call__(self, **_kwargs) -> ClarifyDecision:
        return self._decision


_NO_ASK = ClarifyDecision(needs_clarification=False, reason="clear")


def _suggestions(monkeypatch, mapping):
    monkeypatch.setattr(
        "core.mcp.tools.match_column_values",
        lambda flow, column, term, **kw: mapping.get(term.lower(), []),
    )


# ── clarify_decide: question assembly ────────────────────────────────────────


def test_unresolved_term_becomes_did_you_mean_question(monkeypatch):
    _suggestions(monkeypatch, {"uk": ["United Kingdom", "Ukraine"]})
    monkeypatch.setattr(hitl, "_CLARIFY_DECIDER", _StubDecider(_NO_ASK))
    state = {
        "messages": [HumanMessage(content="Zurich premium in UK", id="m1")],
        "routing_context": _ctx(
            [UnresolvedTerm(kind="country", term="UK", column="Country", flow="gpr")]
        ),
    }
    out = hitl.clarify_decide(state)
    questions = out["clarify_questions"]
    assert len(questions) == 1
    q = questions[0]
    assert q["kind"] == "unresolved_entity"
    assert "UK" in q["question"]
    assert [o["label"] for o in q["options"]] == ["United Kingdom", "Ukraine"]
    assert (q["column"], q["flow"], q["term"]) == ("Country", "gpr", "UK")


def test_term_without_suggestions_is_skipped(monkeypatch):
    _suggestions(monkeypatch, {})
    monkeypatch.setattr(hitl, "_CLARIFY_DECIDER", _StubDecider(_NO_ASK))
    state = {
        "messages": [HumanMessage(content="premium in Atlantis", id="m1")],
        "routing_context": _ctx(
            [UnresolvedTerm(kind="country", term="Atlantis", column="Country", flow="gpr")]
        ),
    }
    assert hitl.clarify_decide(state)["clarify_questions"] is None


def test_llm_question_joins_entity_questions(monkeypatch):
    _suggestions(monkeypatch, {"uk": ["United Kingdom"]})
    llm_q = ClarifyQuestion(
        question="Which metric — premium or share of wallet?",
        header="Metric",
        options=[ClarifyOption(label="Premium"), ClarifyOption(label="Share of wallet")],
    )
    monkeypatch.setattr(
        hitl,
        "_CLARIFY_DECIDER",
        _StubDecider(ClarifyDecision(needs_clarification=True, question=llm_q)),
    )
    state = {
        "messages": [HumanMessage(content="Zurich in UK", id="m1")],
        "routing_context": _ctx(
            [UnresolvedTerm(kind="country", term="UK", column="Country", flow="gpr")]
        ),
    }
    questions = hitl.clarify_decide(state)["clarify_questions"]
    assert [q["kind"] for q in questions] == ["unresolved_entity", "ambiguity"]


def test_llm_question_repeating_an_entity_is_dropped(monkeypatch):
    _suggestions(monkeypatch, {"uk": ["United Kingdom"]})
    llm_q = ClarifyQuestion(
        question="Did you mean the UK market or another one?",
        header="Market",
        options=[ClarifyOption(label="United Kingdom"), ClarifyOption(label="Ukraine")],
    )
    monkeypatch.setattr(
        hitl,
        "_CLARIFY_DECIDER",
        _StubDecider(ClarifyDecision(needs_clarification=True, question=llm_q)),
    )
    state = {
        "messages": [HumanMessage(content="Zurich in UK", id="m1")],
        "routing_context": _ctx(
            [UnresolvedTerm(kind="country", term="UK", column="Country", flow="gpr")]
        ),
    }
    questions = hitl.clarify_decide(state)["clarify_questions"]
    assert len(questions) == 1 and questions[0]["kind"] == "unresolved_entity"


def test_fallback_and_clean_turns_ask_nothing(monkeypatch):
    monkeypatch.setattr(hitl, "_CLARIFY_DECIDER", _StubDecider(_NO_ASK))
    fallback_state = {
        "messages": [HumanMessage(content="hello", id="m1")],
        "routing_context": RoutingContext(
            table_family="fallback", intent_type="new_question"
        ),
    }
    assert hitl.clarify_decide(fallback_state)["clarify_questions"] is None
    clean_state = {
        "messages": [HumanMessage(content="Zurich premium 2024", id="m1")],
        "routing_context": _ctx(),
    }
    assert hitl.clarify_decide(clean_state)["clarify_questions"] is None


# ── answer normalization + gate folding ──────────────────────────────────────


def test_normalize_answers_dict_and_legacy_string():
    questions = [{"id": "entity:country:uk"}, {"id": "llm:ambiguity"}]
    assert hitl._normalize_answers(
        {"entity:country:uk": "United Kingdom"}, questions
    ) == {"entity:country:uk": "United Kingdom"}
    # A bare string answers the FIRST question (legacy single-question contract).
    assert hitl._normalize_answers("United Kingdom", questions) == {
        "entity:country:uk": "United Kingdom"
    }
    assert hitl._normalize_answers("", questions) == {}


def test_gate_folds_answers_and_updates_resolved_filters(monkeypatch):
    questions = [
        {
            "id": "entity:country:uk",
            "kind": "unresolved_entity",
            "entity_kind": "country",
            "question": "I couldn't find country 'UK'. Did you mean one of these?",
            "term": "UK",
            "column": "Country",
            "flow": "gpr",
        },
        {
            "id": "llm:ambiguity",
            "kind": "ambiguity",
            "question": "Which metric?",
        },
    ]
    answers = {"entity:country:uk": "United Kingdom", "llm:ambiguity": "Premium"}
    monkeypatch.setattr(hitl, "interrupt", lambda payload: answers)

    ctx = _ctx(resolved={"Carrier_Group": ["ZURICH GROUP"]})
    state = {
        "messages": [HumanMessage(content="Zurich in UK", id="m1")],
        "clarify_questions": questions,
        "routing_context": ctx,
    }
    out = hitl.clarify_gate(state)

    assert out["clarify_questions"] is None
    assert "country 'UK' means 'United Kingdom'" in out["clarification"]
    assert "Which metric? -> Premium" in out["clarification"]
    new_msg = out["messages"][1]
    assert "User clarification" in new_msg.content
    # The entity answer became an exact contract filter value.
    assert out["routing_context"].resolved_filters == {
        "Carrier_Group": ["ZURICH GROUP"],
        "Country": ["United Kingdom"],
    }


def test_gate_passthrough_without_questions():
    assert hitl.clarify_gate({"clarify_questions": None}) == {}


# ── UI payload normalisation ─────────────────────────────────────────────────


def test_clarify_questions_of_wraps_flat_legacy_payload():
    from ui.components.chatbot import clarify_questions_of

    multi = {"kind": "clarify", "questions": [{"id": "a"}, {"id": "b"}]}
    assert [q["id"] for q in clarify_questions_of(multi)] == ["a", "b"]
    flat = {"kind": "custom_peer_mismatch", "question": "Which peers?", "options": []}
    wrapped = clarify_questions_of(flat)
    assert len(wrapped) == 1
    assert wrapped[0]["id"] == "q0"
    assert wrapped[0]["question"] == "Which peers?"
