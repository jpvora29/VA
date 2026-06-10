"""Tests for the boardroom digest's row-gathering.

Analyst turns carry `analyst_evidence` (every lens's executed rows); the digest
must see ALL of them — not just the first result set per flow — or the
query-dependent widgets (timeline, opportunity map, positioning) starve.

Run:  pytest tests/test_boardroom_rows.py -q -o pythonpath=.
"""
from __future__ import annotations

from core.agents.boardroom import _gather_rows


def _ev(flow: str, lens: str, sql: str, rows: list) -> dict:
    return {"flow": flow, "sql": sql, "rows": rows, "lens": lens}


def test_analyst_evidence_yields_one_entry_per_lens():
    state = {
        "analyst_evidence": [
            _ev("gpr", "temporal_trend", "SELECT a", [{"Year": 2023, "P": 1}, {"Year": 2024, "P": 2}]),
            _ev("gpr", "peer_benchmark", "SELECT b", [{"Carrier": "X", "P": 3}]),
            _ev("survey", "market_context", "SELECT c", [{"Score": 7.1}]),
        ],
        # The first-per-flow fields are still set on analyst turns; they must
        # NOT shadow the full evidence.
        "gpr_query_result": [{"Year": 2023, "P": 1}, {"Year": 2024, "P": 2}],
    }
    data = _gather_rows(state)
    assert set(data) == {
        "gpr:temporal_trend",
        "gpr:peer_benchmark",
        "survey:market_context",
    }


def test_analyst_evidence_dedupes_by_sql_and_caps_entries():
    rows = [{"a": 1}, {"a": 2}]
    state = {
        "analyst_evidence": [
            _ev("gpr", "lens_a", "SELECT  x", rows),
            _ev("gpr", "lens_b", "select x", rows),  # same SQL modulo whitespace/case
        ]
        + [_ev("gpr", f"lens_{i}", f"SELECT {i}", rows) for i in range(20)],
    }
    data = _gather_rows(state)
    assert "gpr:lens_a" in data
    assert "gpr:lens_b" not in data  # deduped
    assert len(data) == 8  # capped at _MAX_EVIDENCE_SETS


def test_duplicate_lens_names_do_not_collide():
    state = {
        "analyst_evidence": [
            _ev("gpr", "trend", "SELECT a", [{"a": 1}, {"a": 2}]),
            _ev("gpr", "trend", "SELECT b", [{"b": 1}, {"b": 2}]),
        ],
    }
    data = _gather_rows(state)
    assert len(data) == 2


def test_deterministic_turn_falls_back_to_per_flow_fields():
    state = {
        "analyst_evidence": [],
        "gpr_query_result": [{"Year": 2024, "P": 5}],
        "survey_query_result": [{"Score": 7.0}],
    }
    data = _gather_rows(state)
    assert set(data) == {"premium", "survey"}
