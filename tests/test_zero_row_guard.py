"""Tests for the analyst solver's zero-row guard in `run_sql`.

A SELECT that *succeeds* with 0 rows is only evidence of "no data" when its
filter values are real. ``WHERE Country = 'UK'`` returns 0 rows because the
stored value is 'United Kingdom' — without the guard the insight-writer then
asserts a false "no premium in UK".

Run:  pytest tests/test_zero_row_guard.py -q -o pythonpath=.
"""
from __future__ import annotations

import json

import pytest

import core.agents.analyst.common as common
from core.schemas.mcp import ExecuteSQLResult


def _result(rows: list) -> ExecuteSQLResult:
    return ExecuteSQLResult(rows=rows, row_count=len(rows), error=None)


@pytest.fixture
def run_sql_tool(monkeypatch):
    """Build the solver toolset against stubbed execute/audit layers."""

    def _build(rows: list, suspects: list, *, guard_zero_rows: bool = True):
        monkeypatch.setattr(common, "execute_sql", lambda flow, sql: _result(rows))
        monkeypatch.setattr(common, "audit_sql_filters", lambda flow, sql: suspects)
        evidence: list = []
        tools = common.build_tools(
            evidence, "q", "lens", guard_zero_rows=guard_zero_rows
        )
        run_sql = next(t for t in tools if t.name == "run_sql")
        return run_sql, evidence

    return _build


def test_zero_rows_with_suspect_filter_warns_and_drops_evidence(run_sql_tool):
    suspects = [{"column": "Country", "value": "UK", "suggestions": []}]
    run_sql, evidence = run_sql_tool([], suspects)  # guard armed (default)
    reply = json.loads(
        run_sql.invoke({"flow": "gpr", "sql": "SELECT 1 WHERE Country = 'UK'"})
    )
    assert reply["row_count"] == 0
    assert "WRONG FILTER VALUE" in reply["warning"]
    assert reply["suspect_filters"] == suspects
    # The empty result must never reach the insight-writer as a "no data" fact.
    assert evidence == []


def test_zero_rows_with_clean_filters_is_genuine_no_data(run_sql_tool):
    run_sql, evidence = run_sql_tool([], [])
    reply = json.loads(
        run_sql.invoke({"flow": "gpr", "sql": "SELECT 1 WHERE Country = 'Canada'"})
    )
    assert reply["row_count"] == 0
    assert "warning" not in reply
    assert len(evidence) == 1  # legitimate empty evidence is kept


def test_guard_disabled_keeps_zero_row_evidence_without_audit(run_sql_tool, monkeypatch):
    """A turn that resolved every entity cleanly disarms the guard: a 0-row result
    is genuine 'no data', not a filter typo — and the audit must not even run."""
    def _boom(flow, sql):
        raise AssertionError("audit_sql_filters called while the guard was disabled")

    run_sql, evidence = run_sql_tool([], [], guard_zero_rows=False)
    monkeypatch.setattr(common, "audit_sql_filters", _boom)
    reply = json.loads(
        run_sql.invoke({"flow": "gpr", "sql": "SELECT 1 WHERE Country = 'UK'"})
    )
    assert reply["row_count"] == 0
    assert "warning" not in reply
    assert len(evidence) == 1


def test_guard_fires_at_most_once_per_solver(run_sql_tool):
    """The guard re-checks a suspect 0-row ONCE; a second 0-row is taken at face
    value, so a stubborn-but-valid empty result can't loop the solver."""
    suspects = [{"column": "Country", "value": "UK", "suggestions": []}]
    run_sql, evidence = run_sql_tool([], suspects)

    first = json.loads(
        run_sql.invoke({"flow": "gpr", "sql": "SELECT 1 WHERE Country = 'UK'"})
    )
    assert "warning" in first  # first 0-row trips the guard
    assert evidence == []

    second = json.loads(
        run_sql.invoke({"flow": "gpr", "sql": "SELECT 1 WHERE Country = 'UK'"})
    )
    assert "warning" not in second  # already tripped -> accepted as evidence
    assert len(evidence) == 1


def test_non_empty_result_skips_the_audit(run_sql_tool, monkeypatch):
    def _boom(flow, sql):  # the audit must not run when rows came back
        raise AssertionError("audit_sql_filters called on a non-empty result")

    rows = [{"Premium": 1.0}]
    run_sql, evidence = run_sql_tool(rows, [])
    monkeypatch.setattr(common, "audit_sql_filters", _boom)
    reply = json.loads(run_sql.invoke({"flow": "gpr", "sql": "SELECT Premium"}))
    assert reply["row_count"] == 1
    assert len(evidence) == 1
