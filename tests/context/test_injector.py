"""ContextInjector — node → per-audience view dispatch (Phase 0 Fix 2).

Proves the one place node→view mapping lives: each registered node gets exactly
its bundle slice, an unknown node is a loud wiring error, and the dispatch table
is injectable.

Run:  pytest tests/context/test_injector.py -q
"""
from __future__ import annotations

import pytest

from core.context.bundle import (
    ContextBundle,
    PlannerView,
    ResponseView,
    RoutingView,
    SolverView,
    SQLView,
)
from core.context.injector import ContextInjector

_SCHEMA = {"GPR": [{"Column Name": "Premium"}, {"Column Name": "Carrier_Group"}]}


def _bundle() -> ContextBundle:
    return ContextBundle(
        flow="gpr",
        query="zurich premium",
        schema_tables=_SCHEMA,
        definitions={"Premium": "gross written premium"},
        valid_values={"Country": ["US", "Canada"]},
        skills={"planner": "PLAN", "sql": "SQL", "response": "RESP"},
        valid_year_quarter=["2024"],
    )


@pytest.mark.parametrize(
    "node, view_type",
    [
        ("router", RoutingView),
        ("planner", PlannerView),
        ("sql", SQLView),
        ("solver", SolverView),
        ("response", ResponseView),
    ],
)
def test_inject_for_returns_the_nodes_own_view(node, view_type):
    injector = ContextInjector()
    view = injector.inject_for(node, _bundle())
    assert isinstance(view, view_type)


def test_supports_reports_known_nodes():
    injector = ContextInjector()
    assert injector.supports("planner") is True
    assert injector.supports("nope") is False


def test_unknown_node_is_a_loud_wiring_error():
    injector = ContextInjector()
    with pytest.raises(KeyError):
        injector.inject_for("nope", _bundle())


def test_view_table_is_injectable():
    sentinel = object()
    injector = ContextInjector(view_by_node={"custom": lambda _b: sentinel})
    assert injector.inject_for("custom", _bundle()) is sentinel
    # Default nodes are absent when a custom table is supplied.
    assert injector.supports("planner") is False
