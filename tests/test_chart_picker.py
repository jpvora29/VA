"""Tests for the analyst chart-picker.

The picker ranks the gathered evidence, then the rule table in
`core.answers.chart_rules` decides each chart from the shape of its rows. There
is no model call, so a result set no rule fits produces no chart rather than a
guessed one, and every kept spec is a plain dict (JSON-safe for the chat-store).
"""
from __future__ import annotations

import json

import core.agents.analyst.chart_picker as cp


def _chartable_rows():
    return [
        {"Product": "Property", "Premium": 10},
        {"Product": "Casualty", "Premium": 20},
        {"Product": "Marine", "Premium": 15},
    ]


def _evidence(rows=None):
    return [{"flow": "gpr", "sql": "select 1", "rows": rows or _chartable_rows(), "lens": "mix"}]


def test_the_picker_makes_no_model_call():
    """The model chart node is gone from the picker entirely."""
    assert not hasattr(cp, "chart_node_for")


def test_rows_no_rule_fits_produce_no_chart():
    """Two points: the table says it better, so nothing is appended."""
    assert cp.pick_charts("breakdown by product", _evidence(_chartable_rows()[:2])) == []


def test_a_kept_chart_carries_its_rows_and_a_plain_spec():
    charts = cp.pick_charts("breakdown by product", _evidence())
    assert len(charts) == 1
    spec = charts[0]["chart_data"]
    assert spec["chart_type"] == "bar" and spec["rule"] == "ranking"
    assert charts[0]["rows"] == _chartable_rows()
    json.dumps(spec)  # JSON-safe for the chat-store


def test_the_title_is_written_from_the_columns():
    charts = cp.pick_charts("breakdown by product", _evidence())
    assert charts[0]["title"] == "Premium by product"


def test_the_requested_trend_is_charted_first_and_duplicates_are_dropped():
    """The trend is the chart the reader gets FIRST, and a second lens drawing
    the identical picture is dropped rather than shown twice."""
    trend = [{"Year": 2023, "Premium": 90}, {"Year": 2024, "Premium": 100}, {"Year": 2025, "Premium": 125}]
    evidence = [
        {"flow": "gpr", "lens": "mix", "sql": "mix", "rows": [{"Product": str(i), "Premium": i} for i in range(40)]},
        {"flow": "gpr", "lens": "trend", "sql": "trend", "rows": trend},
        {"flow": "gpr", "lens": "duplicate", "sql": "another query", "rows": trend},
    ]
    charts = cp.pick_charts("Show the premium trend over time", evidence)
    assert charts[0]["rows"] == trend
    assert charts[0]["chart_data"]["chart_type"] == "line"
    assert [c["rows"] for c in charts].count(trend) == 1


def test_harness_reads_nested_analyst_specs():
    from tests.golden.harness import _extract_charts
    result = _extract_charts({"analyst_charts": [{"rows": [], "chart_data": {"chart_type": "bar", "x": "Product", "y": ["Premium"]}}]})
    assert result == [{"type": "bar", "x": "Product", "y": ["Premium"], "series": []}]


# --------------------------------------------------------------------------- #
# Phase 8 — the chart answers the question the answer led with
# --------------------------------------------------------------------------- #

from core.agents.analyst.chart_picker import ChartFocus, _focus_alignment


def _ev(evidence_id, rows, lens="trend"):
    return {"flow": "gpr", "lens": lens, "sql": "s", "rows": rows,
            "evidence_id": evidence_id}


def test_the_evidence_the_answer_was_written_from_outranks_a_related_set():
    """Not "related to the answer" — this IS the answer."""
    focus = ChartFocus(evidence_ids=("ev_lead",))
    lead = _ev("ev_lead", [{"Year": 2024, "Premium": 1.0}])
    other = _ev("ev_other", [{"Year": 2024, "Premium": 1.0}])
    assert _focus_alignment(lead, focus) > _focus_alignment(other, focus)


def test_a_required_quarterly_comparison_is_preferred_when_both_years_are_present():
    """The motivating case: quarters across two years IS the required comparison."""
    focus = ChartFocus(requirements=("quarterly_comparison",))
    quarterly = _ev("ev_q", [{"period": "Q1", "2024": 425.0, "2025": 425.0},
                             {"period": "Q2", "2024": 425.0, "2025": 420.0}])
    products = _ev("ev_p", [{"Product_Line": "Property", "Premium": 900.0},
                            {"Product_Line": "Cyber", "Premium": 190.0}])
    assert _focus_alignment(quarterly, focus) > _focus_alignment(products, focus)


def test_a_single_year_quarterly_set_is_not_the_required_comparison():
    focus = ChartFocus(requirements=("quarterly_comparison",))
    one_year = _ev("ev_q", [{"period": "Q1", "Year": 2025, "Premium": 425.0},
                            {"period": "Q2", "Year": 2025, "Premium": 420.0}])
    assert _focus_alignment(one_year, focus) == 0.0


def test_evidence_about_the_leading_subject_scores_above_evidence_that_is_not():
    focus = ChartFocus(subject=(("Product_Line", "Property"),))
    on_subject = _ev("ev_a", [{"Product_Line": "Property", "Premium": 900.0}])
    off_subject = _ev("ev_b", [{"Product_Line": "Marine", "Premium": 500.0}])
    assert _focus_alignment(on_subject, focus) > _focus_alignment(off_subject, focus)


def test_no_focus_changes_no_ranking():
    """Every existing caller passes none, and must behave exactly as before."""
    assert _focus_alignment(_ev("ev", [{"Year": 2024, "Premium": 1.0}]), ChartFocus()) == 0.0
