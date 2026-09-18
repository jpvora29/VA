"""Tests for the analyst chart-picker's chartability gate.

Focus: the picker must reject specs whose `chart_type` is effectively "none"
(empty string / None / whitespace), using the SAME falsy-aware rule the renderer
(`ui.chart_functions`) applies. A mismatch previously let such specs through, so
the chart was appended here but rejected downstream as "data is scalar".
"""
from __future__ import annotations

import core.agents.analyst.chart_picker as cp


def _chartable_rows():
    # >=2 rows and >=2 cols with a numeric measure -> passes _chartability.
    return [
        {"Product": "Property", "Premium": 10},
        {"Product": "Casualty", "Premium": 20},
        {"Product": "Marine", "Premium": 15},
    ]


def _patch_node(monkeypatch, chart_data):
    """Make pick_charts use a stub chart node returning `chart_data`."""
    monkeypatch.setattr(
        cp, "chart_node_for", lambda flow, question: (lambda **kw: chart_data)
    )


def _evidence():
    return [{"flow": "gpr", "sql": "select 1", "rows": _chartable_rows(), "lens": "mix"}]


def test_skips_empty_chart_type(monkeypatch):
    """An empty-string chart_type must be skipped, not appended."""
    _patch_node(monkeypatch, {"chart_type": "", "x": "Product", "y": ["Premium"]})
    assert cp.pick_charts("breakdown by product", _evidence()) == []


def test_skips_none_value_chart_type(monkeypatch):
    """A literal None chart_type value must be skipped."""
    _patch_node(monkeypatch, {"chart_type": None, "x": "Product", "y": ["Premium"]})
    assert cp.pick_charts("breakdown by product", _evidence()) == []


def test_skips_whitespace_chart_type(monkeypatch):
    _patch_node(monkeypatch, {"chart_type": "  none ", "x": "Product", "y": ["Premium"]})
    assert cp.pick_charts("breakdown by product", _evidence()) == []


def test_keeps_valid_chart_type(monkeypatch):
    """A real chart_type is appended with its rows + spec."""
    spec = {"chart_type": "bar", "x": "Product", "y": ["Premium"], "title": "Mix"}
    _patch_node(monkeypatch, spec)
    charts = cp.pick_charts("breakdown by product", _evidence())
    assert len(charts) == 1
    assert charts[0]["chart_data"]["chart_type"] == "bar"
    assert charts[0]["rows"] == _chartable_rows()


def test_keeps_chart_when_node_returns_pydantic_model(monkeypatch):
    """The reported bug: the model hands back a ChartOutput MODEL, not a dict.

    The old `isinstance(chart_data, dict)` gate silently dropped it. The picker
    must now coerce the model to a plain dict and keep the chart.
    """
    from core.schemas.survey import ChartOutput

    model = ChartOutput(
        chart_type="line", x="Product", y=["Premium"], series=[], bar_mode=[],
        is_legend=True, y_agg="none", title="Trend", sort="none",
        secondary_y=[], waterfall_measures=[],
    )
    _patch_node(monkeypatch, model)
    charts = cp.pick_charts("premium trend", _evidence())
    assert len(charts) == 1
    cd = charts[0]["chart_data"]
    assert isinstance(cd, dict)  # coerced — JSON-safe for the chat-store
    assert cd["chart_type"] == "line"


def test_the_requested_trend_is_charted_first_and_duplicates_are_dropped(monkeypatch):
    """Priority and dedupe, which the one-chart ceiling used to hide.

    An analyst answer may now carry up to `MAX_CHARTS` charts, so "only one chart
    came back" no longer proves the picker ranked the trend above the wider mix.
    What must hold is that the trend is the chart the reader gets FIRST, and that
    a second lens drawing the identical picture is dropped rather than shown twice.
    """
    seen = []
    def build(**kwargs):
        seen.append(kwargs["sql_output"])
        return {"chart_type": "line", "x": "Year", "y": ["Premium"]}
    monkeypatch.setattr(cp, "chart_node_for", lambda *args: build)
    trend = [{"Year": 2024, "Premium": 100}, {"Year": 2025, "Premium": 125}]
    evidence = [
        {"flow": "gpr", "lens": "mix", "sql": "mix", "rows": [{"Product": str(i), "Premium": i} for i in range(40)]},
        {"flow": "gpr", "lens": "trend", "sql": "trend", "rows": trend},
        {"flow": "gpr", "lens": "duplicate", "sql": "another query", "rows": trend},
    ]
    charts = cp.pick_charts("Show the premium trend over time", evidence)
    # The trend is ranked first, so it is the first spec asked for and the first
    # chart rendered; the third lens draws the same line and is deduped away.
    assert seen[0] == trend
    assert len(charts) == 1
    assert charts[0]["rows"] == trend


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
