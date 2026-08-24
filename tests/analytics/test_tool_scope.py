"""The turn's shared scope — assembled from what is already resolved, never asked.

Run:  pytest tests/analytics/test_tool_scope.py -q
"""
from __future__ import annotations

import pytest

from core.analytics.tools import turn_scope, years_in


def matcher(_flow, _column, term):
    known = {"canada": ["Canada"], "cyber": ["Cyber"], "zurich": ["ZURICH GROUP"]}
    return list(known.get(term.strip().lower(), []))


@pytest.mark.parametrize(
    "timeframe,expected",
    [
        ("2024", [2024]),
        ("FY2023", [2023]),
        ("2022-2024", [2022, 2023, 2024]),
        ("2023 to 2024", [2023, 2024]),
        ("2021 and 2024", [2021, 2024]),      # two years, not a range
        ("last 12 months", []),               # rolling window: pin nothing
        ("", []),
    ],
)
def test_years_in(timeframe, expected):
    assert years_in(timeframe) == expected


def test_contract_filters_are_used_verbatim():
    scope = turn_scope(
        "gpr",
        resolved_filters={"Carrier_Group": ["ZURICH GROUP"], "Country": ["Canada"]},
        matcher=matcher,
    )
    assert scope.filters == {"Carrier_Group": "ZURICH GROUP", "Country": "Canada"}
    assert not scope.blocked


def test_multi_value_contract_filter_stays_a_list():
    scope = turn_scope(
        "gpr", resolved_filters={"Country": ["Canada", "United Kingdom"]}, matcher=matcher
    )
    assert scope.filters["Country"] == ["Canada", "United Kingdom"]


def test_year_comes_from_the_plan_timeframe():
    scope = turn_scope("gpr", timeframe="2024", matcher=matcher)
    assert scope.filters == {"Year": 2024}


def test_contract_wins_over_the_plan_on_the_same_column():
    scope = turn_scope(
        "gpr",
        resolved_filters={"Country": ["Canada"]},
        plan_filters={"Country": "cyber"},   # would resolve elsewhere; contract wins
        matcher=matcher,
    )
    assert scope.filters["Country"] == "Canada"


def test_plan_filters_fill_what_the_contract_does_not_carry():
    scope = turn_scope("gpr", plan_filters={"Product_Line": "cyber"}, matcher=matcher)
    assert scope.filters == {"Product_Line": "Cyber"}


def test_planner_noise_is_ignored_but_a_real_mismatch_blocks():
    ok = turn_scope("gpr", plan_filters={"timeframe": "latest"}, matcher=matcher)
    assert not ok.blocked

    blocked = turn_scope("gpr", plan_filters={"Country": "Atlantis"}, matcher=matcher)
    assert blocked.blocked
    assert blocked.unmatched == ("Country=Atlantis",)
