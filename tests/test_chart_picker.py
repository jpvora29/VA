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
    monkeypatch.setattr(cp, "_chart_rules", lambda flow, question: "rules")
    monkeypatch.setattr(
        cp, "_chart_node", lambda flow, rules: (lambda **kw: chart_data)
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
