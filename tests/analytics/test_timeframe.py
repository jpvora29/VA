"""Deterministic timeframe resolution (Phase 1).

Covers the cases the plan calls out: single-year, multi-year, year-quarter
format, explicit/relative/multi-period queries, and the flag default. The pure
resolver carries all the logic; the planner wiring is a thin flag-gated call that
only fills a blank timeframe.

Run:  pytest tests/analytics -q
"""
from __future__ import annotations

import pytest

from core.analytics import resolve_default_timeframe, timeframe_resolution_enabled

GPR_YQ = [
    "2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4",
    "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4", "2025-Q1",
]
PLAIN_YEARS = [2023, 2024, 2025]


# ── defaulting fires: no time reference -> latest year ─────────────────────

def test_defaults_to_latest_year_from_year_quarter():
    assert resolve_default_timeframe(GPR_YQ, "Zurich premium in Canada") == "2025"


def test_defaults_to_latest_year_from_plain_years():
    assert resolve_default_timeframe(PLAIN_YEARS, "Zurich's NPS") == "2025"


def test_latest_and_current_resolve_to_latest():
    # "latest" / "most recent" / "current year" all WANT the latest year.
    assert resolve_default_timeframe(GPR_YQ, "Zurich premium in the latest year") == "2025"
    assert resolve_default_timeframe(GPR_YQ, "Zurich's most recent premium") == "2025"
    assert resolve_default_timeframe(GPR_YQ, "Zurich premium current year") == "2025"


# ── defaulting defers (returns "") for any explicit/relative/multi-period ──

@pytest.mark.parametrize(
    "query",
    [
        "Zurich premium in 2023",          # explicit year
        "Zurich premium in Q2 2024",       # explicit year + quarter
        "Zurich premium by quarter",       # quarter
        "Zurich premium trend",            # multi-period
        "Zurich YoY premium growth",       # YoY
        "premium across years",            # multi-period
        "premium by year",                 # multi-period
        "Zurich premium last year",        # relative
        "premium over the last 3 years",   # relative range
        "rolling 12 month premium",        # TTM-ish
    ],
)
def test_defers_when_query_has_time_reference(query):
    assert resolve_default_timeframe(GPR_YQ, query) == ""


def test_defers_when_timeframe_hint_already_resolved():
    # Context filler resolved a relative term -> don't override it.
    assert resolve_default_timeframe(GPR_YQ, "and last year?", timeframe_hint="MAX(Year) - 1") == ""


# ── edge cases ─────────────────────────────────────────────────────────────

def test_empty_valid_periods_returns_blank():
    assert resolve_default_timeframe([], "Zurich premium") == ""


def test_blank_hint_is_ignored():
    assert resolve_default_timeframe(GPR_YQ, "Zurich premium", timeframe_hint="   ") == "2025"


# ── flag default ───────────────────────────────────────────────────────────

def test_resolution_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("ANALYTICS_TIMEFRAME_RESOLUTION", raising=False)
    assert timeframe_resolution_enabled() is False


@pytest.mark.parametrize("value, expected", [("on", True), ("shadow", True), ("off", False), ("OFF", False)])
def test_resolution_flag_reads_env(monkeypatch, value, expected):
    monkeypatch.setenv("ANALYTICS_TIMEFRAME_RESOLUTION", value)
    assert timeframe_resolution_enabled() is expected
