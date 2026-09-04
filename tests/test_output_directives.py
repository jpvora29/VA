"""Tests for the output-directives slice of the query contract.

"Don't generate a chart" must actually suppress charts: the deterministic
phrase detector feeds `RoutingContext.output_directives`, and every
chart-producing node checks `charts_suppressed` before running.

Run:  pytest tests/test_output_directives.py -q -o pythonpath=.
"""
from __future__ import annotations

import pytest

from core.agents.common.directives import (
    apply_directives,
    charts_suppressed,
    detect_chart_directive,
    detect_depth_directive,
    detect_presentation_directive,
    followups_suppressed,
    presentation_mode,
    prose_suppressed,
    response_depth,
)
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


# ── presentation directive: chart_only / table_only ──────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Just the chart please",
        "only the visual",
        "give me just the graph",
        "chart only",
        "Just show me the visual",
        "give me only the chart for Zurich premium",
    ],
)
def test_detect_presentation_chart_only(query):
    assert detect_presentation_directive(query) == "chart_only"


@pytest.mark.parametrize(
    "query",
    [
        "just the table",
        "table only",
        "give me just the numbers",
        "only the numbers",
        "compare Chubb vs peers, table-only",
        "numbers only please",
    ],
)
def test_detect_presentation_table_only(query):
    assert detect_presentation_directive(query) == "table_only"


@pytest.mark.parametrize(
    "query",
    [
        "What is Zurich's premium in Canada in 2024?",
        "Show me a chart of Zurich's premium",  # a chart REQUEST, not chart_only
        "no chart please",  # suppression, but prose stays
        "How is AXA performing vs peers?",
    ],
)
def test_detect_presentation_neutral(query):
    assert detect_presentation_directive(query) is None


# ── depth directive: direct ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "In one line, how did Zurich do?",
        "give me a one-liner on AXA's premium",
        "short answer: Zurich's rank?",
        "keep it brief",
        "briefly, what happened to premium?",
        "tldr on the cyber book",
    ],
)
def test_detect_depth_direct(query):
    assert detect_depth_directive(query) == "direct"


@pytest.mark.parametrize(
    "query",
    [
        "Why did premium decline in Canada?",
        "Give me a full breakdown by product.",
        "What is Zurich's NPS?",
    ],
)
def test_detect_depth_neutral(query):
    assert detect_depth_directive(query) is None


# ── presentation / depth helpers over RoutingContext ─────────────────────────


def _pctx(presentation="prose", depth="analyst", charts="auto") -> RoutingContext:
    return RoutingContext(
        table_family="premium",
        intent_type="new_question",
        output_directives=OutputDirectives(
            charts=charts, presentation=presentation, depth=depth
        ),
    )


def test_presentation_and_depth_helpers_read_model_and_dict():
    ctx = _pctx(presentation="chart_only", depth="direct")
    assert presentation_mode(ctx) == "chart_only"
    assert response_depth(ctx) == "direct"
    assert presentation_mode(ctx.model_dump()) == "chart_only"
    assert response_depth(ctx.model_dump()) == "direct"
    # Safe defaults on missing/legacy shapes.
    assert presentation_mode(None) == "prose"
    assert response_depth({}) == "analyst"


def test_prose_and_followup_suppression():
    assert prose_suppressed(_pctx(presentation="chart_only")) is True
    assert prose_suppressed(_pctx(presentation="table_only")) is True
    assert prose_suppressed(_pctx(presentation="prose")) is False
    # Follow-ups die for any minimal response, including a direct one-liner.
    assert followups_suppressed(_pctx(presentation="chart_only")) is True
    assert followups_suppressed(_pctx(depth="direct")) is True
    assert followups_suppressed(_pctx()) is False


def test_table_only_suppresses_charts():
    # table_only implies no chart even though `charts` itself is not "none".
    assert charts_suppressed(_pctx(presentation="table_only", charts="auto")) is True
    # chart_only keeps the chart on.
    assert charts_suppressed(_pctx(presentation="chart_only", charts="required")) is False


# ── end-to-end: context filler overlay keeps charts coherent ─────────────────


def test_apply_directives_folds_all_detectors():
    # One call folds chart + presentation + depth detectors over the raw query.
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    fired = apply_directives("just the table, briefly", rc.output_directives)
    assert fired is True
    assert rc.output_directives.presentation == "table_only"
    assert rc.output_directives.charts == "none"  # table_only pins charts off
    assert rc.output_directives.depth == "direct"
    assert rc.output_directives.source == "deterministic"


def test_apply_directives_no_hit_leaves_defaults():
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    fired = apply_directives("What is Zurich's premium in Canada in 2024?", rc.output_directives)
    assert fired is False
    assert rc.output_directives.charts == "auto"
    assert rc.output_directives.presentation == "prose"
    assert rc.output_directives.depth == "analyst"
    assert rc.output_directives.source == ""


def test_overlay_pins_charts_for_presentation():
    # Simulate the context_filler overlay block directly on a RoutingContext.
    rc = RoutingContext(table_family="premium", intent_type="new_question")
    presentation = detect_presentation_directive("just show me the visual")
    assert presentation == "chart_only"
    rc.output_directives.presentation = presentation
    if presentation == "chart_only":
        rc.output_directives.charts = "required"
    assert charts_suppressed(rc) is False
    assert prose_suppressed(rc) is True

    rc2 = RoutingContext(table_family="premium", intent_type="new_question")
    presentation2 = detect_presentation_directive("just the numbers")
    assert presentation2 == "table_only"
    rc2.output_directives.presentation = presentation2
    rc2.output_directives.charts = "none"
    assert charts_suppressed(rc2) is True
    assert prose_suppressed(rc2) is True


# ── write_insight honors the contract ────────────────────────────────────────


_EVIDENCE = [{"flow": "gpr", "sql": "SELECT 1", "rows": [{"premium": 100}], "lens": "t"}]


class _Chunk:
    def __init__(self, text: str) -> None:
        self.content = text


def _streaming_llm(captured: dict, text: str = "Premium fell **8%**."):
    """A fake llm_creative whose `.with_config(...).stream(messages)` captures the
    system prompt and yields the answer as one chunk — matching the real
    streaming interface insight_writer now uses."""

    class _Configured:
        @staticmethod
        def stream(messages):
            captured["system"] = messages[0].content
            return iter([_Chunk(text)])

    class _LLM:
        @staticmethod
        def with_config(**kwargs):
            return _Configured()

    return _LLM


@pytest.mark.parametrize("presentation", ["chart_only", "table_only"])
def test_write_insight_skips_prose_without_llm(monkeypatch, presentation):
    from core.agents.analyst import insight_writer as iw

    class _Boom:
        @staticmethod
        def with_config(**kwargs):
            raise AssertionError("insight_writer must not call the LLM when prose is suppressed")

    monkeypatch.setattr(iw.Initialization, "llm_reason", _Boom)
    out = iw.write_insight(
        question="q", route="premium", synthesis_focus="",
        evidence=_EVIDENCE, presentation=presentation, depth="analyst",
    )
    assert out == ""


def test_write_insight_direct_uses_compact_contract(monkeypatch):
    from core.agents.analyst import insight_writer as iw

    captured = {}
    monkeypatch.setattr(
        iw.Initialization, "llm_reason",
        _streaming_llm(captured, "Premium fell **8%**, concentrated in Property."),
    )

    direct = iw.write_insight(
        question="q", route="premium", synthesis_focus="",
        evidence=_EVIDENCE, presentation="prose", depth="direct",
    )
    assert "DIRECT, short answer" in captured["system"]
    assert "SUPPORTING DATA" not in captured["system"]
    assert direct == "Premium fell **8%**, concentrated in Property."

    iw.write_insight(
        question="q", route="premium", synthesis_focus="",
        evidence=_EVIDENCE, presentation="prose", depth="analyst",
    )
    assert "SUPPORTING DATA" in captured["system"]


# ── end-to-end: insight nodes + follow-ups honor suppression ─────────────────


def test_gpr_insight_skips_prose_when_suppressed(monkeypatch):
    from core.agents.gpr import response as gpr

    def _boom(*a, **k):
        raise AssertionError("gpr_insight must not run its predictor when prose is suppressed")

    monkeypatch.setattr(gpr, "_GPR_RESPONSE_NODE", _boom)
    state = {
        "messages": [type("M", (), {"content": "just the chart for Zurich"})()],
        "routing_context": _pctx(presentation="chart_only", charts="required"),
        "gpr_reasoning": "plan",
        "gpr_query_result": [{"premium": 1}],
    }
    assert gpr.gpr_insight(state) == {"gpr_response": ""}


def test_followup_node_suppressed_for_minimal_response():
    from core.agents.followup import followup_node

    state = {
        "current_route": "premium",
        "routing_context": _pctx(presentation="chart_only"),
        "messages": [type("M", (), {"content": "just the chart"})()],
        "gpr_response": "ignored",
    }
    assert followup_node(state) == {"followup_questions": []}
