"""End-to-end mapping: what the analyst subgraph returns -> what the UI shows.

`answer_table` is unit-tested in `test_answer_table.py`; this covers the wiring —
that `primary_lens` survives the subgraph boundary and that the state fields the
chat transcript renders (`gpr_query_result`, `survey_query_result`) carry the
answer's table rather than the first solver to finish.
"""
from __future__ import annotations

import pytest

from core.agents import analyst_agent as module


PEER_LOOKUP = {
    "flow": "gpr",
    "lens": "peer_benchmark",
    "sql": "SELECT DISTINCT Overall_Peer_Group FROM Peers WHERE LOWER(Carrier)='zurich group'",
    "rows": [{"Overall_Peer_Group": "AIG"}, {"Overall_Peer_Group": "CHUBB"}],
}
PREMIUM_ANSWER = {
    "flow": "gpr",
    "lens": "direct_answer",
    "sql": "SELECT Year, SUM(Premium) AS Total_Premium FROM GPR GROUP BY Year",
    "rows": [{"Year": 2025, "Total_Premium": 12_400_000}],
}
SURVEY_ANSWER = {
    "flow": "survey",
    "lens": "direct_answer",
    "sql": "SELECT Attribute, AVG(Score) AS Avg_Score FROM Survey GROUP BY Attribute",
    "rows": [{"Attribute": "Claims", "Avg_Score": 7.9}, {"Attribute": "Pricing", "Avg_Score": 6.4}],
}


class _FakeSubgraph:
    """Stands in for the compiled subgraph — no LLM, no database."""

    def __init__(self, result):
        self._result = result

    @property
    def AnalystAgent(self):
        return self

    def invoke(self, _payload):
        return self._result


@pytest.fixture
def run_turn(monkeypatch):
    def _run(result, *, route="premium"):
        monkeypatch.setattr(module, "_subgraph", _FakeSubgraph(result))

        class _Msg:
            content = "What was Zurich's premium in Canada in 2025 versus peers?"

        return module.analyst_agent_node({"current_route": route, "messages": [_Msg()]})

    return _run


def test_premium_table_is_the_premium_leg_not_the_peer_lookup(run_turn):
    state = run_turn(
        {
            "answer": "Zurich wrote **$12.4M**.",
            # Peer lookup first: exactly the order that used to win the race.
            "evidence": [PEER_LOOKUP, PREMIUM_ANSWER],
            "charts": [],
            "primary_lens": "direct_answer",
        }
    )
    assert state["gpr_query_result"] == PREMIUM_ANSWER["rows"]


def test_no_peer_name_reaches_the_shown_table(run_turn):
    state = run_turn(
        {
            "answer": "…",
            "evidence": [PEER_LOOKUP, PREMIUM_ANSWER],
            "charts": [],
            "primary_lens": "direct_answer",
        }
    )
    shown = " ".join(str(v) for row in state["gpr_query_result"] for v in row.values())
    assert "AIG" not in shown and "CHUBB" not in shown


def test_both_route_picks_a_table_per_flow(run_turn):
    state = run_turn(
        {
            "answer": "…",
            "evidence": [PEER_LOOKUP, SURVEY_ANSWER, PREMIUM_ANSWER],
            "charts": [],
            "primary_lens": "direct_answer",
        },
        route="both",
    )
    assert state["gpr_query_result"] == PREMIUM_ANSWER["rows"]
    assert state["survey_query_result"] == SURVEY_ANSWER["rows"]


def test_full_evidence_still_rides_along_for_the_boardroom(run_turn):
    """Narrowing the SHOWN table must not narrow what the digest can use."""
    state = run_turn(
        {
            "answer": "…",
            "evidence": [PEER_LOOKUP, PREMIUM_ANSWER],
            "charts": [],
            "primary_lens": "direct_answer",
        }
    )
    assert state["analyst_evidence"] == [PEER_LOOKUP, PREMIUM_ANSWER]


def test_a_subgraph_without_primary_lens_still_answers(run_turn):
    """Older checkpoints / a plan-less turn: fall back to shape alone."""
    state = run_turn(
        {"answer": "…", "evidence": [PEER_LOOKUP, PREMIUM_ANSWER], "charts": []}
    )
    assert state["gpr_query_result"] == PREMIUM_ANSWER["rows"]


def test_a_failed_turn_still_returns_the_route_fields(run_turn):
    state = run_turn({"answer": "", "evidence": [], "charts": []})
    assert state["gpr_query_result"] == []
    assert "couldn't complete" in state["gpr_response"]
