"""Grounding a selected tool call — the deterministic gate in front of the library.

The model's choice is never trusted verbatim: the primitive must exist for this
flow, the cuts must be real dimensions, the metric must resolve, and every filter
value must match stored data. Anything else is REJECTED with a reason, which is the
signal to fall back to LLM-SQL — never silently repaired into a wider question.

Run:  pytest tests/analytics/test_tool_grounding.py -q
"""
from __future__ import annotations

import pytest

from core.analytics.tools import ground_call, ground_calls, ground_filters


def matcher(mapping=None):
    """A stub value matcher: (flow, column, term) -> exact stored values."""
    mapping = mapping or {"zurich": ["ZURICH GROUP"], "canada": ["Canada"]}

    def match(_flow: str, _column: str, term: str):
        return list(mapping.get(term.strip().lower(), []))

    return match


def test_valid_call_is_grounded_with_canonical_names():
    call, rejected = ground_call(
        "gpr",
        {
            "name": "compute_breakdown",
            "metric": "premium",
            "group_by": ["product_line"],          # loose casing from the model
            "filters": {"country": "canada"},      # loose value from the model
        },
        matcher=matcher(),
    )
    assert rejected is None
    assert call.group_by == ("Product_Line",)
    assert call.filters == {"Country": "Canada"}


def test_metric_defaults_to_the_flow_default():
    call, _ = ground_call("gpr", {"name": "compute_rank"}, matcher=matcher())
    assert call.metric == "premium"
    call, _ = ground_call("survey", {"name": "compute_rank"}, matcher=matcher())
    assert call.metric == "score"


def test_metric_alias_resolves_through_the_registry():
    call, _ = ground_call(
        "gpr", {"name": "compute_breakdown", "metric": "gross premium"}, matcher=matcher()
    )
    assert call.metric == "premium"


def test_unknown_primitive_is_rejected():
    call, rejected = ground_call("gpr", {"name": "compute_magic"}, matcher=matcher())
    assert call is None and "not a tool" in rejected.reason


def test_primitive_from_the_other_flow_is_rejected():
    call, rejected = ground_call("gpr", {"name": "compute_nps"}, matcher=matcher())
    assert call is None and "not a tool" in rejected.reason


def test_unknown_group_by_column_is_rejected_not_dropped():
    call, rejected = ground_call(
        "gpr",
        {"name": "compute_breakdown", "group_by": ["Product_Line", "Underwriter"]},
        matcher=matcher(),
    )
    assert call is None
    assert "Underwriter" in rejected.reason


def test_unmatched_filter_value_is_rejected():
    call, rejected = ground_call(
        "gpr",
        {"name": "compute_breakdown", "filters": {"Country": "Atlantis"}},
        matcher=matcher(),
    )
    assert call is None
    assert "Atlantis" in rejected.reason


def test_numeric_filters_pass_through_untouched():
    call, _ = ground_call(
        "gpr", {"name": "compute_breakdown", "filters": {"Year": "2024"}}, matcher=matcher()
    )
    assert call.filters == {"Year": 2024}


def test_cuts_are_ignored_for_a_tool_that_takes_none():
    call, rejected = ground_call(
        "gpr",
        {"name": "compute_ttm", "group_by": ["Product_Line"]},
        matcher=matcher(),
    )
    assert rejected is None and call.group_by == ()


def test_declared_options_survive_and_unknown_ones_do_not():
    call, _ = ground_call(
        "gpr",
        {"name": "compute_period_series", "grain": "quarter", "colour": "red"},
        matcher=matcher(),
    )
    assert call.options == {"grain": "quarter"}


def test_duplicate_calls_are_computed_once():
    result = ground_calls(
        "gpr",
        [
            {"name": "compute_breakdown", "group_by": ["Product_Line"]},
            {"name": "compute_breakdown", "group_by": ["Product_Line"]},
        ],
        matcher=matcher(),
    )
    assert len(result.calls) == 1 and result.ok


def test_filter_grounding_separates_noise_from_a_real_mismatch():
    grounded = ground_filters(
        "gpr",
        {"timeframe": "latest", "Country": "Atlantis", "Year": 2024},
        matcher=matcher(),
    )
    assert grounded.values == {"Year": 2024}
    assert grounded.unknown_columns == ("timeframe",)      # planner noise, ignorable
    assert grounded.unmatched_values == ("Country=Atlantis",)  # a real mismatch
