"""Phase 3 orchestrator: run plan primitive-calls deterministically over SQLite.

Proves the acceptance criteria: known primitives produce identical numbers across
repeated runs (determinism), duplicate calls compute once (caching), unknown/failed
calls land in `skipped` (LLM-SQL fallback signal), and shared scope filters apply to
every call. Calls are passed as plain dicts to keep the test LLM-free.

Run:  pytest tests/analytics/test_orchestrator.py -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.analytics import AnalyticsOrchestrator, PrimitiveArgs


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text(
            'CREATE TABLE GPR (Carrier_Group TEXT, Country TEXT, Product_Line TEXT, '
            'Year INTEGER, Premium REAL)'
        ))
        conn.execute(
            text('INSERT INTO GPR (Carrier_Group, Country, Product_Line, Year, Premium) '
                 'VALUES (:cg, :co, :pl, :yr, :pr)'),
            [
                {"cg": "Zurich", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 150.0},
                {"cg": "Zurich", "co": "Canada", "pl": "Cyber", "yr": 2024, "pr": 50.0},
                {"cg": "AIG", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 100.0},
                {"cg": "AIG", "co": "Canada", "pl": "Marine", "yr": 2024, "pr": 200.0},
            ],
        )
    return eng


SCOPE = {"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024}


def test_runs_calls_and_collects_facts(engine):
    calls = [{"name": "compute_breakdown", "metric": "premium", "group_by": ["Product_Line"]}]
    ev = AnalyticsOrchestrator().run(calls, flow="gpr", shared_filters=SCOPE, engine=engine)
    assert {f.dims["Product_Line"]: f.value for f in ev.facts} == {"Property": 150.0, "Cyber": 50.0}
    assert set(ev.by_call) == {"compute_breakdown"}
    assert ev.skipped == []


def test_compound_request_multiple_primitives(engine):
    # "performance analysis for Zurich": breakdown + rank + whitespace in one plan,
    # sharing the Zurich/Canada/2024 scope. (rank ranks Zurich among all carriers in
    # each product because the carrier filter scopes the WHERE, not the ranking set.)
    calls = [
        {"name": "compute_breakdown", "metric": "premium", "group_by": ["Product_Line"]},
        {"name": "find_whitespace", "metric": "premium", "group_by": ["Product_Line"]},
    ]
    ev = AnalyticsOrchestrator().run(calls, flow="gpr", shared_filters=SCOPE, engine=engine)
    assert set(ev.by_call) == {"compute_breakdown", "find_whitespace"}
    # Zurich has Property + Cyber but not Marine; the market has Marine -> whitespace.
    assert [g.dims["Product_Line"] for g in ev.by_call["find_whitespace"]] == ["Marine"]


def test_unknown_primitive_is_skipped_not_fatal(engine):
    calls = [
        {"name": "compute_breakdown", "metric": "premium", "group_by": ["Product_Line"]},
        {"name": "no_such_primitive", "metric": "premium"},
    ]
    ev = AnalyticsOrchestrator().run(calls, flow="gpr", shared_filters=SCOPE, engine=engine)
    assert ev.skipped == ["no_such_primitive"]          # fallback signal
    assert "compute_breakdown" in ev.by_call            # the rest still ran


def test_determinism_repeated_runs_equal(engine):
    calls = [
        {"name": "compute_breakdown", "metric": "premium", "group_by": ["Product_Line"]},
        {"name": "compute_share_of_portfolio", "metric": "premium", "group_by": ["Product_Line"]},
    ]
    orch = AnalyticsOrchestrator()
    a = orch.run(calls, flow="gpr", shared_filters=SCOPE, engine=engine)
    b = orch.run(calls, flow="gpr", shared_filters=SCOPE, engine=engine)
    assert [f.value for f in a.facts] == [f.value for f in b.facts]


def test_caching_computes_each_call_once(engine):
    calls_seen = {"n": 0}

    def counting_breakdown(args, *, engine=None):
        calls_seen["n"] += 1
        return []

    orch = AnalyticsOrchestrator(library={"compute_breakdown": counting_breakdown})
    # Two identical calls in one plan -> primitive invoked once (cache hit on the 2nd).
    calls = [
        {"name": "compute_breakdown", "metric": "premium", "group_by": ["Product_Line"]},
        {"name": "compute_breakdown", "metric": "premium", "group_by": ["Product_Line"]},
    ]
    orch.run(calls, flow="gpr", shared_filters=SCOPE, engine=engine)
    assert calls_seen["n"] == 1


# ── a multi-select filter is a LIST, and the memo key has to survive it ──────
#
# A multi-select country/product filter reaches a primitive as a list (see
# `library._peer_clauses`, which branches on exactly that). The memo key used to be
# `tuple(sorted(filters.items()))`, a tuple holding that list — unhashable. The
# lookup that raised sits OUTSIDE the per-primitive try/except, so the whole turn
# died with `TypeError: unhashable type: 'list'` instead of one call degrading.


def test_a_list_valued_filter_does_not_sink_the_turn(engine):
    calls = [{"name": "compute_breakdown", "metric": "premium", "group_by": ["Product_Line"]}]
    ev = AnalyticsOrchestrator().run(
        calls, flow="gpr",
        shared_filters={"Country": ["Canada"], "Carrier_Group": "Zurich", "Year": 2024},
        engine=engine,
    )
    assert {f.dims["Product_Line"]: f.value for f in ev.facts} == {"Property": 150.0, "Cyber": 50.0}
    assert not ev.skipped


def test_a_list_valued_filter_still_caches_by_identity(engine):
    """Freezing the key must not flatten two different filters into one entry."""
    seen = []

    def capture(args: PrimitiveArgs, *, engine=None):
        seen.append(dict(args.filters))
        return []

    orch = AnalyticsOrchestrator(library={"capture": capture})
    orch.run(
        [
            {"name": "capture", "filters": {"Country": ["Canada", "Mexico"]}},
            {"name": "capture", "filters": {"Country": ["Canada", "Mexico"]}},   # cache hit
            {"name": "capture", "filters": {"Country": ["Mexico", "Canada"]}},   # a different query
            {"name": "capture", "filters": {"Country": ["Canada"]}},             # and another
        ],
        flow="gpr", engine=engine,
    )
    assert [f["Country"] for f in seen] == [
        ["Canada", "Mexico"], ["Mexico", "Canada"], ["Canada"],
    ]


def test_a_list_valued_option_does_not_sink_the_turn(engine):
    """The other half of the key: an option value can be a list too."""
    def capture(args: PrimitiveArgs, *, engine=None, cuts=None):
        return []

    orch = AnalyticsOrchestrator(library={"capture": capture})
    ev = orch.run(
        [{"name": "capture", "options": {"cuts": ["Product_Line", "Country"]}}],
        flow="gpr", engine=engine,
    )
    assert not ev.skipped


def test_shared_scope_merges_and_call_overrides(engine):
    captured = {}

    def capture(args: PrimitiveArgs, *, engine=None):
        captured["filters"] = dict(args.filters)
        return []

    orch = AnalyticsOrchestrator(library={"capture": capture})
    orch.run(
        [{"name": "capture", "filters": {"Year": 2023}}],   # call overrides shared Year
        flow="gpr",
        shared_filters={"Country": "Canada", "Year": 2024},
        engine=engine,
    )
    assert captured["filters"] == {"Country": "Canada", "Year": 2023}


def test_failing_primitive_is_skipped(engine):
    def boom(args, *, engine=None):
        raise RuntimeError("db down")

    orch = AnalyticsOrchestrator(library={"boom": boom})
    ev = orch.run([{"name": "boom"}], flow="gpr", engine=engine)
    assert ev.skipped == ["boom"] and ev.facts == []
