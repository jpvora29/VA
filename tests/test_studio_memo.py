"""The build memo: same question once per build, and never across builds.

Measured cause: one single-country build made 305 analytics primitive calls for
88 distinct arguments — 217 exact repeats, 61% of the planning phase. The risk a
memo introduces is stale or shared data, so most of these tests are about the
memo NOT applying: outside a build, across builds, and across data sources.
"""
from __future__ import annotations

import pytest

from studio.memo import Memo, active_memo, build_memo, memoized


@pytest.fixture
def counted():
    """A memoizable function that records how often it really ran."""
    calls = []

    @memoized
    def compute(flow, filters, engine=None, top=5):
        calls.append((flow, dict(filters), engine, top))
        return [{"row": len(calls)}]

    return compute, calls


# ── the point ────────────────────────────────────────────────────────────────

def test_a_repeated_call_runs_once_inside_a_build(counted):
    compute, calls = counted
    with build_memo():
        a = compute("gpr", {"Country": "Singapore"})
        b = compute("gpr", {"Country": "Singapore"})
    assert a == b
    assert len(calls) == 1


def test_argument_order_does_not_make_a_second_key(counted):
    compute, calls = counted
    with build_memo():
        compute("gpr", {"Country": "Singapore", "Year": 2024})
        compute("gpr", {"Year": 2024, "Country": "Singapore"})
    assert len(calls) == 1


def test_different_scopes_are_different_answers(counted):
    compute, calls = counted
    with build_memo():
        compute("gpr", {"Country": "Singapore"})
        compute("gpr", {"Country": "Japan"})
        compute("gpr", {"Country": "Singapore"}, top=8)
    assert len(calls) == 3


def test_hits_and_misses_are_counted(counted):
    compute, _ = counted
    with build_memo() as memo:
        compute("gpr", {"a": 1})
        compute("gpr", {"a": 1})
        compute("gpr", {"a": 2})
    assert (memo.misses, memo.hits) == (2, 1)


# ── the ways it must NOT apply ───────────────────────────────────────────────

def test_outside_a_build_nothing_is_cached(counted):
    """The chatbot, the Overall page and tests must behave exactly as before."""
    compute, calls = counted
    compute("gpr", {"a": 1})
    compute("gpr", {"a": 1})
    assert len(calls) == 2
    assert active_memo() is None


def test_a_new_build_recomputes(counted):
    """A memo may never outlive the build whose data it describes."""
    compute, calls = counted
    with build_memo():
        compute("gpr", {"a": 1})
    with build_memo():
        compute("gpr", {"a": 1})
    assert len(calls) == 2


def test_the_memo_is_torn_down_even_on_failure(counted):
    compute, _ = counted
    with pytest.raises(ValueError):
        with build_memo():
            compute("gpr", {"a": 1})
            raise ValueError("boom")
    assert active_memo() is None


def test_two_engines_are_never_interchangeable(counted):
    """Keyed by engine IDENTITY — a custom dataset must not read the governed book."""
    compute, calls = counted
    governed, dataset = object(), object()
    with build_memo():
        compute("gpr", {"a": 1}, engine=governed)
        compute("gpr", {"a": 1}, engine=dataset)
        compute("gpr", {"a": 1}, engine=governed)
    assert len(calls) == 2


# ── the shared-mutable-result hazard ─────────────────────────────────────────

def test_a_caller_cannot_corrupt_the_cached_value(counted):
    """A page that sorts its rows in place must not change another page's rows."""
    compute, _ = counted
    with build_memo():
        first = compute("gpr", {"a": 1})
        first.append({"row": "injected"})
        first[0]["row"] = "mutated"
        second = compute("gpr", {"a": 1})
    assert second == [{"row": 1}]


def test_nested_dicts_are_copied_too():
    @memoized
    def nested(_key):
        return {"outer": {"inner": [1, 2]}}

    with build_memo():
        a = nested("k")
        a["outer"]["inner"].append(3)
        b = nested("k")
    assert b == {"outer": {"inner": [1, 2]}}


# ── re-entrancy ──────────────────────────────────────────────────────────────

def test_a_nested_build_memo_shares_the_outer_one(counted):
    """assemble_deck opens one; a step inside it must not start a second."""
    compute, calls = counted
    with build_memo("outer") as outer:
        compute("gpr", {"a": 1})
        with build_memo("inner") as inner:
            assert inner is outer
            compute("gpr", {"a": 1})
    assert len(calls) == 1


def test_the_memo_survives_unhashable_arguments(counted):
    """Filters arrive as dicts and peer sets as lists — neither is hashable."""
    compute, calls = counted
    with build_memo():
        compute("gpr", {"peers": ["AIG", "CHUBB"], "Year": 2024})
        compute("gpr", {"peers": ["AIG", "CHUBB"], "Year": 2024})
    assert len(calls) == 1


def test_memo_dataclass_reports_savings():
    memo = Memo(hits=7, misses=3)
    assert memo.saved_calls == 7
