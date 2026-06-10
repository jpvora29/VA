"""Tests for the deterministic ChartSpecCritic (`core/charts/critic.py`).

Two layers:
  * Unit tests on `ChartSpecCritic.review` — each documented repair (junk y
    fields, redundant/identifier/constant legends, legend↔x orientation,
    scatter-with-year, pie slice budget, ranked bars).
  * End-to-end through `generate_chart`, driven by the eval cases in
    `codex changes/tests/chart_output_eval_cases.yaml` — the three observed
    failure modes (wrong type, wrong/junk fields, ugly-but-correct) must come
    out repaired in the rendered figure.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from core.charts.critic import ChartSpecCritic, classify_columns
from ui.chart_functions import generate_chart

_CRITIC = ChartSpecCritic()

_EVAL_PATH = (
    Path(__file__).resolve().parents[2]
    / "codex changes" / "tests" / "chart_output_eval_cases.yaml"
)
_EVAL_CASES = yaml.safe_load(_EVAL_PATH.read_text(encoding="utf-8"))[
    "chart_output_eval_cases"
]


# ── Column role classification ───────────────────────────────────────────────


def test_classify_roles():
    df = pd.DataFrame(
        {
            "Year": [2023, 2023, 2024, 2024],
            "Practice": ["Property", "Casualty", "Property", "Casualty"],
            "Country": ["Canada"] * 4,                    # constant (filter echo)
            "Client_Id": ["c1", "c2", "c3", "c4"],        # id by name
            "Premium": [1.2e6, 8e5, 1.3e6, 7e5],
            "SoW": [0.31, 0.22, 0.33, 0.21],
        }
    )
    roles = {c: r.kind for c, r in classify_columns(df).items()}
    assert roles["Year"] == "temporal"
    assert roles["Practice"] == "dimension"
    assert roles["Country"] == "constant"
    assert roles["Client_Id"] == "identifier"
    assert roles["Premium"] == "measure_amount"
    assert roles["SoW"] == "measure_rate"


# ── The marquee fix: smaller dimension goes to the legend ────────────────────


def _practices_df(n_practices=15, years=(2023, 2024, 2025)):
    rows = []
    for y in years:
        for i in range(n_practices):
            rows.append({"Survey_Year": y, "SurveyPractice": f"Practice {i}", "Score": 5 + (i % 4)})
    return pd.DataFrame(rows)


def test_many_practices_never_become_the_legend():
    """x=Year + 15-practice legend (the ugly chart) → swap: practices on x,
    2-3 year colours in the legend."""
    df = _practices_df()
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Survey_Year", "y": ["Score"],
         "series": ["SurveyPractice"], "intent": "score by practice across years"},
        df,
    )
    assert spec["x"] == "SurveyPractice"
    assert spec["series"] == ["Survey_Year"]
    assert any("legend" in r for r in reasons)


def test_small_legend_is_left_alone():
    """2 products vs 3 years: products already the smaller dim → no swap
    (matches the year_category_bar eval expectation)."""
    df = pd.DataFrame(
        [
            {"Year": y, "Product_Line": p, "Premium": v}
            for y, p, v in [
                (2023, "Property", 12), (2023, "Casualty", 8),
                (2024, "Property", 13), (2024, "Casualty", 7),
                (2025, "Property", 15), (2025, "Casualty", 9),
            ]
        ]
    )
    spec, _ = _CRITIC.review(
        {"chart_type": "bar", "x": "Year", "y": ["Premium"], "series": ["Product_Line"]},
        df,
    )
    assert spec["x"] == "Year"
    assert spec["series"] == ["Product_Line"]


def test_cardinality_tie_puts_time_on_x():
    df = pd.DataFrame(
        [
            {"Year": y, "Carrier_Group": c, "Premium": v}
            for y, c, v in [(2024, "A", 10), (2024, "B", 8), (2025, "A", 12), (2025, "B", 7)]
        ]
    )
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Carrier_Group", "y": ["Premium"], "series": ["Year"]},
        df,
    )
    assert spec["x"] == "Year"
    assert spec["series"] == ["Carrier_Group"]
    assert "tie→time-on-x" in reasons


def test_trend_always_puts_time_on_x_even_when_larger():
    df = _practices_df(n_practices=2, years=(2020, 2021, 2022, 2023, 2024))
    spec, reasons = _CRITIC.review(
        {"chart_type": "line", "x": "SurveyPractice", "y": ["Score"],
         "series": ["Survey_Year"], "intent": "score trend over time by practice"},
        df,
    )
    assert spec["x"] == "Survey_Year"
    assert spec["series"] == ["SurveyPractice"]
    assert "trend→time-on-x" in reasons


# ── Junk-field rejection ─────────────────────────────────────────────────────


def test_constant_and_identifier_series_are_dropped():
    df = pd.DataFrame(
        {
            "Section": ["Claims", "UW", "Service"] * 3,
            "Country": ["Canada"] * 9,
            "Row_Id": [f"r{i}" for i in range(9)],
            "Score": list(range(9)),
        }
    )
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Section", "y": ["Score"], "series": ["Country", "Row_Id"]},
        df,
    )
    assert spec["series"] == []
    assert any("constant" in r for r in reasons)
    assert any("identifier" in r for r in reasons)


def test_measure_in_series_is_dropped():
    df = pd.DataFrame({"Section": ["A", "B"], "Score": [1, 2], "Premium": [10, 20]})
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Section", "y": ["Score"], "series": ["Premium"]}, df
    )
    assert spec["series"] == []
    assert any("measure" in r for r in reasons)


def test_junk_y_among_measures_is_dropped_but_garbage_only_y_is_kept():
    df = pd.DataFrame({"Section": ["A", "B"], "Score": [1, 2]})
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Section", "y": ["Score", "Section"]}, df
    )
    assert spec["y"] == ["Score"]
    # Garbage-only y: leave it for the renderer to reject loudly.
    spec2, _ = _CRITIC.review({"chart_type": "bar", "x": "Score", "y": ["Section"]}, df)
    assert spec2["y"] == ["Section"]


def test_constant_x_is_replaced_with_a_real_dimension():
    df = pd.DataFrame(
        {"Country": ["Canada"] * 4, "Product": ["A", "B", "C", "D"], "Premium": [1, 2, 3, 4]}
    )
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Country", "y": ["Premium"]}, df
    )
    assert spec["x"] == "Product"
    assert any(r.startswith("x-replaced") for r in reasons)


def test_series_inferred_from_duplicate_x_groups():
    df = pd.DataFrame(
        [
            {"Year": y, "Segment": s, "Premium": v}
            for y, s, v in [(2023, "Corp", 5), (2023, "SME", 3), (2024, "Corp", 6), (2024, "SME", 4)]
        ]
    )
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Year", "y": ["Premium"], "series": [], "y_agg": "none"}, df
    )
    assert spec["series"] == ["Segment"]
    assert any("series-from-duplicates" in r for r in reasons)


# ── Chart-type repairs ───────────────────────────────────────────────────────


def test_scatter_with_year_x_becomes_line():
    df = pd.DataFrame({"Year": [2022, 2023, 2024], "Premium": [10, 12, 15]})
    spec, reasons = _CRITIC.review(
        {"chart_type": "scatter", "x": "Year", "y": ["Premium"]}, df
    )
    assert spec["chart_type"] == "line"
    assert "scatter+time-x→line" in reasons


def test_pie_with_too_many_slices_becomes_bar():
    df = pd.DataFrame({"Product": [f"P{i}" for i in range(15)], "Premium": range(15)})
    spec, reasons = _CRITIC.review(
        {"chart_type": "pie", "x": "Product", "y": ["Premium"]}, df
    )
    assert spec["chart_type"] == "bar"


def test_small_pie_is_kept():
    df = pd.DataFrame({"Segment": ["Corp", "SME", "Risk"], "Premium": [40, 30, 20]})
    spec, _ = _CRITIC.review({"chart_type": "donut", "x": "Segment", "y": ["Premium"]}, df)
    assert spec["chart_type"] == "donut"


def test_ranked_bars_sort_desc():
    df = pd.DataFrame({"Product": ["A", "B", "C", "D"], "Premium": [3, 9, 1, 5]})
    spec, reasons = _CRITIC.review(
        {"chart_type": "bar", "x": "Product", "y": ["Premium"], "sort": "none"}, df
    )
    assert spec["sort"] == "desc"
    assert "ranked-bars(desc)" in reasons


def test_temporal_x_is_never_rank_sorted():
    df = pd.DataFrame({"Year": [2022, 2023, 2024], "Premium": [9, 3, 5]})
    spec, _ = _CRITIC.review(
        {"chart_type": "bar", "x": "Year", "y": ["Premium"], "sort": "none"}, df
    )
    assert spec.get("sort", "none") == "none"


# ── End-to-end: eval cases through generate_chart ────────────────────────────


def _case(case_id: str) -> dict:
    return next(c for c in _EVAL_CASES if c["id"] == case_id)


def _x_tick_values(fig):
    vals = []
    for tr in fig.data:
        vals.extend(str(v) for v in (list(tr.x) if tr.x is not None else []))
    return vals


@pytest.mark.parametrize("case_id", [c["id"] for c in _EVAL_CASES])
def test_eval_case_renders_expected_chart(case_id):
    case = _case(case_id)
    df = pd.DataFrame(case["rows"])
    # Simulate the documented LLM failure: hand the renderer the FORBIDDEN type
    # (or the expected one when no forbidden type is listed).
    given_type = case.get("forbidden_chart_type", case["expected_chart_type"])
    spec = {
        "chart_type": given_type,
        "x": case.get("expected_x", ""),
        "y": case.get("expected_y", []),
        "series": [case["expected_series"]] if case.get("expected_series") else [],
        "intent": case["user_query"],
        "title": "",
    }
    fig, msg = generate_chart(df, spec)
    assert fig is not None, f"{case_id}: no figure ({msg})"

    expected = case["expected_chart_type"]
    trace_types = {t.type for t in fig.data}
    if expected == "bar":
        assert trace_types == {"bar"}, f"{case_id}: got {trace_types}"
    elif expected == "line":
        assert trace_types == {"scatter"}, f"{case_id}: got {trace_types}"
        assert all("lines" in (t.mode or "") for t in fig.data)

    for assertion in case.get("axis_assertions", []):
        ticks = _x_tick_values(fig)
        if assertion == "no_fractional_year_ticks":
            assert ticks and not any("." in v for v in ticks), f"{case_id}: {ticks}"
        elif assertion == "ticks_are_2023_2024_2025":
            assert set(ticks) == {"2023", "2024", "2025"}, f"{case_id}: {ticks}"


def test_eval_swapped_orientation_recovers():
    """Feed year_category_bar with the orientation swapped the ugly way —
    the rendered figure still ends with the small dimension in the legend."""
    case = _case("year_category_bar")
    df = pd.DataFrame(case["rows"])
    fig, _ = generate_chart(
        df,
        {"chart_type": "line", "x": "Product_Line", "y": ["Premium"],
         "series": ["Year"], "intent": case["user_query"], "title": ""},
    )
    assert fig is not None
    # 2 product traces (legend) over 3 year categories on x — never 3 traces over 2.
    assert len(fig.data) == 2
    assert {t.name for t in fig.data} == {"Property", "Casualty"}
