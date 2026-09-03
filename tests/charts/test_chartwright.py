"""Chartwright — per-type chart tools whose enums come from the real result set.

The point of the agent is PREVENTION: the old path handed the model one fat
all-types schema and let `ChartSpecCritic` repair the wreckage. These pin that the
wreckage is now unrepresentable — a hallucinated column, a categorical measure, an
amount and a rate on one axis, a 15-entry legend, time on a scatter axis — and
that a call which still cannot be drawn is REJECTED rather than guessed at.

Run:  pytest tests/charts/test_chartwright.py -q
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.charts.agent import Chartwright, ChartRequest, design_chart
from core.charts.catalog import applicable_types, tool_schemas
from core.charts.grounding import ground_chart_call
from core.charts.profile import build_profile, sample_values, to_frame


# ── fixtures: the result shapes the chatbot actually produces ────────────────

MIXED_ROWS = [
    {"Product_Line": "Property", "Year": 2024, "Premium": 150.0, "Growth_%": 4.2},
    {"Product_Line": "Cyber", "Year": 2024, "Premium": 50.0, "Growth_%": 12.1},
    {"Product_Line": "Property", "Year": 2023, "Premium": 120.0, "Growth_%": 2.0},
    {"Product_Line": "Cyber", "Year": 2023, "Premium": 40.0, "Growth_%": 8.0},
]

WIDE_ROWS = [
    {"Practice": f"P{i}", "Premium": float(i * 10)} for i in range(1, 16)
]


def profile_of(rows):
    return build_profile(to_frame(rows))


def schema_named(rows, tool_name):
    for schema in tool_schemas(profile_of(rows)):
        if schema["function"]["name"] == tool_name:
            return schema["function"]["parameters"]
    return None


def enum_of(parameters, argument):
    prop = (parameters or {}).get("properties", {}).get(argument)
    if prop is None:
        return None
    return prop.get("enum") or (prop.get("items") or {}).get("enum")


# ── the profile: one deterministic read, shared with the critic ──────────────


def test_columns_are_classified_into_the_critics_role_vocabulary():
    profile = profile_of(MIXED_ROWS)
    assert profile.temporal == ["Year"]
    assert profile.dimensions == ["Product_Line"]
    assert profile.amounts == ["Premium"]
    assert profile.rates == ["Growth_%"]


def test_a_single_scalar_is_not_chartable():
    assert not profile_of([{"Premium": 42.0}]).chartable


def test_a_result_with_no_measure_is_not_chartable():
    rows = [{"Product_Line": "Property"}, {"Product_Line": "Cyber"}]
    assert not profile_of(rows).chartable


def test_the_description_omits_measure_values():
    """The agent decides axes, not numbers — showing it the figures is the one
    place it would be tempted to repeat one as fact."""
    frame = to_frame(MIXED_ROWS)
    profile = build_profile(frame)
    described = profile.describe(sample_values(frame, profile))
    assert "Property" in described  # dimension values help identify the column
    assert "150" not in described  # a premium figure does not


# ── the catalog: what the data cannot support is never offered ───────────────


def test_a_line_is_not_offered_without_a_time_column():
    rows = [{"Product_Line": "Property", "Premium": 1.0}, {"Product_Line": "Cyber", "Premium": 2.0}]
    assert "line" not in {spec.name for spec in applicable_types(profile_of(rows))}


def test_a_combo_is_not_offered_without_both_an_amount_and_a_rate():
    rows = [{"Product_Line": "Property", "Premium": 1.0}, {"Product_Line": "Cyber", "Premium": 2.0}]
    assert "combo" not in {spec.name for spec in applicable_types(profile_of(rows))}


def test_a_scatter_is_not_offered_with_only_one_measure():
    rows = [{"Product_Line": "Property", "Premium": 1.0}, {"Product_Line": "Cyber", "Premium": 2.0}]
    assert "scatter" not in {spec.name for spec in applicable_types(profile_of(rows))}


def test_a_pie_is_not_offered_when_there_are_too_many_slices():
    assert "pie" not in {spec.name for spec in applicable_types(profile_of(WIDE_ROWS))}


# ── the schemas: bad specs become unrepresentable ────────────────────────────


def test_y_offers_measures_only_so_a_categorical_measure_cannot_be_asked_for():
    assert enum_of(schema_named(MIXED_ROWS, "draw_bar"), "y_measures") == [
        "Premium",
        "Growth_%",
    ]


def test_a_combo_separates_the_amount_from_the_rate():
    parameters = schema_named(MIXED_ROWS, "draw_combo")
    assert enum_of(parameters, "y_amounts") == ["Premium"]
    assert enum_of(parameters, "secondary_y_rates") == ["Growth_%"]


def test_a_line_can_only_put_a_time_column_on_x():
    assert enum_of(schema_named(MIXED_ROWS, "draw_line"), "x_temporal") == ["Year"]


def test_a_column_too_wide_for_a_legend_is_never_offered_as_a_series():
    """15 practices in a legend is the failure the critic was written to undo."""
    assert enum_of(schema_named(WIDE_ROWS, "draw_bar"), "series") is None


def test_no_schema_offers_a_column_the_result_does_not_have():
    columns = set(profile_of(MIXED_ROWS).roles)
    for schema in tool_schemas(profile_of(MIXED_ROWS)):
        for prop in schema["function"]["parameters"]["properties"].values():
            values = prop.get("enum") or (prop.get("items") or {}).get("enum") or []
            # Option enums (bar_mode, sort, step_kinds) are not column lists.
            if values and values[0] in columns:
                assert set(values) <= columns


# ── grounding: what still slips through is rejected, not guessed ─────────────


def test_a_grounded_call_becomes_the_spec_the_renderer_already_speaks():
    grounding = ground_chart_call(
        "draw_bar",
        {"x_category": "Product_Line", "y_measures": ["Premium"], "sort": "desc",
         "title": "Premium by product line"},
        profile_of(MIXED_ROWS),
    )
    assert grounding.ok
    spec = grounding.chart.spec
    assert spec["chart_type"] == "bar"
    assert spec["x"] == "Product_Line"
    assert spec["y"] == ["Premium"]
    assert spec["sort"] == "desc"
    assert spec["is_legend"] is False  # no series -> no legend


def test_a_column_name_in_the_wrong_case_still_resolves():
    grounding = ground_chart_call(
        "draw_bar",
        {"x_category": "product line", "y_measures": ["premium"], "title": "t"},
        profile_of(MIXED_ROWS),
    )
    assert grounding.ok
    assert grounding.chart.spec["x"] == "Product_Line"


def test_a_hallucinated_column_is_rejected_not_invented():
    grounding = ground_chart_call(
        "draw_bar",
        {"x_category": "Region", "y_measures": ["Premium"], "title": "t"},
        profile_of(MIXED_ROWS),
    )
    assert not grounding.ok
    assert "x category" in grounding.rejected[0].reason.replace("_", " ")


def test_time_on_a_scatter_axis_is_rejected():
    grounding = ground_chart_call(
        "draw_scatter",
        {"x_measure": "Year", "y_measure": "Premium", "title": "t"},
        profile_of(MIXED_ROWS),
    )
    assert not grounding.ok
    assert "time column" in grounding.rejected[0].reason


def test_sorting_a_time_axis_by_value_is_repaired_to_chronological():
    grounding = ground_chart_call(
        "draw_bar",
        {"x_category": "Year", "y_measures": ["Premium"], "sort": "desc", "title": "t"},
        profile_of(MIXED_ROWS),
    )
    assert grounding.ok
    assert grounding.chart.spec["sort"] == "none"
    assert grounding.chart.repairs


def test_a_bar_mode_with_no_series_is_dropped():
    grounding = ground_chart_call(
        "draw_bar",
        {"x_category": "Product_Line", "y_measures": ["Premium"], "bar_mode": "stack",
         "title": "t"},
        profile_of(MIXED_ROWS),
    )
    assert grounding.ok
    assert grounding.chart.spec["bar_mode"] == []


def test_an_unknown_tool_is_rejected():
    assert not ground_chart_call("draw_sankey", {}, profile_of(MIXED_ROWS)).ok


# ── the agent: selection is injected, so the pipeline tests without a model ──


class StubSelector:
    def __init__(self, result):
        self.result = result
        self.seen = None

    def select(self, request: ChartRequest):
        self.seen = request
        return self.result


def test_the_agent_designs_a_chart_from_a_selected_call():
    selector = StubSelector(
        ("draw_bar", {"x_category": "Product_Line", "y_measures": ["Premium"], "title": "T"})
    )
    turn = Chartwright(selector=selector).design(
        user_query="premium by product line", rows=MIXED_ROWS
    )
    assert turn.drawn
    assert turn.spec["chart_type"] == "bar"
    assert turn.tool == "draw_bar"


def test_the_agent_is_only_offered_types_the_data_supports():
    selector = StubSelector(None)
    rows = [{"Product_Line": "Property", "Premium": 1.0}, {"Product_Line": "Cyber", "Premium": 2.0}]
    Chartwright(selector=selector).design(user_query="q", rows=rows)
    offered = {s["function"]["name"] for s in selector.seen.schemas}
    assert "draw_bar" in offered
    assert "draw_line" not in offered  # no time column in this result


def test_no_tool_call_means_declined_not_failed():
    """The agent looked and said there is no chart here — the caller must not
    fall back and ask an older path to find one anyway."""
    turn = Chartwright(selector=StubSelector(None)).design(user_query="q", rows=MIXED_ROWS)
    assert turn.declined
    assert not turn.drawn


def test_a_scalar_result_declines_without_calling_the_model():
    selector = StubSelector(("draw_bar", {}))
    turn = Chartwright(selector=selector).design(user_query="q", rows=[{"Premium": 1.0}])
    assert turn.declined
    assert selector.seen is None  # never asked


def test_an_ungroundable_call_is_rejected_so_the_caller_can_fall_back():
    selector = StubSelector(("draw_bar", {"x_category": "Nope", "y_measures": ["Premium"]}))
    turn = Chartwright(selector=selector).design(user_query="q", rows=MIXED_ROWS)
    assert not turn.drawn
    assert not turn.declined  # a failure, not a decision
    assert turn.rejected


def test_a_selector_that_raises_never_sinks_the_turn():
    class Boom:
        def select(self, request):
            raise RuntimeError("model down")

    turn = design_chart(user_query="q", rows=MIXED_ROWS, agent=Chartwright(selector=Boom()))
    assert not turn.drawn
    assert turn.rejected


# ── the fallback branch the chart nodes take ─────────────────────────────────


def test_declined_returns_no_chart_without_consulting_the_old_path(monkeypatch):
    from core.agents.common import chart_spec

    called = {"two_phase": False}

    def two_phase(**_kwargs):
        called["two_phase"] = True
        return {"chart_type": "bar"}

    monkeypatch.setattr(chart_spec, "generate_chart_two_phase", two_phase)
    monkeypatch.setattr(
        "core.charts.agent.design_chart",
        lambda **_k: __import__(
            "core.charts.agent", fromlist=["ChartTurn"]
        ).ChartTurn(declined=True),
    )
    spec = chart_spec.generate_chart_spec(
        base_rules="", user_query="q", sql_output=MIXED_ROWS,
        type_predictor=None, spec_predictor=None, detail_provider=lambda _t: None,
    )
    assert spec == {}
    assert not called["two_phase"]


def test_a_rejected_design_falls_back_to_the_two_phase_path(monkeypatch):
    from core.agents.common import chart_spec
    from core.charts.agent import ChartTurn

    monkeypatch.setattr(
        chart_spec, "generate_chart_two_phase", lambda **_k: {"chart_type": "line"}
    )
    monkeypatch.setattr(
        "core.charts.agent.design_chart", lambda **_k: ChartTurn(rejected=("boom",))
    )
    spec = chart_spec.generate_chart_spec(
        base_rules="", user_query="q", sql_output=MIXED_ROWS,
        type_predictor=None, spec_predictor=None, detail_provider=lambda _t: None,
    )
    assert spec == {"chart_type": "line"}


def test_the_flag_off_restores_the_two_phase_path(monkeypatch):
    from core.agents.common import chart_spec

    monkeypatch.setenv("CHART_AGENT", "off")
    monkeypatch.setattr(
        chart_spec, "generate_chart_two_phase", lambda **_k: {"chart_type": "line"}
    )
    spec = chart_spec.generate_chart_spec(
        base_rules="", user_query="q", sql_output=MIXED_ROWS,
        type_predictor=None, spec_predictor=None, detail_provider=lambda _t: None,
    )
    assert spec == {"chart_type": "line"}


# ── the spec survives the renderer's own gate ────────────────────────────────


@pytest.mark.parametrize(
    "tool, arguments",
    [
        ("draw_bar", {"x_category": "Product_Line", "y_measures": ["Premium"], "title": "t"}),
        ("draw_line", {"x_temporal": "Year", "y_measures": ["Premium"], "title": "t"}),
        ("draw_donut", {"labels": "Product_Line", "values": "Premium", "title": "t"}),
        ("draw_combo", {"x_category": "Product_Line", "y_amounts": ["Premium"],
                        "secondary_y_rates": ["Growth_%"], "title": "t"}),
        ("draw_waterfall", {"x_steps": "Product_Line", "y_measure": "Premium", "title": "t"}),
    ],
)
def test_every_designed_spec_renders(tool, arguments):
    """End of the pipeline: what Chartwright produces must actually draw, not just
    look well-formed. Guards the seam between the agent and `chart_functions`."""
    from ui.chart_functions import generate_chart

    grounding = ground_chart_call(tool, arguments, profile_of(MIXED_ROWS))
    assert grounding.ok
    figure, message = generate_chart(
        pd.DataFrame(MIXED_ROWS), dict(grounding.chart.spec)
    )
    assert figure is not None, f"{tool} produced no figure: {message}"


# ── aggregation: a rate is averaged, an amount is summed ─────────────────────


def test_a_rate_measure_is_averaged_not_summed():
    """The renderer's own default sums everything, which quietly adds up
    percentages. Chartwright knows the role, so it says mean."""
    grounding = ground_chart_call(
        "draw_bar",
        {"x_category": "Product_Line", "y_measures": ["Growth_%"], "title": "t"},
        profile_of(MIXED_ROWS),
    )
    assert grounding.chart.spec["y_agg"] == "mean"


def test_an_amount_measure_is_summed():
    grounding = ground_chart_call(
        "draw_bar",
        {"x_category": "Product_Line", "y_measures": ["Premium"], "title": "t"},
        profile_of(MIXED_ROWS),
    )
    assert grounding.chart.spec["y_agg"] == "sum"
