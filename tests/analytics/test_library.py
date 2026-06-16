"""Golden tests for the Phase 2 primitive library, over an in-memory SQLite DB.

Tiny, hand-verified datasets so every expected number is checkable by eye. The
engine is injected, so these run anywhere (no creds, no warehouse). Shared
primitives are exercised on BOTH flows (GPR SUM(premium), survey AVG(score)) to
prove flow-agnosticism.

Run:  pytest tests/analytics/test_library.py -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.analytics import (
    PrimitiveArgs,
    compute_breakdown,
    compute_market_presence,
    compute_rank,
    compute_share_of_portfolio,
    compute_yoy,
    find_whitespace,
)


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
                {"cg": "Zurich", "co": "Canada", "pl": "Property", "yr": 2023, "pr": 100.0},
                {"cg": "Zurich", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 150.0},
                {"cg": "Zurich", "co": "Canada", "pl": "Cyber", "yr": 2024, "pr": 50.0},
                {"cg": "AIG", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 100.0},
                {"cg": "AIG", "co": "Canada", "pl": "Cyber", "yr": 2024, "pr": 300.0},
                {"cg": "AIG", "co": "Canada", "pl": "Marine", "yr": 2024, "pr": 200.0},
            ],
        )
        conn.execute(text(
            'CREATE TABLE Carriers (Carrier TEXT, SurveyPractice TEXT, Attribute TEXT, '
            'Survey_Year INTEGER, Score REAL)'
        ))
        conn.execute(
            text('INSERT INTO Carriers (Carrier, SurveyPractice, Attribute, Survey_Year, Score) '
                 'VALUES (:c, :p, :a, :y, :s)'),
            [
                {"c": "Zurich", "p": "Property", "a": "Responsiveness", "y": 2024, "s": 6.0},
                {"c": "Zurich", "p": "Property", "a": "Accuracy", "y": 2024, "s": 8.0},
                {"c": "AIG", "p": "Property", "a": "Responsiveness", "y": 2024, "s": 9.0},
            ],
        )
    return eng


def _by_dim(facts, key):
    return {tuple(sorted(f.dims.items())): f for f in facts}


# ── compute_breakdown — both flows ─────────────────────────────────────────

def test_breakdown_gpr_sum_premium(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024})
    facts = compute_breakdown(args, engine=engine)
    got = {f.dims["Product_Line"]: f.value for f in facts}
    assert got == {"Property": 150.0, "Cyber": 50.0}
    assert facts[0].dims["Product_Line"] == "Property"  # ordered by value desc
    assert facts[0].support == [{"Product_Line": "Property", "value": 150.0}]


def test_breakdown_survey_avg_score(engine):
    args = PrimitiveArgs(flow="survey", metric="score", group_by=("SurveyPractice",),
                         filters={"Carrier": "Zurich", "Survey_Year": 2024})
    facts = compute_breakdown(args, engine=engine)
    # AVG(6, 8) = 7.0  — proves the registry drives AVG (not SUM) for survey.
    assert {f.dims["SurveyPractice"]: f.value for f in facts} == {"Property": 7.0}


# ── compute_rank — both flows ──────────────────────────────────────────────

def test_rank_gpr_premium_within_product(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Year": 2024})
    facts = compute_rank(args, engine=engine)
    ranked = {(f.dims["Product_Line"], f.dims["entity"]): (f.value, f.support[0]["of_n"]) for f in facts}
    assert ranked[("Property", "Zurich")] == (1, 2)   # 150 > 100
    assert ranked[("Property", "AIG")] == (2, 2)
    assert ranked[("Cyber", "AIG")] == (1, 2)         # 300 > 50
    assert ranked[("Marine", "AIG")] == (1, 1)        # alone
    assert facts[0].rendered.startswith("#")


def test_rank_survey_score(engine):
    args = PrimitiveArgs(flow="survey", metric="score", group_by=("SurveyPractice",),
                         filters={"Survey_Year": 2024})
    facts = compute_rank(args, engine=engine)
    ranked = {f.dims["entity"]: f.value for f in facts}
    assert ranked["AIG"] == 1 and ranked["Zurich"] == 2   # AIG 9.0 > Zurich avg 7.0


# ── compute_yoy ────────────────────────────────────────────────────────────

def test_yoy_gpr_premium(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Carrier_Group": "Zurich"})
    facts = compute_yoy(args, engine=engine)
    # Property: 100 -> 150 = +50%; Cyber has only 2024 (no prior) -> omitted.
    assert len(facts) == 1
    assert facts[0].dims["Product_Line"] == "Property"
    assert facts[0].value == 50.0
    assert facts[0].rendered == "+50.0%"


# ── compute_share_of_portfolio ─────────────────────────────────────────────

def test_share_of_portfolio_gpr(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024})
    facts = compute_share_of_portfolio(args, engine=engine)
    # Zurich 2024 book = 200 (Property 150 + Cyber 50) -> 75% / 25%.
    got = {f.dims["Product_Line"]: f.value for f in facts}
    assert got == {"Property": 75.0, "Cyber": 25.0}
    assert facts[0].rendered == "75.0%"


# ── compute_market_presence ────────────────────────────────────────────────

def test_market_presence_excludes_carrier_filter(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024})
    facts = compute_market_presence(args, engine=engine)
    # Carrier filter dropped -> all carriers: Property 250, Cyber 350, Marine 200.
    assert {f.dims["Product_Line"]: f.value for f in facts} == {
        "Property": 250.0, "Cyber": 350.0, "Marine": 200.0,
    }


# ── find_whitespace (composite) ────────────────────────────────────────────

def test_find_whitespace_flags_absent_carrier_product(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024})
    gaps = find_whitespace(args, engine=engine)
    # Zurich has Property (150) and Cyber (50) but NO Marine, while the market
    # has Marine (200) -> Marine is the whitespace.
    assert [g.dims["Product_Line"] for g in gaps] == ["Marine"]
    assert gaps[0].value == 200.0
    assert gaps[0].name == "whitespace"
