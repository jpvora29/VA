"""Tests for the output-directives slice of the query contract.

"Don't generate a chart" must actually suppress charts: the deterministic
phrase detector feeds `RoutingContext.output_directives`, and every
chart-producing node checks `charts_suppressed` before running.

Run:  pytest tests/test_output_directives.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents.common.directives import charts_suppressed, detect_chart_directive
from core.schemas.routing import OutputDirectives, RoutingContext


# ── deterministic detector ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Zurich premium in Canada, no chart please",
        "Show Zurich's premium without a chart",
        "Don't generate a chart for this",
        "Do not show charts",
        "please don't include any graphs",
        "Skip the chart, just give the analysis",
        "Zurich SoW by product, text only",
        "Give me the numbers only",
        "just the table for AXA's premium",
        "compare Chubb vs peers, table-only",
        "Never draw a plot for this one",
    ],
)
def test_detector_suppression_phrasings(query):
    assert detect_chart_directive(query) == "none"


@pytest.mark.parametrize(
    "query",
    [
        "Show me a chart of Zurich's premium trend",
        "Give me a graph of NPS by year",
        "Premium by region as a chart",
        "Visualize AXA's growth across products",
        "Chubb vs peers — chart it",
        "include a chart with the breakdown",
    ],
)
def test_detector_request_phrasings(query):
    assert detect_chart_directive(query) == "required"


@pytest.mark.parametrize(
    "query",
    [
        "What is Zurich's premium in Canada in 2024?",
        "How is AXA performing vs peers?",
        "Top 5 carriers by gross premium",
        # Words that merely contain chart-ish substrings must not fire.
        "What charters does the policy cover?",
    ],
)
def test_detector_neutral_queries(query):
    assert detect_chart_directive(query) is None


def test_negated_request_is_suppression_not_request():
    # Contains "generate a chart" — the negation must win.
    assert detect_chart_directive("don't generate a chart of the trend") == "none"


# ── charts_suppressed helper ─────────────────────────────────────────────────


def _ctx(charts: str) -> RoutingContext:
    return RoutingContext(
        table_family="premium",
        intent_type="new_question",
        output_directives=OutputDirectives(charts=charts, source="deterministic"),
    )


def test_charts_suppressed_reads_model_and_dict_shapes():
    assert charts_suppressed(_ctx("none")) is True
    assert charts_suppressed(_ctx("auto")) is False
    assert charts_suppressed(_ctx("required")) is False
    assert charts_suppressed(_ctx("none").model_dump()) is True
    assert charts_suppressed(_ctx("auto").model_dump()) is False


def test_charts_suppressed_defaults_safe_on_missing_context():
    # Missing/legacy shapes must never silently suppress charts.
    assert charts_suppressed(None) is False
    assert charts_suppressed({}) is False
    assert charts_suppressed({"output_directives": None}) is False
    legacy = RoutingContext(table_family="premium", intent_type="new_question")
    assert charts_suppressed(legacy) is False  # default is 'auto'


# ── analyst chart-picker gate ────────────────────────────────────────────────


def test_chart_picker_node_honors_suppression(monkeypatch):
    from core.graph import analyst_subgraph as sub

    def _boom(question, evidence):
        raise AssertionError("pick_charts must not run when charts are suppressed")

    monkeypatch.setattr(sub, "pick_charts", _boom)
    state = {
        "question": "q",
        "route": "premium",
        "routing_context": _ctx("none"),
        "evidence": [{"flow": "gpr", "sql": "s", "rows": [{"a": 1}], "lens": "t"}],
    }
    assert sub.chart_picker_node(state) == {"charts": []}


def test_chart_picker_node_runs_normally_without_directive(monkeypatch):
    from core.graph import analyst_subgraph as sub

    sentinel = [{"title": "t", "rows": [], "chart_data": {"chart_type": "bar"}}]
    monkeypatch.setattr(sub, "pick_charts", lambda q, ev: sentinel)
    state = {
        "question": "q",
        "route": "premium",
        "routing_context": _ctx("auto"),
        "evidence": [],
    }
    assert sub.chart_picker_node(state) == {"charts": sentinel}
