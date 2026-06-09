"""ContextBundle per-audience views + engine assembly (decision #1).

The structural guarantee: routing/solver views never carry the full schema dump
or the full valid_values dict (the two prompt-bloat offenders). Each view is a
typed dataclass, so a leak is a field that fails these assertions.

Engine assembly is exercised with injected providers + resolver — no DB / LLM.

Run:  pytest tests/context/test_bundle_views.py -q
"""
from __future__ import annotations

from dataclasses import fields

from core.context.bundle import ContextBundle
from core.context.engine import ContextEngine
from core.context.retriever import EntityResolver

_SCHEMA = {
    "GPR": [
        {"Column Name": "Premium", "Type": "FLOAT"},
        {"Column Name": "Carrier_Group", "Type": "TEXT"},
        {"Column Name": "SIC_Major_Class", "Type": "TEXT"},
    ]
}


def _bundle(**over):
    base = dict(
        flow="gpr",
        query="manufacturing premium",
        schema_tables=_SCHEMA,
        definitions={"Premium": "gross written premium"},
        valid_values={"Country": ["US", "Canada"]},
        skills={"planner": "PLAN RULES", "sql": "SQL RULES", "response": "RESP"},
        valid_year_quarter=["2024"],
    )
    base.update(over)
    return ContextBundle(**base)


def test_routing_view_has_no_values_or_definitions():
    view = _bundle().for_routing()
    field_names = {f.name for f in fields(view)}
    assert "valid_values" not in field_names
    assert "definitions" not in field_names
    assert "schema_tables" not in field_names  # only the outline, never the dump
    # Outline is names only — no column metadata leaks through.
    assert view.schema_outline["GPR"] == ["Premium", "Carrier_Group", "SIC_Major_Class"]


def test_planner_view_carries_grounding():
    view = _bundle().for_planner()
    assert view.definitions == {"Premium": "gross written premium"}
    assert view.valid_values == {"Country": ["US", "Canada"]}
    assert view.rules == "PLAN RULES"
    assert view.valid_year_quarter == ["2024"]


def test_sql_view_uses_sql_scope_rules():
    view = _bundle().for_sql()
    assert view.rules == "SQL RULES"
    assert view.valid_values == {"Country": ["US", "Canada"]}


def test_solver_view_drops_full_schema_keeps_resolved_entities():
    from core.context.retriever import ResolvedValues

    bundle = _bundle(
        resolved_entities={
            "SIC_Major_Class": ResolvedValues(
                "SIC_Major_Class", ["Manufacture of motor vehicles"], "semantic"
            ),
            "Carrier_Group": ResolvedValues("Carrier_Group", [], "none"),
        }
    )
    view = bundle.for_solver()
    field_names = {f.name for f in fields(view)}
    assert "schema_tables" not in field_names  # no full dump for the solver
    assert view.resolved_entities == {
        "SIC_Major_Class": ["Manufacture of motor vehicles"]
    }  # empty resolutions are dropped


def test_response_view_is_definitions_only():
    view = _bundle().for_response()
    field_names = {f.name for f in fields(view)}
    assert "valid_values" not in field_names
    assert "schema_tables" not in field_names
    assert view.definitions == {"Premium": "gross written premium"}


def test_engine_build_gates_high_card_and_records_provenance():
    # Carrier_Group is high-card (101 > cap 8) -> resolver runs; semantic rescue
    # maps the conceptual query on SIC_Major_Class.
    full_values = {
        "Country": ["US", "Canada"],  # low-card -> full
        "Carrier_Group": [f"C{i}" for i in range(101)],  # high-card -> resolved
        "SIC_Major_Class": [f"SIC {i}" for i in range(50)],  # high-card semantic
    }

    def fuzzy(col, _q):
        return ["ZURICH"] if col == "Carrier_Group" else []

    def semantic(col, _q):
        return ["SIC 7"] if col == "SIC_Major_Class" else []

    resolver = EntityResolver(
        fuzzy=fuzzy,
        is_semantic=lambda c: c == "SIC_Major_Class",
        semantic=semantic,
        enabled=True,
    )

    engine = ContextEngine()
    bundle = engine.build(
        "gpr",
        "manufacturing premium for zurich",
        resolver=resolver,
        schema_provider=lambda: _SCHEMA,
        valid_values_provider=lambda: full_values,
        definitions_provider=lambda: {},
        skill_provider=lambda scope, q: f"{scope}-rules",
    )

    assert bundle.valid_values["Country"] == ["US", "Canada"]  # untouched
    assert bundle.valid_values["Carrier_Group"] == ["ZURICH"]  # fuzzy-resolved
    assert bundle.valid_values["SIC_Major_Class"] == ["SIC 7"]  # semantic-rescued
    assert bundle.resolved_entities["Carrier_Group"].source == "fuzzy"
    assert bundle.resolved_entities["SIC_Major_Class"].source == "semantic"
    assert bundle.for_planner().rules == "planner-rules"
