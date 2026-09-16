"""An answer must not refuse beside evidence it drew a chart from.

The reported failure: a turn returned "cannot produce insights as numbers do not
match" while rendering charts from the very same evidence — after three or four
minutes of waiting.

Two separate all-or-nothing paths caused it:

  * one disagreeing pair of figures discarded EVERY figure the turn established,
    including the ones nothing disagreed about;
  * rows that carried no verifiable measure produced "no usable numeric evidence"
    even when a populated table sat directly underneath the sentence.

Both are now partial answers with a stated limitation. The principle these tests
hold the code to: if there is enough evidence to draw a chart, there is enough to
say something true about it.
"""
from __future__ import annotations

import pytest

from core.answers.comparison_inputs import build_answer_fact_pack
from core.answers.grounded import AnswerRequest, compose_answer, validate_record


def _set(lens: str, rows: list) -> dict:
    return {"flow": "gpr", "lens": lens, "sql": f"-- {lens}", "rows": rows}


CONFLICTING = [
    _set("a", [{"Product_Line": "Property", "Premium": 900.0}]),
    _set("b", [{"Product_Line": "Property", "Premium": 950.0}]),
    _set("c", [{"Product_Line": "Cyber", "Premium": 190.0},
               {"Product_Line": "Marine", "Premium": 500.0}]),
]


# --------------------------------------------------------------------------- #
# A conflict is scoped to what actually conflicts
# --------------------------------------------------------------------------- #


def test_the_pack_names_which_identity_is_disputed():
    pack = build_answer_fact_pack(CONFLICTING)
    assert pack.conflicted
    assert any("Property" in label for label in pack.disputed_labels())


def test_the_undisputed_figures_survive():
    usable = build_answer_fact_pack(CONFLICTING).usable()
    values = sorted(fact.value for fact in usable.facts)
    assert values == [190.0, 500.0]


def test_a_pack_with_no_conflict_is_returned_unchanged():
    pack = build_answer_fact_pack([_set("a", [{"Product_Line": "Cyber", "Premium": 190.0}])])
    assert pack.usable() is pack


# --------------------------------------------------------------------------- #
# The answer is written from what survived
# --------------------------------------------------------------------------- #


def test_a_disagreement_about_one_figure_does_not_discard_the_others():
    answer = compose_answer(AnswerRequest("How is the book split?", tuple(CONFLICTING)))
    assert "cannot give a reliable numerical answer" not in answer.text
    assert "Cyber" in answer.text


def test_what_was_excluded_is_stated_rather_than_hidden():
    answer = compose_answer(AnswerRequest("How is the book split?", tuple(CONFLICTING)))
    assert answer.limitations
    assert "disagreed" in answer.limitations[0]
    assert "Property" in answer.limitations[0]


def test_the_disputed_figure_itself_is_not_quoted():
    """Reporting one of two disagreeing values would be picking a winner."""
    answer = compose_answer(AnswerRequest("How is the book split?", tuple(CONFLICTING)))
    assert "900" not in answer.text and "950" not in answer.text


def test_a_partial_answer_still_verifies_as_a_stored_record():
    answer = compose_answer(AnswerRequest("How is the book split?", tuple(CONFLICTING)))
    assert validate_record(answer.as_dict(), answer.text, CONFLICTING)


def test_a_record_using_a_disputed_figure_is_still_rejected():
    """The relaxation must not let a contested number through."""
    from dataclasses import replace

    answer = compose_answer(AnswerRequest("How is the book split?", tuple(CONFLICTING)))
    pack = build_answer_fact_pack(CONFLICTING)
    disputed = next(
        fact for fact in pack.facts
        if (fact.metric, fact.unit, fact.dimensions) in set(pack.conflicted)
    )
    record = answer.as_dict()
    record["facts"] = record["facts"] + [disputed.as_dict()]
    assert not validate_record(record, answer.text, CONFLICTING)


def test_everything_conflicting_still_refuses():
    """A turn where nothing survives has genuinely nothing to say."""
    both = [
        _set("a", [{"Product_Line": "Property", "Premium": 900.0}]),
        _set("b", [{"Product_Line": "Property", "Premium": 950.0}]),
    ]
    answer = compose_answer(AnswerRequest("q", tuple(both)))
    assert "cannot give a reliable numerical answer" in answer.text
    assert answer.limitations


# --------------------------------------------------------------------------- #
# Rows that carry no verifiable measure
# --------------------------------------------------------------------------- #


NON_NUMERIC = [_set("a", [{"Product_Line": "Property", "Status": "active"},
                          {"Product_Line": "Cyber", "Status": "active"}])]


def test_rows_with_no_measure_point_the_reader_at_the_table():
    answer = compose_answer(AnswerRequest("q", tuple(NON_NUMERIC)))
    assert "2 rows" in answer.text
    assert "shown below" in answer.text


def test_that_is_not_the_same_message_as_nothing_came_back():
    """A populated table under "no evidence" is what made the answer look broken."""
    retrieved = compose_answer(AnswerRequest("q", tuple(NON_NUMERIC))).text
    empty = compose_answer(AnswerRequest("q", ())).text
    assert retrieved != empty
    assert "no usable numeric evidence" in empty


def test_an_unusable_result_carries_its_limitation():
    answer = compose_answer(AnswerRequest("q", tuple(NON_NUMERIC)))
    assert answer.limitations
    assert answer.limitation == "No verifiable figures"


def test_a_single_row_is_described_in_the_singular():
    single = [_set("a", [{"Product_Line": "Property", "Status": "active"}])]
    assert "1 row " in compose_answer(AnswerRequest("q", tuple(single))).text


# --------------------------------------------------------------------------- #
# The principle
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("evidence", [CONFLICTING, NON_NUMERIC])
def test_evidence_good_enough_to_chart_always_produces_some_prose(evidence):
    """If a chart can be drawn from it, the answer must say something about it."""
    answer = compose_answer(AnswerRequest("q", tuple(evidence)))
    assert answer.text.strip()
    assert len(answer.text.split()) > 5


# --------------------------------------------------------------------------- #
# The distinction that keeps the relaxation safe
# --------------------------------------------------------------------------- #


def _self_contradicting():
    """A stated growth rate its own operands do not produce: 100 -> 150 is +50%."""
    return ({"flow": "gpr", "rows": [{"YoY_%": 90}], "facts": [{
        "name": "yoy", "column": "YoY_%", "value": 90, "unit": "%",
        "dims": {"year": 2025},
        "support": [{"yr": 2025, "prior_year": 2024, "measure_name": "Premium",
                     "prev": 100, "measure": 150}]}]},)


def test_a_calculation_contradicting_its_own_operands_fails_closed():
    """Nothing is salvageable by dropping a slice — the arithmetic itself is wrong."""
    answer = compose_answer(AnswerRequest("q", _self_contradicting()))
    assert not answer.claims
    assert answer.limitation == "Conflicting evidence"
    assert "cannot give a reliable numerical answer" in answer.text


def test_the_two_kinds_of_conflict_are_told_apart():
    """One is two sources disagreeing about a slice; the other is corrupt math."""
    contested = build_answer_fact_pack(CONFLICTING)
    corrupt = build_answer_fact_pack(_self_contradicting())
    assert contested.conflicted        # names the disputed identity -> partial answer
    assert corrupt.conflicts           # flagged...
    assert not corrupt.conflicted      # ...but with nothing to drop -> fail closed
