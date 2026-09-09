"""The row under an answer: next steps, and what went wrong with it.

Two things that used to dead-end in the transcript. A conclusion had nowhere to
go — every next step lived in a workspace the user had to navigate to and retype
the finding into. And a thumbs-down recorded that an answer failed but nothing
about how, which is the only part anyone can act on.

These tests pin the parts that are pure: which actions apply to which answer, the
questions the re-ask actions send, the rows an export finds, the reason
vocabulary, and the seed a decision is drafted from.

Run:  pytest tests/test_answer_actions.py -q -o pythonpath=.
"""
from __future__ import annotations

import json

import pytest
from dash.development.base_component import Component

from core.memory.feedback_reasons import (
    FREE_TEXT_REASON,
    REASON_KEYS,
    REASONS,
    is_valid,
    reason_label,
)
from ui.components.answer_actions import (
    ACTIONS,
    AnswerContext,
    actions_for,
    answer_footer,
    feedback_panel,
    wants_note,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _walk(node):
    if isinstance(node, Component):
        yield node
        for child in node._traverse():
            if isinstance(child, Component):
                yield child
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item)


def _ids(node) -> list:
    return [
        c.id for c in _walk(node) if getattr(c, "id", None) is not None
    ]


def _action_keys(node) -> list[str]:
    return [
        cid["action"]
        for cid in _ids(node)
        if isinstance(cid, dict) and cid.get("type") == "answer-action"
    ]


def _analysis(**kw) -> AnswerContext:
    return AnswerContext(idx=1, question="Zurich in the UK", shape="analyst", **kw)


# ── which actions apply ──────────────────────────────────────────────────────


def test_a_full_analysis_offers_its_next_steps():
    keys = [a.key for a in actions_for(_analysis(has_rows=True))]
    assert keys == ["drivers", "export", "decision", "board"]


def test_a_bare_lookup_offers_no_next_steps():
    """"$12.4M" is an answer, not a finding — raising it as a decision is silly."""
    ctx = AnswerContext(idx=0, question="What was premium?", shape="direct")
    assert actions_for(ctx) == []


def test_export_appears_only_when_there_are_rows():
    assert "export" not in _action_keys(
        answer_footer(_analysis(has_rows=False), content="x")
    )
    assert "export" in _action_keys(
        answer_footer(_analysis(has_rows=True), content="x")
    )


def test_export_is_offered_even_on_a_bare_lookup_that_returned_rows():
    """Rows are rows; the shape gate is about findings, not about data."""
    ctx = AnswerContext(idx=0, shape="direct", has_rows=True)
    assert [a.key for a in actions_for(ctx)] == ["export"]


def test_actions_key_off_the_shape_not_the_markdown():
    """The insight-card heuristic counts H3s, and a comparison or briefing answer
    may legitimately have none. Gating on it would drop the actions from exactly
    the answers most worth acting on."""
    ctx = AnswerContext(idx=1, question="q", shape="comparison", is_insight=False)
    assert [a.key for a in actions_for(ctx)] == ["drivers", "decision", "board"]


def test_an_answer_from_before_this_shipped_still_gets_actions():
    """Older transcripts carry no stamped shape; fall back to the card heuristic."""
    ctx = AnswerContext(idx=1, question="q", shape="", is_insight=True)
    assert [a.key for a in actions_for(ctx)] == ["drivers", "decision", "board"]

    plain = AnswerContext(idx=1, question="q", shape="", is_insight=False)
    assert actions_for(plain) == []


def test_the_row_stays_short():
    """Four is the budget. A ten-button row is a row nobody reads."""
    assert len(ACTIONS) <= 4


# ── the rendered footer ──────────────────────────────────────────────────────


def test_the_footer_carries_copy_and_both_thumbs():
    footer = answer_footer(_analysis(has_rows=True), content="Premium fell 8%.")
    ratings = {
        cid["rating"]
        for cid in _ids(footer)
        if isinstance(cid, dict) and cid.get("type") == "msg-feedback"
    }
    assert ratings == {"up", "down"}
    assert any(
        type(c).__name__ == "Clipboard" and c.content == "Premium fell 8%."
        for c in _walk(footer)
    )


def test_an_actionless_footer_says_so_for_the_stylesheet():
    """No actions means no divider — CSS needs to know without counting children."""
    bare = answer_footer(AnswerContext(idx=0, shape="direct"), content="x")
    assert "is-bare" in bare.className
    full = answer_footer(_analysis(has_rows=True), content="x")
    assert "is-bare" not in full.className


def test_every_control_is_keyed_to_its_own_message():
    """Two answers on screen must not share a button."""
    first = _ids(answer_footer(_analysis(has_rows=True), content="a"))
    second = _ids(
        answer_footer(
            AnswerContext(idx=7, question="q", shape="analyst", has_rows=True),
            content="b",
        )
    )
    assert not {json.dumps(i, sort_keys=True) for i in first if isinstance(i, dict)} & {
        json.dumps(i, sort_keys=True) for i in second if isinstance(i, dict)
    }


# ── the feedback panel ───────────────────────────────────────────────────────


def test_the_panel_is_mounted_hidden_with_every_reason():
    panel = feedback_panel(3)
    assert panel.hidden is True
    offered = [
        cid["reason"]
        for cid in _ids(panel)
        if isinstance(cid, dict) and cid.get("type") == "fb-reason"
    ]
    assert offered == list(REASON_KEYS)


def test_the_panel_has_somewhere_to_write_a_correction():
    """The user's own words are the most valuable thing a downvote can carry."""
    kinds = {
        cid["type"]
        for cid in _ids(feedback_panel(0))
        if isinstance(cid, dict)
    }
    assert {"fb-note", "fb-send", "fb-ack", "fb-dismiss", "fb-panel"} <= kinds


# ── the reason vocabulary ────────────────────────────────────────────────────


def test_reasons_are_distinct_and_named():
    assert len(REASON_KEYS) == len(set(REASON_KEYS))
    assert all(r.label and r.icon and r.feeds for r in REASONS)


def test_the_roadmap_failure_modes_are_all_offered():
    """Scope, metric, period, evidence, clarity, chart, context — plus an escape."""
    assert {
        "wrong_scope",
        "wrong_metric",
        "wrong_period",
        "bad_evidence",
        "confusing",
        "bad_chart",
        "missing_context",
        FREE_TEXT_REASON,
    } == set(REASON_KEYS)


@pytest.mark.parametrize("key", [None, "", "nonsense", "WRONG_SCOPE "])
def test_only_known_reasons_are_accepted(key):
    assert is_valid(key) is (key == "WRONG_SCOPE ")


def test_reason_label_falls_back_to_the_raw_key():
    assert reason_label("wrong_period") == "Wrong period"
    assert reason_label("mystery") == "mystery"


def test_only_the_catch_all_reason_needs_the_user_to_write_something():
    assert wants_note(FREE_TEXT_REASON) is True
    assert wants_note("wrong_period") is False


# ── the pure halves of the callbacks ─────────────────────────────────────────


def test_the_drivers_action_asks_a_question_that_lands_on_the_driver_shape():
    from core.agents.common.answer_shape import detect_answer_shape
    from ui.callbacks import _driver_followup

    followup = _driver_followup("Zurich premium in the UK fell this year")
    assert detect_answer_shape(followup) == "driver"
    assert "Zurich premium in the UK" in followup


def test_the_drivers_action_still_asks_something_with_no_question_stored():
    from core.agents.common.answer_shape import detect_answer_shape
    from ui.callbacks import _driver_followup

    assert detect_answer_shape(_driver_followup("")) == "driver"


def test_export_finds_the_rows_that_belong_to_that_answer():
    from ui.callbacks import _rows_for_answer

    history = {
        "messages": [
            {"type": "HumanMessage", "content": "q1"},
            {"type": "AIMessage", "content": "a1"},
            {"type": "SQLOutputForCharts", "updated_query": [{"premium": 1}]},
            {"type": "HumanMessage", "content": "q2"},
            {"type": "AIMessage", "content": "a2"},
            {"type": "SQLOutputForCharts", "updated_query": [{"premium": 2}]},
        ]
    }
    assert _rows_for_answer(history, 1) == [{"premium": 1}]
    assert _rows_for_answer(history, 4) == [{"premium": 2}]


def test_export_finds_nothing_for_an_answer_with_no_rows():
    from ui.callbacks import _rows_for_answer

    history = {"messages": [{"type": "AIMessage", "content": "a"}]}
    assert _rows_for_answer(history, 0) == []
    assert _rows_for_answer(history, 99) == []
    assert _rows_for_answer(None, 0) == []


def test_a_decision_is_seeded_from_the_answer_not_invented():
    from ui.decisions.callbacks import seed_from_answer

    history = {
        "messages": [
            {"type": "HumanMessage", "content": "q"},
            {
                "type": "AIMessage",
                "content": "Cyber grew **$4.2M**, concentrated in Manufacturing.",
                "question": "How did cyber perform in the UK last year?",
            },
        ]
    }
    seed = seed_from_answer(history, 1)
    assert seed["title"] == "How did cyber perform in the UK last year"
    assert "$4.2M" in seed["rationale"]
    # Owner, status, priority and dates are business judgements the answer does
    # not contain, so they are left to the form's own defaults.
    assert set(seed) == {"title", "rationale"}


def test_a_long_question_is_trimmed_to_fit_a_board_card():
    from ui.decisions.callbacks import seed_from_answer

    question = "How did " + ("cyber premium in the United Kingdom " * 5) + "perform?"
    history = {
        "messages": [{"type": "AIMessage", "content": "x", "question": question}]
    }
    assert len(seed_from_answer(history, 0)["title"]) <= 80


def test_a_stale_index_seeds_a_blank_decision_rather_than_failing():
    from ui.decisions.callbacks import seed_from_answer

    assert seed_from_answer({"messages": []}, 3) is None
    assert seed_from_answer(None, 0) is None


# ── end to end: a finished turn becomes an actionable answer ─────────────────


def _rendered_actions(message, idx):
    from ui.components.chatbot import ai_message

    node = ai_message(
        message["content"],
        True,
        idx=idx,
        question=message.get("question", ""),
        route=message.get("route", ""),
        shape=message.get("shape", ""),
        has_rows=message.get("has_rows", False),
    )
    return _action_keys(node)


def test_a_committed_turn_renders_with_the_right_actions():
    """question -> stamped answer -> rendered footer, with no LLM in the path.

    This is the join everything else depends on: the graph's routing context
    supplies the shape, the transcript supplies the rows, and the footer offers
    exactly the steps that can actually run.
    """
    from ui.callbacks import _rows_for_answer, _stamp_answer_context

    history = {
        "messages": [
            {"type": "HumanMessage", "content": "Why did premium fall in Germany?"},
            {"type": "AIMessage", "content": "### The fall\nPremium fell **$2.7M**."},
            {
                "type": "SQLOutputForCharts",
                "updated_query": [{"country": "DE", "premium": 12}],
                "chart_data": {"chart_type": "bar"},
            },
        ]
    }
    state = {
        "current_route": "premium",
        "routing_context": {"output_directives": {"shape": "driver"}},
    }
    _stamp_answer_context(
        history, state, "Why did premium fall in Germany?", first_new=0
    )

    answer = history["messages"][1]
    assert answer["shape"] == "driver"
    assert answer["question"] == "Why did premium fall in Germany?"
    assert answer["route"] == "premium"
    assert answer["has_rows"] is True
    assert _rows_for_answer(history, 1) == [{"country": "DE", "premium": 12}]
    # "Create decision" leads, because it is the promoted step and the promoted
    # step is drawn first; the rest keep their declared order behind it.
    assert _rendered_actions(answer, 1) == ["decision", "drivers", "export", "board"]


def test_a_lookup_turn_renders_bare_even_though_it_returned_rows():
    from ui.callbacks import _stamp_answer_context

    history = {
        "messages": [
            {"type": "HumanMessage", "content": "What was Zurich's premium in 2024?"},
            {"type": "AIMessage", "content": "**$12.4M**, up from $11.1M."},
            {
                "type": "SQLOutputForCharts",
                "updated_query": [{"premium": 12.4}],
                "chart_data": {"chart_type": "bar"},
            },
        ]
    }
    state = {
        "current_route": "premium",
        "routing_context": {"output_directives": {"shape": "direct"}},
    }
    _stamp_answer_context(history, state, "What was Zurich's premium in 2024?", 0)
    assert _rendered_actions(history["messages"][1], 1) == ["export"]


def test_only_this_turns_answers_are_stamped():
    """A conversation saved before this shipped must not be relabelled with the
    current question — the reason the stamp is index-based, not field-based."""
    from ui.callbacks import _stamp_answer_context

    history = {
        "messages": [
            {"type": "HumanMessage", "content": "old question"},
            {"type": "AIMessage", "content": "old answer"},
            {"type": "HumanMessage", "content": "new question"},
            {"type": "AIMessage", "content": "new answer"},
        ]
    }
    state = {
        "current_route": "premium",
        "routing_context": {"output_directives": {"shape": "briefing"}},
    }
    _stamp_answer_context(history, state, "new question", first_new=2)

    assert "question" not in history["messages"][1]
    assert history["messages"][3]["question"] == "new question"
    assert history["messages"][3]["shape"] == "briefing"


def test_the_export_flag_agrees_with_what_export_would_find():
    """The button must never promise a download that then finds nothing."""
    from ui.callbacks import _rows_for_answer, _stamp_answer_context

    history = {
        "messages": [
            {"type": "HumanMessage", "content": "q"},
            {"type": "AIMessage", "content": "a"},
        ]
    }
    state = {
        "current_route": "premium",
        "routing_context": {"output_directives": {"shape": "analyst"}},
    }
    _stamp_answer_context(history, state, "q", 0)
    assert history["messages"][1]["has_rows"] is False
    assert _rows_for_answer(history, 1) == []
    assert "export" not in _rendered_actions(history["messages"][1], 1)


# ── what reaches episodic memory ─────────────────────────────────────────────


class _CapturingStore:
    """The real typed writers over a captured `remember` — no DB, no engine."""

    def __init__(self):
        from core.memory.episodic import SqliteEpisodicStore

        self.written = []
        self.store = SqliteEpisodicStore()
        self.store.remember = lambda user_id, episode: self.written.append(episode)


def test_a_diagnosed_downvote_stores_the_defect_not_just_the_mood():
    cap = _CapturingStore()
    cap.store.record_feedback(
        7,
        "conv-1",
        "down",
        "It should have used Q3, not the full year.",
        reason="wrong_period",
        question="How did cyber do this quarter?",
        route="premium",
        answer="Cyber wrote $12.4M in 2024.",
    )
    episode = cap.written[0]
    assert episode["kind"] == "feedback"
    assert episode["rating"] == "down"
    assert episode["route"] == "premium"
    assert episode["content"] == "It should have used Q3, not the full year."
    assert episode["meta"]["reason"] == "wrong_period"
    assert episode["meta"]["question"] == "How did cyber do this quarter?"
    assert episode["meta"]["answer"] == "Cyber wrote $12.4M in 2024."


def test_a_bare_rating_still_writes_and_carries_no_empty_meta():
    """The thumb is recorded the moment it is pressed, so a rating the user
    gives and then abandons is never lost."""
    cap = _CapturingStore()
    cap.store.record_feedback(7, "conv-1", "up")
    episode = cap.written[0]
    assert episode["rating"] == "up"
    assert episode["meta"] == {}


def test_a_very_long_answer_is_truncated_before_storage():
    cap = _CapturingStore()
    cap.store.record_feedback(
        7, "c", "down", "x", reason="confusing", answer="a" * 5000
    )
    assert len(cap.written[0]["meta"]["answer"]) == 1000


def test_corrections_are_the_downvotes_that_can_be_acted_on():
    from core.memory.episodic import SqliteEpisodicStore

    store = SqliteEpisodicStore()
    store._recent = lambda user_id, kind, limit: [
        {"rating": "up", "content": None, "meta": {}},
        {"rating": "down", "content": None, "meta": {}},          # no diagnosis
        {"rating": "down", "content": None, "meta": {"reason": "wrong_period"}},
        {"rating": "down", "content": "should have been Q3", "meta": {}},
    ]
    corrections = store.recent_corrections(7)
    assert len(corrections) == 2
    assert corrections[0]["meta"]["reason"] == "wrong_period"
    assert corrections[1]["content"] == "should have been Q3"
