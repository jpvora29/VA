"""The analyst solver reaches for a signed-off calculation before it writes SQL.

`compute_metric` has been bound to the solver for a while, but the prompt around
it still said "Use run_sql for ALL data", the lens handed over a SQL shape, and
the peer specialist's role was a SQL recipe — so a covered calculation lost to a
hand-derived query it should always win. These pin the instruction, not the
plumbing: what the solver is TOLD at the point where it chooses an approach.

Run:  pytest tests/test_solver_prefers_computed_metrics.py -q
"""
from __future__ import annotations

import pytest

from core.agents.common.analytics_tools import compute_first_directive
from core.analysis.planner import get_lens_library


def _role_of(module_path: str) -> str:
    """The `_ROLE` string literal a solver module assigns, read without importing it.

    `core.agents.analyst.peer_solver` imports `run_solver`, which pulls the whole
    data layer; these assertions are about prompt TEXT, so parsing the constant
    out of the source keeps the test honest about what ships without dragging a
    warehouse connection into a string check.
    """
    import ast
    import io

    tree = ast.parse(io.open(module_path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_ROLE" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no _ROLE assignment in {module_path}")


PEER_ROLE = _role_of("core/agents/analyst/peer_solver.py")


# ── the directive itself ─────────────────────────────────────────────────────


def test_the_directive_names_the_calculations_the_flow_can_run():
    body = compute_first_directive("gpr", "premium")
    assert "compute_peer_average_total" in body
    assert "compute_share_of_wallet" in body
    # A survey-only calculation is not offered to a GPR turn.
    assert "compute_nps" not in body


def test_a_both_route_sees_the_calculations_of_both_flows():
    body = compute_first_directive("gpr", "both")
    assert "compute_share_of_wallet" in body  # gpr
    assert "compute_nps" in body  # survey


def test_the_directive_tells_the_solver_to_prefer_it_over_sql():
    body = compute_first_directive("gpr", "premium")
    assert "PREFER THESE OVER run_sql" in body
    assert "compute_metric(" in body


def test_the_directive_is_empty_when_the_library_is_off(monkeypatch):
    """ANALYTICS_TOOLS=off restores the prompt's pure-SQL form."""
    monkeypatch.setenv("ANALYTICS_TOOLS", "off")
    assert compute_first_directive("gpr", "premium") == ""


# ── the peer specialist ──────────────────────────────────────────────────────


def test_the_peer_role_leads_with_the_computed_peer_average():
    assert "compute_peer_average_total" in PEER_ROLE
    assert "compute_peer_average'" in PEER_ROLE  # the survey-score variant


def test_the_peer_role_keeps_hand_written_sql_as_the_fallback():
    """The LOWER(TRIM) reconciliation still matters — but only after a computed
    leg comes back empty, never as the opening move."""
    assert "ONLY IF" in PEER_ROLE
    assert "LOWER(TRIM(...))" in PEER_ROLE
    # The reconciliation must come AFTER the compute instruction, not before it.
    assert PEER_ROLE.index("compute_peer_average_total") < PEER_ROLE.index("LOWER(TRIM")


# ── the lenses ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "lens, calculation",
    [
        ("peer_benchmark", "compute_peer_average_total"),
        ("market_context", "compute_market_presence"),
        ("dimensional_breakdown", "compute_breakdown"),
        ("temporal_trend", "compute_yoy_to_date"),
        ("opportunity", "compute_share_of_wallet"),
        ("whitespace", "find_whitespace"),
        ("contradiction", "compute_attribute_breakdown"),
    ],
)
def test_each_lens_names_the_calculation_that_covers_its_core_move(lens, calculation):
    body = get_lens_library().body(lens)
    assert body, f"lens {lens} not found"
    assert calculation in body


@pytest.mark.parametrize(
    "lens",
    [
        "peer_benchmark",
        "market_context",
        "dimensional_breakdown",
        "temporal_trend",
        "opportunity",
        "whitespace",
        "contradiction",
    ],
)
def test_every_lens_demotes_its_sql_shape_to_a_fallback(lens):
    """A lens may still carry a SQL recipe, but it must be labelled the fallback —
    an unqualified "SQL shape" heading reads as the primary instruction."""
    body = get_lens_library().body(lens)
    assert "fallback only" in body
