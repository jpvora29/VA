"""Lookup, survey and hybrid answers pass through the same verify gate as the analyst."""

from __future__ import annotations

from core.answers.grounded import GroundedAnswer
from core.answers.response_pipeline import verify_response


def _answer(text):
    return GroundedAnswer(text, (), (), False)


def test_a_lookup_answer_loses_its_unhedged_causal_claim():
    gate = verify_response(
        _answer("Premium fell 250. The decline was caused by rate cuts."),
        (),
        route="gpr_response",
    )
    assert "caused by" not in gate.text
    assert gate.text.startswith("Premium fell 250.")
    assert gate.record["content"] == gate.text
    assert gate.record["verification"]


def test_a_lookup_answer_on_a_narrowed_scope_states_it():
    evidence = (
        {
            "flow": "gpr",
            "rows": [{"a": 1}],
            "scope": {"Country": "Singapore"},
            "actual_scope": {},
        },
    )
    gate = verify_response(_answer("Premium was 250."), evidence, route="gpr_response")
    assert gate.text == "Premium was 250."
    assert gate.record["limitations"]


def test_a_clean_lookup_answer_is_untouched():
    gate = verify_response(_answer("Premium was 250."), (), route="gpr_response")
    assert gate.record is None and gate.text == "Premium was 250."


# --------------------------------------------------------------------------- #
# Follow-ups inherit what the previous answer was computed on
# --------------------------------------------------------------------------- #


def test_a_follow_up_hands_the_previous_turns_resolved_scope_to_the_filler():
    import json

    from core.agents.context_filler import prior_turn_scope

    state = {
        "routing_context": {
            "resolved_filters": {"Country": ["Singapore"], "Carrier_Group": ["ZURICH"]}
        }
    }
    assert json.loads(prior_turn_scope(state, is_follow_up=True)) == {
        "Carrier_Group": ["ZURICH"],
        "Country": ["Singapore"],
    }


def test_a_first_turn_inherits_nothing_even_from_a_stale_checkpoint():
    from core.agents.context_filler import prior_turn_scope

    state = {"routing_context": {"resolved_filters": {"Country": ["Japan"]}}}
    assert prior_turn_scope(state, is_follow_up=False) == "{}"


# --------------------------------------------------------------------------- #
# An answer carries the id of the run that produced it
# --------------------------------------------------------------------------- #


def test_only_this_turns_answers_get_the_turn_id():
    from ui.chat_turn import stamp_turn_id

    transcript = {
        "messages": [
            {"type": "HumanMessage", "content": "q1"},
            {"type": "AIMessage", "content": "a1", "turn_id": "old"},
            {"type": "HumanMessage", "content": "q2"},
            {"type": "AIMessage", "content": "a2"},
        ]
    }
    stamp_turn_id(transcript, 2, "job-2")
    assert [m.get("turn_id") for m in transcript["messages"]] == [
        None,
        "old",
        None,
        "job-2",
    ]
