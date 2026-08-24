"""`compute_metric` — the analyst solver asking for a metric by name, not by SQL.

The solver keeps `run_sql` for everything the library does not cover; what these
pin is that a covered ask is computed by the tested primitive, lands in the SAME
evidence contract the SQL tool uses, and fails with a usable message instead of a
wrong number.

Run:  pytest tests/test_analyst_compute_tool.py -q
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from core.agents.analyst.analytics_tool import build_compute_tool


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(
            text(
                'CREATE TABLE GPR (Carrier_Group TEXT, Country TEXT, Product_Line TEXT, '
                'Year INTEGER, Premium REAL)'
            )
        )
        conn.execute(
            text(
                'INSERT INTO GPR (Carrier_Group, Country, Product_Line, Year, Premium) '
                'VALUES (:cg, :co, :pl, :yr, :pr)'
            ),
            [
                {"cg": "ZURICH GROUP", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 150.0},
                {"cg": "ZURICH GROUP", "co": "Canada", "pl": "Cyber", "yr": 2024, "pr": 50.0},
                {"cg": "AIG", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 200.0},
            ],
        )
    return eng


_VALUES = {"zurich group": ["ZURICH GROUP"], "canada": ["Canada"]}


def matcher(_flow, _column, term):
    """Stand-in for the shared fuzzy matcher (which needs the live data layer)."""
    return list(_VALUES.get(str(term).strip().lower(), []))


def tool_for(evidence, engine, lens="dimensional_breakdown"):
    return build_compute_tool(evidence, lens, matcher=matcher, engine=engine)


def test_a_named_calculation_returns_computed_rows(engine):
    evidence = []
    out = json.loads(
        tool_for(evidence, engine).invoke(
            {
                "flow": "gpr",
                "name": "compute_share_of_portfolio",
                "group_by": ["Product_Line"],
                "filters": {"Carrier_Group": "ZURICH GROUP", "Country": "Canada", "Year": 2024},
            }
        )
    )
    # 150 of a 200 book, and 50 of it.
    assert {row["Product_Line"]: row["Share_of_Portfolio_%"] for row in out["rows"]} == {
        "Property": 75.0,
        "Cyber": 25.0,
    }


def test_the_result_joins_the_same_evidence_contract_as_run_sql(engine):
    evidence = []
    tool_for(evidence, engine, lens="market_context").invoke(
        {"flow": "gpr", "name": "compute_market_presence", "group_by": ["Product_Line"]}
    )
    assert len(evidence) == 1
    entry = evidence[0]
    assert set(entry) == {"flow", "sql", "rows", "lens"}
    assert entry["lens"] == "market_context"
    assert entry["sql"].startswith("--")           # provenance, not an executed query
    assert entry["rows"]


def test_an_unknown_calculation_is_refused_with_the_real_menu(engine):
    out = tool_for([], engine).invoke({"flow": "gpr", "name": "compute_vibes"})
    assert out.startswith("ERROR")
    assert "compute_share_of_wallet" in out         # tells the solver what it may ask for


def test_a_survey_only_calculation_is_refused_on_the_premium_flow(engine):
    out = tool_for([], engine).invoke({"flow": "gpr", "name": "compute_nps"})
    assert out.startswith("ERROR")


def test_a_hallucinated_column_is_refused_rather_than_dropped(engine):
    out = tool_for([], engine).invoke(
        {"flow": "gpr", "name": "compute_breakdown", "group_by": ["Underwriter"]}
    )
    assert out.startswith("ERROR") and "Underwriter" in out


def test_a_refusal_records_no_evidence(engine):
    evidence = []
    tool_for(evidence, engine).invoke({"flow": "gpr", "name": "compute_vibes"})
    assert evidence == []


def test_a_pinned_peer_set_is_honoured_by_a_computed_peer_average(engine):
    with engine.begin() as conn:
        conn.execute(
            text('CREATE TABLE Peers (Carrier_Group TEXT, Overall_Peer_Group TEXT, Country TEXT)')
        )
        conn.execute(
            text('INSERT INTO Peers VALUES (:a, :b, :c)'),
            [{"a": "ZURICH GROUP", "b": "AIG", "c": "Canada"}],
        )
        conn.execute(
            text('INSERT INTO GPR VALUES (:cg, :co, :pl, :yr, :pr)'),
            [{"cg": "CHUBB", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 500.0}],
        )

    evidence = []
    tool = build_compute_tool(
        evidence, "peer_benchmark", flow="gpr", peers=["CHUBB"], matcher=matcher, engine=engine
    )
    out = json.loads(
        tool.invoke(
            {
                "flow": "gpr",
                "name": "compute_peer_average_total",
                "filters": {"Carrier_Group": "ZURICH GROUP", "Country": "Canada", "Year": 2024},
            }
        )
    )
    # The pinned CHUBB (500), not the Peers-table AIG (200).
    assert out["rows"][0]["Peer_Avg_Premium"] == 500.0
