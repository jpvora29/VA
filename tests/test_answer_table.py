"""The answer's table is chosen by shape, not by which solver finished first.

The bug these cover: parallel lenses merge through an add-reducer, so the old
"first non-empty result set for this flow" rule surfaced whichever query won the
race — routinely the peer-membership lookup, which is why a premium question came
back showing a list of peer carrier names and no premium.
"""
from __future__ import annotations

from core.agents.analyst.answer_table import (
    score_evidence,
    select_answer_evidence,
    select_answer_rows,
)

PEER_LOOKUP = {
    "flow": "gpr",
    "lens": "peer_benchmark",
    "sql": "SELECT DISTINCT Overall_Peer_Group FROM Peers WHERE LOWER(Carrier)='zurich group'",
    "rows": [
        {"Overall_Peer_Group": "AIG"},
        {"Overall_Peer_Group": "CHUBB"},
        {"Overall_Peer_Group": "AXA XL"},
    ],
}

PREMIUM_ANSWER = {
    "flow": "gpr",
    "lens": "direct_answer",
    "sql": "SELECT Year, SUM(Premium) AS Total_Premium FROM GPR WHERE ... GROUP BY Year",
    "rows": [
        {"Year": 2024, "Total_Premium": 11_200_000},
        {"Year": 2025, "Total_Premium": 12_400_000},
    ],
}

COMPUTED_PEER_AVG = {
    "flow": "gpr",
    "lens": "peer_benchmark",
    "sql": "-- computed: compute_peer_average_total(metric=Premium, filters={...})",
    "rows": [{"peer_average": 9_800_000, "peers": 6}],
}

SURVEY_SCORE = {
    "flow": "survey",
    "lens": "perception",
    "sql": "SELECT Attribute, AVG(Score) AS Avg_Score FROM Survey GROUP BY Attribute",
    "rows": [{"Attribute": "Claims", "Avg_Score": 7.9}, {"Attribute": "Pricing", "Avg_Score": 6.4}],
}


# ── the bug ──────────────────────────────────────────────────────────────────

def test_peer_name_lookup_never_becomes_the_answer_table():
    """The regression: this list arriving first used to BE the shown table."""
    evidence = [PEER_LOOKUP, PREMIUM_ANSWER]
    assert select_answer_rows(evidence, "gpr") == PREMIUM_ANSWER["rows"]


def test_choice_does_not_depend_on_solver_finish_order():
    forward = [PEER_LOOKUP, PREMIUM_ANSWER, COMPUTED_PEER_AVG]
    assert select_answer_rows(forward, "gpr") == select_answer_rows(
        list(reversed(forward)), "gpr"
    )


def test_ties_break_deterministically():
    """Two equally-shaped sets must still resolve the same way every run."""
    twin = dict(PREMIUM_ANSWER, sql=PREMIUM_ANSWER["sql"].replace("Year", "Quarter"))
    pair = [PREMIUM_ANSWER, twin]
    assert select_answer_evidence(pair, "gpr") is select_answer_evidence(
        list(reversed(pair)), "gpr"
    )


# ── the scoring rules ────────────────────────────────────────────────────────

def test_a_computed_metric_beats_hand_written_sql():
    assert score_evidence(COMPUTED_PEER_AVG) > score_evidence(PREMIUM_ANSWER)


def test_the_primary_lens_wins_among_comparable_sets():
    trend = dict(PREMIUM_ANSWER, lens="temporal_trend")
    breakdown = dict(PREMIUM_ANSWER, lens="dimensional_breakdown", sql="SELECT b ...")
    picked = select_answer_evidence(
        [breakdown, trend], "gpr", primary_lens="temporal_trend"
    )
    assert picked is trend


def test_a_discovery_query_scores_below_a_real_result():
    assert score_evidence(PEER_LOOKUP) < score_evidence(PREMIUM_ANSWER)


def test_a_row_dump_loses_to_a_readable_table():
    dump = dict(
        PREMIUM_ANSWER,
        sql="SELECT * FROM GPR",
        rows=[{"Carrier_Group": f"C{i}", "Premium": i} for i in range(500)],
    )
    assert score_evidence(dump) < score_evidence(PREMIUM_ANSWER)


# ── flow scoping + empties ───────────────────────────────────────────────────

def test_each_flow_gets_its_own_table():
    evidence = [PEER_LOOKUP, PREMIUM_ANSWER, SURVEY_SCORE]
    assert select_answer_rows(evidence, "gpr") == PREMIUM_ANSWER["rows"]
    assert select_answer_rows(evidence, "survey") == SURVEY_SCORE["rows"]


def test_no_evidence_for_a_flow_is_an_empty_table():
    assert select_answer_rows([SURVEY_SCORE], "gpr") == []
    assert select_answer_rows([], "gpr") == []
    assert select_answer_evidence([], "gpr") is None


def test_empty_result_sets_are_never_chosen():
    empty = {"flow": "gpr", "lens": "direct_answer", "sql": "SELECT 1", "rows": []}
    assert select_answer_rows([empty, PREMIUM_ANSWER], "gpr") == PREMIUM_ANSWER["rows"]
    assert score_evidence(empty) == 0.0
