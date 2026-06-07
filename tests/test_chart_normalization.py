"""Tests for the deterministic chart guard (`_normalize_axes_and_type`).

These lock in the corrections the renderer makes on top of the LLM's chart spec:
year axes stay discrete (no 2024.2), `line` is reserved for real trends,
amount+rate pairs become a combo, and titles stay on one line. Fixtures mirror
`codex changes/tests/chart_output_eval_cases.yaml`.

Run:  pytest tests/test_chart_normalization.py -q
"""
from __future__ import annotations

import pandas as pd

from ui.chart_functions import (
    MAX_TITLE_LEN,
    _Spec,
    _clean_title,
    _normalize_axes_and_type,
    _sanitize_spec,
)


def _spec(df: pd.DataFrame, raw: dict) -> tuple[_Spec, pd.DataFrame]:
    spec, prepared, _ = _sanitize_spec(df, raw)
    assert spec is not None
    prepared, _reasons = _normalize_axes_and_type(prepared, spec)
    return spec, prepared


# ── Year axis stays discrete ────────────────────────────────────────────────


def test_multi_year_category_comparison_becomes_bar():
    df = pd.DataFrame(
        [
            {"Year": 2023, "Product_Line": "Property", "Premium": 1_200_000},
            {"Year": 2023, "Product_Line": "Casualty", "Premium": 800_000},
            {"Year": 2024, "Product_Line": "Property", "Premium": 1_300_000},
            {"Year": 2024, "Product_Line": "Casualty", "Premium": 700_000},
            {"Year": 2025, "Product_Line": "Property", "Premium": 1_500_000},
            {"Year": 2025, "Product_Line": "Casualty", "Premium": 900_000},
        ]
    )
    spec, prepared = _spec(
        df,
        {
            "chart_type": "line",  # LLM's wrong pick
            "x": "Year",
            "y": ["Premium"],
            "series": ["Product_Line"],
            "intent": "Show premium by product for Zurich for 2023, 2024, 2025",
        },
    )
    assert spec.chart_type == "bar"
    # Year coerced to ordered string categories — no fractional ticks possible.
    assert list(prepared[spec.x].cat.categories) == ["2023", "2024", "2025"]
    assert prepared[spec.x].dtype.name == "category"


def test_no_fractional_year_ticks():
    df = pd.DataFrame(
        [{"Year": y, "Premium": p} for y, p in [(2023, 1), (2024, 2), (2025, 3)]]
    )
    _spec_obj, prepared = _spec(
        df, {"chart_type": "bar", "x": "Year", "y": ["Premium"]}
    )
    assert set(prepared["Year"].astype(str)) == {"2023", "2024", "2025"}
    assert not any("." in v for v in prepared["Year"].astype(str))


# ── line ⇄ bar gating ───────────────────────────────────────────────────────


def test_explicit_trend_keeps_line():
    df = pd.DataFrame(
        [{"Year": y, "Premium": p} for y, p in [(2023, 12), (2024, 13), (2025, 15)]]
    )
    spec, _prepared = _spec(
        df,
        {
            "chart_type": "line",
            "x": "Year",
            "y": ["Premium"],
            "intent": "Show Zurich premium trend over time from 2023 to 2025",
        },
    )
    assert spec.chart_type == "line"


def test_one_period_breakdown_is_bar():
    df = pd.DataFrame(
        [
            {"Section": "Claims", "Score": 7.2},
            {"Section": "Underwriting", "Score": 6.8},
            {"Section": "Servicing", "Score": 7.5},
        ]
    )
    spec, _prepared = _spec(
        df,
        {
            "chart_type": "line",
            "x": "Section",
            "y": ["Score"],
            "intent": "Show score by section in 2025",
        },
    )
    assert spec.chart_type == "bar"


# ── amount + rate ⇒ combo ───────────────────────────────────────────────────


def test_amount_and_rate_become_combo_by_name():
    df = pd.DataFrame(
        [
            {"Carrier_Group": "A", "Premium": 12_000_000, "SoW": 0.32},
            {"Carrier_Group": "B", "Premium": 8_000_000, "SoW": 0.21},
        ]
    )
    spec, _prepared = _spec(
        df,
        {
            "chart_type": "bar",
            "x": "Carrier_Group",
            "y": ["Premium", "SoW"],
            "intent": "Premium and share of wallet by carrier",
        },
    )
    assert spec.chart_type == "combo"
    assert spec.y == ["Premium"]
    assert "SoW" in spec.secondary_y


def test_amount_and_rate_become_combo_by_magnitude():
    # "Index" is not a named rate, but is ~1e6x smaller than Premium.
    df = pd.DataFrame(
        [
            {"Country": "Canada", "Premium": 5_000_000, "Index": 1.4},
            {"Country": "US", "Premium": 9_000_000, "Index": 2.1},
        ]
    )
    spec, _prepared = _spec(
        df,
        {"chart_type": "bar", "x": "Country", "y": ["Premium", "Index"]},
    )
    assert spec.chart_type == "combo"
    assert spec.y == ["Premium"]
    assert "Index" in spec.secondary_y


def test_same_unit_measures_stay_bar():
    df = pd.DataFrame(
        [
            {"Product": "Property", "Premium_2024": 10, "Premium_2025": 12},
            {"Product": "Casualty", "Premium_2024": 8, "Premium_2025": 9},
        ]
    )
    spec, _prepared = _spec(
        df,
        {"chart_type": "bar", "x": "Product", "y": ["Premium_2024", "Premium_2025"]},
    )
    assert spec.chart_type == "bar"
    assert not spec.secondary_y


# ── title hygiene ───────────────────────────────────────────────────────────


def test_long_title_is_truncated_to_one_line():
    spec = _Spec(
        chart_type="bar",
        x="Product_Line",
        y=["Premium"],
        title="A very long descriptive chart title that the LLM produced "
        "explaining far too much detail about the premium analysis across products",
    )
    cleaned = _clean_title(spec)
    assert len(cleaned) <= MAX_TITLE_LEN
    assert "\n" not in cleaned


def test_missing_title_is_synthesized():
    spec = _Spec(chart_type="bar", x="Product_Line", y=["Premium"], title="")
    assert _clean_title(spec) == "Premium by Product Line"
