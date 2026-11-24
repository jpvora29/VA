"""Phase 2 step 3: lookups through the analyst pipeline, behind UNIFIED_PIPELINE.

Unit tests cover the switch, the router decision, the one-step plan and the
primitives adapter. The end-to-end tests run the real compiled analyst subgraph
and the real `analyst_agent_node` mapping, with only the model calls stubbed
(the writer, and the analytics runner's selection), because this environment
has no model credentials.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from core.agents import analyst_agent
from core.agents.analyst import lookup_tools
from core.agents.analyst.lookup_tools import LIBRARY_TOOL, lookup_primitive_evidence
from core.agents.common.analytics_tools import AnalyticsTurn
from core.agents.router import RouterNode
from core.analysis.lookup_plan import (
    LOOKUP_LENS,
    is_lookup_plan,
    is_lookup_turn,
    lookup_plan,
)
from core.answers.steps import title_of
from core.graph import analyst_subgraph as subgraph
from core.schemas.analysis import AnalysisPlan, DerivedAnalysis
from core.turn.pipeline import takes_unified_pipeline, unified_pipeline_enabled

QUESTION = "What was Zurich's premium in Singapore in 2025?"
FILTERS = {"Carrier_Group": ["ZURICH"], "Country": ["Singapore"], "Year": ["2025"]}
ROWS = [{"Carrier_Group": "ZURICH", "premium": 1234.5}]


def rc(depth="lookup", family="premium"):
    return SimpleNamespace(
        analysis_depth=depth,
        table_family=family,
        resolved_filters=FILTERS,
        unresolved_terms=[],
        output_directives={
            "shape": "direct",
            "presentation": "prose",
            "depth": "direct",
        },
    )


def router_state(question=QUESTION, route="premium", depth="lookup"):
    return {
        "messages": [HumanMessage(question)],
        "current_route": route,
        "routing_context": rc(depth, route),
    }


@pytest.fixture
def unified(monkeypatch):
    monkeypatch.setenv("UNIFIED_PIPELINE", "on")


# --------------------------------------------------------------------------- #
# The switch and the router
# --------------------------------------------------------------------------- #


def test_the_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv("UNIFIED_PIPELINE", raising=False)
    assert not unified_pipeline_enabled()
    assert not takes_unified_pipeline("premium", needs_gimmi=False)


def test_only_data_routes_without_gimmi_take_the_unified_pipeline(unified):
    assert takes_unified_pipeline("survey", needs_gimmi=False)
    assert takes_unified_pipeline("both", needs_gimmi=False)
    assert not takes_unified_pipeline("fallback", needs_gimmi=False)
    assert not takes_unified_pipeline("premium", needs_gimmi=True)


def test_with_the_switch_off_lookups_keep_their_own_rails(monkeypatch):
    monkeypatch.delenv("UNIFIED_PIPELINE", raising=False)
    assert RouterNode.relevance_router(router_state()) == "gpr_agent"
    assert RouterNode.relevance_router(router_state(route="survey")) == "survey_agent"
    assert RouterNode.relevance_router(router_state(route="both")) == "combiner_agent"


def test_with_the_switch_on_every_data_lookup_takes_the_analyst(unified):
    for route in ("premium", "survey", "both"):
        assert RouterNode.relevance_router(router_state(route=route)) == "analyst_agent"
    assert RouterNode.relevance_router(router_state(route="fallback")) == "fallback"


def test_a_gimmi_question_stays_on_the_premium_rail(unified):
    state = router_state("Zurich benchmarking against the market in Singapore")
    assert RouterNode.relevance_router(state) == "gpr_agent"


# --------------------------------------------------------------------------- #
# The one-step plan
# --------------------------------------------------------------------------- #


def test_a_lookup_plan_is_one_step_answering_the_question():
    plan = lookup_plan(QUESTION)
    assert is_lookup_plan(plan)
    assert plan.derived[0].lens == LOOKUP_LENS
    assert plan.derived[0].sub_question == QUESTION


def test_a_planned_turn_is_not_a_lookup_plan():
    plan = AnalysisPlan(
        derived=[DerivedAnalysis(lens="temporal_trend", sub_question="x")]
    )
    assert not is_lookup_plan(plan)
    assert not is_lookup_plan(None)


def test_only_an_explicit_lookup_depth_counts():
    assert is_lookup_turn(rc("lookup"))
    assert is_lookup_turn({"analysis_depth": "lookup"})
    assert not is_lookup_turn(rc("analytical"))
    assert not is_lookup_turn(None)


def test_the_planner_model_still_plans_when_the_switch_is_off(monkeypatch):
    monkeypatch.delenv("UNIFIED_PIPELINE", raising=False)
    called = []
    monkeypatch.setattr(
        subgraph,
        "plan_analysis",
        lambda *a, **kw: called.append(1) or AnalysisPlan(derived=[]),
    )
    subgraph.choose_plan({"question": QUESTION, "routing_context": rc("lookup")})
    assert called


def test_a_unified_lookup_skips_the_planner_model(unified, monkeypatch):
    monkeypatch.setattr(
        subgraph, "plan_analysis", lambda *a, **kw: pytest.fail("planner called")
    )
    plan = subgraph.choose_plan({"question": QUESTION, "routing_context": rc("lookup")})
    assert is_lookup_plan(plan)


# --------------------------------------------------------------------------- #
# Primitives first
# --------------------------------------------------------------------------- #


class StubRunner:
    enabled = True

    def __init__(self, turn=None, error=None):
        self._turn = turn or AnalyticsTurn()
        self._error = error
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._turn


def evidence_for(runner):
    return lookup_primitive_evidence(
        question=QUESTION,
        flow="gpr",
        lens=LOOKUP_LENS,
        resolved_filters=FILTERS,
        runner=runner,
    )


def test_a_covered_lookup_becomes_one_library_evidence_record():
    runner = StubRunner(
        AnalyticsTurn(rows=list(ROWS), scope=FILTERS, defaulted_year=None)
    )
    records = evidence_for(runner)
    assert len(records) == 1
    record = records[0]
    assert record["tool"] == LIBRARY_TOOL and record["lens"] == LOOKUP_LENS
    assert record["rows"] == ROWS
    assert record["sql"].startswith("-- computed by the analytics library")
    assert runner.calls[0]["resolved_filters"] == FILTERS


def test_an_uncovered_lookup_hands_over_to_the_solver():
    assert evidence_for(StubRunner(AnalyticsTurn(scope=FILTERS))) == []


def test_a_failing_library_hands_over_to_the_solver():
    assert evidence_for(StubRunner(error=RuntimeError("boom"))) == []


def test_the_library_is_skipped_when_analytics_tools_are_off(monkeypatch):
    monkeypatch.setenv("ANALYTICS_TOOLS", "off")
    runner = StubRunner(AnalyticsTurn(rows=list(ROWS)))
    assert evidence_for(runner) == []
    assert runner.calls == []


# --------------------------------------------------------------------------- #
# End to end: router decision -> analyst subgraph -> route fields
# --------------------------------------------------------------------------- #


def stub_writer(monkeypatch):
    """Replace only the model-written prose; everything around it is real."""
    seen = {}

    def write(**kwargs):
        seen.update(kwargs)
        text = "Zurich wrote **$1,234.5** of premium in Singapore in 2025."
        record = {
            "version": 4,
            "content": text,
            "claims": [],
            "facts": [],
            "limitations": [],
        }
        return SimpleNamespace(text=text, as_dict=lambda: dict(record))

    monkeypatch.setattr(subgraph, "grounded_insight", write)
    monkeypatch.setattr(subgraph, "pick_charts", lambda *a, **kw: [])
    return seen


def stub_library(monkeypatch, rows):
    monkeypatch.setattr(
        lookup_tools,
        "AnalyticsToolRunner",
        lambda: StubRunner(AnalyticsTurn(rows=list(rows), scope=FILTERS)),
    )


def test_a_covered_lookup_runs_end_to_end_without_schema_or_solver(
    unified, monkeypatch
):
    seen = stub_writer(monkeypatch)
    stub_library(monkeypatch, ROWS)
    for name in ("identify_schema", "solve_generic", "solve_peer", "plan_analysis"):
        monkeypatch.setattr(
            subgraph, name, lambda *a, _n=name, **kw: pytest.fail(f"{_n} ran")
        )

    state = router_state()
    assert RouterNode.relevance_router(state) == "analyst_agent"
    out = analyst_agent.analyst_agent_node(state)

    assert out["gpr_response"].startswith("Zurich wrote")
    assert out["gpr_query_result"] == ROWS
    # The writer saw the library's evidence and owed exactly one value.
    assert seen["requirements"] == ("direct_value",)
    assert seen["limitations"] == ()
    assert [e["tool"] for e in seen["evidence"]] == [LIBRARY_TOOL]
    # The evidence is named by its data source, not by the "lookup" lens.
    assert [title_of(e["lens"]) for e in seen["evidence"]] == ["Premium data"]
    # The evidence panel formats the table from the same digest the old rail kept.
    assert out["gpr_analytics"]["scope"] == FILTERS
    assert "facts" in out["gpr_analytics"]


def test_an_uncovered_lookup_falls_back_to_the_solver(unified, monkeypatch):
    seen = stub_writer(monkeypatch)
    stub_library(monkeypatch, [])
    asked = []

    def solver(**kwargs):
        asked.append(kwargs["lens"])
        return [
            {"flow": "gpr", "lens": kwargs["lens"], "sql": "SELECT 1", "rows": ROWS}
        ]

    monkeypatch.setattr(subgraph, "solve_generic", solver)
    monkeypatch.setattr(
        subgraph,
        "identify_schema",
        lambda **kw: subgraph.SchemaSlice(tables=["GPR"]),
    )

    out = analyst_agent.analyst_agent_node(router_state())

    assert asked == [LOOKUP_LENS]
    assert out["gpr_query_result"] == ROWS
    assert [e["lens"] for e in seen["evidence"]] == ["gpr"]
    # SQL evidence has no fact digest, so an earlier turn's one is cleared.
    assert out["gpr_analytics"] is None
    assert out["gpr_response"].startswith("Zurich wrote")


def test_a_unified_lookup_builds_no_position_table(unified, monkeypatch):
    stub_writer(monkeypatch)
    stub_library(monkeypatch, ROWS)
    monkeypatch.setattr(
        subgraph,
        "build_market_positions",
        lambda *a, **kw: pytest.fail("position table built for a lookup"),
    )
    analyst_agent.analyst_agent_node(router_state())


def test_only_lookup_evidence_is_renamed_to_its_data_source():
    row = {"flow": "survey", "lens": LOOKUP_LENS, "sql": "SELECT 1", "rows": ROWS}
    lookup_step = lookup_plan(QUESTION).derived[0]
    assert subgraph.stamp_step(row, lookup_step)["lens"] == "survey"

    trend = DerivedAnalysis(lens="temporal_trend", sub_question="x", step_id="s1")
    trend_row = dict(row, lens="temporal_trend")
    assert subgraph.stamp_step(trend_row, trend)["lens"] == "temporal_trend"
    assert "lens" not in subgraph.stamp_step({"flow": "gpr", "rows": ROWS}, trend)
