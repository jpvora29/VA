"""Unit tests for the chart rendering engine (`ui.chart_functions`).

Self-contained: builds small synthetic DataFrames + ChartOutput-shaped dicts and
asserts that every chart type renders a Plotly figure, and that malformed specs
degrade gracefully to ``(None, message)`` instead of raising.

Run:  pytest tests/test_chart_functions.py -q
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from ui.chart_functions import generate_chart


# ── Happy-path: every chart type produces a figure ──────────────────────────


def _bar_df():
    return pd.DataFrame(
        {
            "Product_Line": ["Property", "Casualty", "Property", "Casualty"],
            "Carrier_Group": ["A", "A", "B", "B"],
            "Premium": [10, 20, 15, 25],
        }
    )


@pytest.mark.parametrize(
    "spec",
    [
        {"chart_type": "bar", "x": "Product_Line", "y": ["Premium"],
         "series": ["Carrier_Group"], "bar_mode": ["group"], "title": "t"},
        {"chart_type": "bar", "x": "Product_Line", "y": ["Premium"],
         "series": ["Carrier_Group"], "bar_mode": ["stack"], "title": "t"},
    ],
)
def test_bar_renders(spec):
    fig, msg = generate_chart(_bar_df(), spec)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2
    assert msg == "Successful"


def test_line_multi_series():
    df = pd.DataFrame(
        {
            "Year": [2021, 2022, 2023, 2021, 2022, 2023],
            "Region": ["EMEA"] * 3 + ["APAC"] * 3,
            "Premium": [1, 2, 3, 2, 3, 5],
        }
    )
    fig, msg = generate_chart(
        df, {"chart_type": "line", "x": "Year", "y": ["Premium"],
             "series": ["Region"], "bar_mode": [], "title": "Trend"}
    )
    assert isinstance(fig, go.Figure) and len(fig.data) == 2


def test_scatter():
    df = pd.DataFrame({"SoW": [0.1, 0.2, 0.3], "Growth": [5, 8, 2], "Carrier": ["A", "B", "C"]})
    fig, _ = generate_chart(
        df, {"chart_type": "scatter", "x": "SoW", "y": ["Growth"], "series": ["Carrier"],
             "bar_mode": [], "title": "t"}
    )
    assert isinstance(fig, go.Figure)


@pytest.mark.parametrize("ctype", ["pie", "donut"])
def test_pie_donut(ctype):
    df = pd.DataFrame({"Segment": ["Corp", "SME", "Risk", "Other"], "Premium": [40, 30, 20, 10]})
    fig, _ = generate_chart(
        df, {"chart_type": ctype, "x": "Segment", "y": ["Premium"], "series": [],
             "bar_mode": [], "title": "Mix"}
    )
    assert isinstance(fig, go.Figure)
    assert fig.data[0].type == "pie"


def test_waterfall():
    df = pd.DataFrame({"Step": ["Open", "Growth", "Churn", "Close"], "Delta": [100, 30, -20, 0]})
    fig, _ = generate_chart(
        df, {"chart_type": "waterfall", "x": "Step", "y": ["Delta"], "series": [], "bar_mode": [],
             "waterfall_measures": ["total", "relative", "relative", "total"], "title": "Bridge"}
    )
    assert isinstance(fig, go.Figure)
    assert fig.data[0].type == "waterfall"


def test_combo_dual_axis():
    df = pd.DataFrame({"Year": [2021, 2022, 2023], "Premium": [100, 120, 150], "Growth_%": [5, 20, 25]})
    fig, _ = generate_chart(
        df, {"chart_type": "combo", "x": "Year", "y": ["Premium"], "secondary_y": ["Growth_%"],
             "series": [], "bar_mode": [], "title": "Premium & Growth"}
    )
    assert isinstance(fig, go.Figure)
    types = sorted(t.type for t in fig.data)
    assert types == ["bar", "scatter"]
    assert fig.layout.yaxis2 is not None  # secondary axis configured


# ── Robustness: malformed specs degrade gracefully ──────────────────────────


def test_none_type_returns_no_figure():
    fig, msg = generate_chart(_bar_df(), {"chart_type": "none", "x": "", "y": [], "series": [], "bar_mode": []})
    assert fig is None and "scalar" in msg.lower()


def test_missing_x_column_falls_back():
    fig, msg = generate_chart(
        _bar_df(), {"chart_type": "bar", "x": "DoesNotExist", "y": ["Premium"],
                    "series": ["Carrier_Group"], "bar_mode": ["group"], "title": "t"}
    )
    assert isinstance(fig, go.Figure)  # engine picks a valid x instead of crashing


def test_non_numeric_y_is_rejected_cleanly():
    fig, msg = generate_chart(
        _bar_df(), {"chart_type": "bar", "x": "Premium", "y": ["Product_Line"], "series": [],
                    "bar_mode": ["group"], "title": "t"}
    )
    assert fig is None and msg


def test_empty_dataframe():
    fig, msg = generate_chart(pd.DataFrame(), {"chart_type": "bar", "x": "a", "y": ["b"], "series": [], "bar_mode": []})
    assert fig is None and msg


def test_case_and_underscore_insensitive_columns():
    fig, _ = generate_chart(
        _bar_df(), {"chart_type": "bar", "x": "product line", "y": ["premium"],
                    "series": ["carrier group"], "bar_mode": ["group"], "title": "t"}
    )
    assert isinstance(fig, go.Figure) and len(fig.data) == 2


def test_high_cardinality_series_is_capped():
    df = pd.DataFrame(
        {"X": [f"p{i % 3}" for i in range(40)], "S": [f"c{i}" for i in range(40)], "V": list(range(40))}
    )
    fig, _ = generate_chart(
        df, {"chart_type": "bar", "x": "X", "y": ["V"], "series": ["S"], "bar_mode": ["group"], "title": "t"}
    )
    assert isinstance(fig, go.Figure)
    assert len(fig.data) <= 12  # MAX_SERIES ceiling


def test_combo_without_secondary_falls_back_to_bar():
    df = pd.DataFrame({"Year": [2021, 2022], "Premium": [100, 120]})
    fig, _ = generate_chart(
        df, {"chart_type": "combo", "x": "Year", "y": ["Premium"], "secondary_y": [], "series": [],
             "bar_mode": [], "title": "t"}
    )
    assert isinstance(fig, go.Figure)
    assert all(t.type == "bar" for t in fig.data)


def test_accepts_pydantic_chart_output():
    from core.schemas.survey import ChartOutput

    spec = ChartOutput(chart_type="bar", x="Product_Line", y=["Premium"],
                       series=["Carrier_Group"], bar_mode=["group"], title="t")
    fig, msg = generate_chart(_bar_df(), spec)
    assert isinstance(fig, go.Figure) and msg == "Successful"
