"""Where peer confidentiality is enforced, end to end.

The design decision under test: redaction happens at the EVIDENCE boundary, not
at the output. A solver keeps real peer names in its tool replies — it needs them
to write the next query's `IN (...)` list — while `evidence`, the sole input to
the insight-writer, the shown table and the chart picker, names no individual
peer. One boundary, three surfaces.
"""
from __future__ import annotations

import json

import pytest

from core.agents.analyst import common as solver_common
from core.agents.common.peer_privacy import PeerRedactor, build_policy, redactor_for
from core.graph import analyst_subgraph
from core.schemas.analyst_subgraph import SchemaSlice


PEER_ROWS = [
    {"Carrier_Group": "ZURICH GROUP", "Premium": 12_400_000},
    {"Carrier_Group": "AIG", "Premium": 9_100_000},
    {"Carrier_Group": "CHUBB", "Premium": 8_000_000},
]


class _Result:
    """Stands in for an ExecuteSQLResult."""

    def __init__(self, rows):
        self.rows = rows
        self.row_count = len(rows)
        self.error = ""


@pytest.fixture
def run_sql_tool(monkeypatch):
    """`run_sql` wired to a fake database, with the evidence list it fills."""
    monkeypatch.setattr(
        solver_common, "execute_sql", lambda flow, sql: _Result(list(PEER_ROWS))
    )
    evidence = []
    redactor = PeerRedactor(build_policy("gpr", ["ZURICH GROUP"]))
    tools = solver_common.build_tools(
        evidence,
        "Zurich premium vs peers",
        "peer_benchmark",
        peer_only=True,
        flow="gpr",
        redactor=redactor,
    )
    run_sql = next(t for t in tools if t.name == "run_sql")
    return run_sql, evidence, redactor


def test_the_solver_still_sees_real_names(run_sql_tool):
    """It must, or it cannot build the next query's IN (...) list."""
    run_sql, _evidence, _r = run_sql_tool
    reply = json.loads(run_sql.invoke({"flow": "gpr", "sql": "SELECT ..."}))
    names = [row["Carrier_Group"] for row in reply["rows"]]
    assert "AIG" in names and "CHUBB" in names


def test_recorded_evidence_names_no_peer(run_sql_tool):
    run_sql, evidence, _r = run_sql_tool
    run_sql.invoke({"flow": "gpr", "sql": "SELECT ..."})
    shown = [row["Carrier_Group"] for row in evidence[0]["rows"]]
    assert shown == ["ZURICH GROUP", "Peer 1", "Peer 2"]


def test_the_evidence_numbers_are_untouched(run_sql_tool):
    run_sql, evidence, _r = run_sql_tool
    run_sql.invoke({"flow": "gpr", "sql": "SELECT ..."})
    assert [r["Premium"] for r in evidence[0]["rows"]] == [
        12_400_000,
        9_100_000,
        8_000_000,
    ]


def test_without_a_redactor_rows_are_recorded_raw(monkeypatch):
    """The parameter is optional, so its absence must be visible in a test."""
    monkeypatch.setattr(
        solver_common, "execute_sql", lambda flow, sql: _Result(list(PEER_ROWS))
    )
    evidence = []
    tools = solver_common.build_tools(evidence, "q", "lens", peer_only=True, flow="gpr")
    next(t for t in tools if t.name == "run_sql").invoke(
        {"flow": "gpr", "sql": "SELECT ..."}
    )
    assert evidence[0]["rows"][1]["Carrier_Group"] == "AIG"


# ── the vocabulary handed forward ────────────────────────────────────────────

def test_stamp_redactions_records_what_was_hidden():
    redactor = PeerRedactor(build_policy("gpr", ["ZURICH GROUP"]))
    redactor.rows(PEER_ROWS)
    evidence = [{"flow": "gpr", "sql": "s", "rows": [], "lens": "peer_benchmark"}]
    stamped = solver_common.stamp_redactions(evidence, redactor)
    assert stamped[0]["redacted_peers"] == ("AIG", "CHUBB")


def test_stamp_redactions_adds_nothing_when_no_peer_was_hidden():
    redactor = redactor_for("gpr", {"Carrier_Group": ["ZURICH GROUP"]})
    evidence = [{"flow": "gpr", "sql": "s", "rows": [], "lens": "trend"}]
    assert "redacted_peers" not in solver_common.stamp_redactions(evidence, redactor)[0]


# ── the writer's last line of defence ────────────────────────────────────────

def _state(**over):
    base = {
        "flow": "gpr",
        "route": "premium",
        "schema_slice": SchemaSlice(resolved_values={"Carrier_Group": ["ZURICH GROUP"]}),
        "custom_peers": None,
    }
    base.update(over)
    return base


def test_a_name_that_reaches_the_prose_another_way_is_scrubbed():
    """Evidence is clean, so this covers the question-quoting path."""
    evidence = [{"rows": [], "redacted_peers": ("AIG",)}]
    out = analyst_subgraph.scrub_peer_names(
        "Zurich trails AIG on premium.", evidence, _state()
    )
    assert "AIG" not in out
    assert out == "Zurich trails a peer on premium."


def test_the_subject_survives_the_scrub():
    evidence = [{"rows": [], "redacted_peers": ("AIG",)}]
    out = analyst_subgraph.scrub_peer_names(
        "ZURICH GROUP wrote $12.4M.", evidence, _state()
    )
    assert out == "ZURICH GROUP wrote $12.4M."


def test_a_turn_with_no_peers_leaves_the_answer_alone():
    answer = "Zurich wrote $12.4M in Canada."
    assert analyst_subgraph.scrub_peer_names(answer, [{"rows": []}], _state()) == answer
