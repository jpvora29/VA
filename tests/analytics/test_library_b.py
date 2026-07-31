"""Golden tests for Phase 2 Tranche B primitives, over in-memory SQLite.

Covers the peer-table primitives (registry `peer_columns`), SoW, NPS, the survey
attribute breakdown, and the survey composite `find_service_gaps`. One `Peers`
table carries both flows' peer-lookup columns (Carrier_Group/Overall_Peer_Group
for GPR; Carrier/Country/Peers for survey), mirroring the single shared table.

Run:  pytest tests/analytics/test_library_b.py -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.analytics import (
    PrimitiveArgs,
    compute_attribute_breakdown,
    compute_nps,
    compute_peer_average,
    compute_share_of_wallet,
    find_service_gaps,
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
                {"cg": "Zurich", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 150.0},
                {"cg": "Zurich", "co": "Canada", "pl": "Cyber", "yr": 2024, "pr": 50.0},
                {"cg": "AIG", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 100.0},
                {"cg": "AIG", "co": "Canada", "pl": "Cyber", "yr": 2024, "pr": 300.0},
                {"cg": "AIG", "co": "Canada", "pl": "Marine", "yr": 2024, "pr": 200.0},
                {"cg": "Chubb", "co": "Canada", "pl": "Property", "yr": 2024, "pr": 200.0},
            ],
        )
        conn.execute(text(
            'CREATE TABLE Carriers (Carrier TEXT, SurveyCountry TEXT, SurveyPractice TEXT, '
            'Attribute TEXT, Survey_Year INTEGER, Score REAL, "NPS Score" REAL)'
        ))
        conn.execute(
            text('INSERT INTO Carriers (Carrier, SurveyCountry, SurveyPractice, Attribute, '
                 'Survey_Year, Score, "NPS Score") VALUES (:c, :co, :p, :a, :y, :s, :n)'),
            [
                {"c": "Zurich", "co": "Singapore", "p": "Property", "a": "Responsiveness", "y": 2024, "s": 6.0, "n": 10},
                {"c": "Zurich", "co": "Singapore", "p": "Property", "a": "Accuracy", "y": 2024, "s": 8.0, "n": 9},
                {"c": "AIG", "co": "Singapore", "p": "Property", "a": "Responsiveness", "y": 2024, "s": 9.0, "n": 10},
                {"c": "Chubb", "co": "Singapore", "p": "Property", "a": "Responsiveness", "y": 2024, "s": 7.0, "n": 6},
            ],
        )
        # One shared Peers table holding both flows' peer-lookup columns.
        conn.execute(text(
            'CREATE TABLE Peers (Carrier_Group TEXT, Overall_Peer_Group TEXT, '
            'Carrier TEXT, Country TEXT, Peers TEXT)'
        ))
        conn.execute(
            text('INSERT INTO Peers (Carrier_Group, Overall_Peer_Group, Carrier, Country, Peers) '
                 'VALUES (:cg, :opg, :c, :co, :p)'),
            [
                # GPR peers — Country scopes the group, same as the live table.
                {"cg": "Zurich", "opg": "AIG", "c": None, "co": "Canada", "p": None},
                {"cg": "Zurich", "opg": "Chubb", "c": None, "co": "Canada", "p": None},
                # A different market gets a different group — proves the scoping.
                {"cg": "Zurich", "opg": "Allianz", "c": None, "co": "Mexico", "p": None},
                {"cg": None, "opg": None, "c": "Zurich", "co": "Singapore", "p": "AIG"},   # survey peers
                {"cg": None, "opg": None, "c": "Zurich", "co": "Singapore", "p": "Chubb"},
            ],
        )
    return eng


# ── compute_peer_average — both flows ──────────────────────────────────────

def test_peer_average_gpr_premium(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024})
    facts = compute_peer_average(args, engine=engine)
    # Zurich's GPR peers = AIG, Chubb. AVG(Premium) over their rows per product:
    # Property AVG(100, 200)=150; Cyber AVG(300)=300; Marine AVG(200)=200.
    assert {f.dims["Product_Line"]: f.value for f in facts} == {
        "Property": 150.0, "Cyber": 300.0, "Marine": 200.0,
    }


def test_peer_average_gpr_is_scoped_by_country(engine):
    """`peer_columns.country` scopes the group per market, so the same subject
    benchmarks against a DIFFERENT peer set in a different country."""
    def peers_for(country):
        args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                             filters={"Country": country, "Carrier_Group": "Zurich", "Year": 2024})
        return {f.dims["Product_Line"]: f.value for f in compute_peer_average(args, engine=engine)}

    # Canada peers = AIG, Chubb (rows exist). Mexico's peer is Allianz, who writes
    # nothing in the fixture — so the scoped lookup returns no peer rows at all.
    assert peers_for("Canada")
    assert peers_for("Mexico") == {}


def test_peer_average_survey_score(engine):
    args = PrimitiveArgs(flow="survey", metric="score", group_by=("SurveyPractice",),
                         filters={"SurveyCountry": "Singapore", "Carrier": "Zurich", "Survey_Year": 2024})
    facts = compute_peer_average(args, engine=engine)
    # Zurich's survey peers in Singapore = AIG, Chubb. AVG(Score) over Property = AVG(9, 7) = 8.0.
    assert {f.dims["SurveyPractice"]: f.value for f in facts} == {"Property": 8.0}


def test_peer_average_excludes_the_subject(engine):
    # Subject Zurich must NOT be in its own peer average.
    args = PrimitiveArgs(flow="survey", metric="score", group_by=("SurveyPractice",),
                         filters={"SurveyCountry": "Singapore", "Carrier": "Zurich", "Survey_Year": 2024})
    fact = compute_peer_average(args, engine=engine)[0]
    assert fact.value == 8.0   # not pulled toward Zurich's 7.0 average


# ── compute_share_of_wallet ────────────────────────────────────────────────

def test_share_of_wallet_gpr(engine):
    args = PrimitiveArgs(flow="gpr", metric="premium", group_by=("Product_Line",),
                         filters={"Country": "Canada", "Carrier_Group": "Zurich", "Year": 2024})
    facts = compute_share_of_wallet(args, engine=engine)
    # Property: 150 / (150+100+200=450) = 33.3%; Cyber: 50 / (50+300=350) = 14.3%.
    assert {f.dims["Product_Line"]: f.value for f in facts} == {"Property": 33.3, "Cyber": 14.3}


# ── compute_nps ────────────────────────────────────────────────────────────

def test_nps_gpr_promoters_minus_detractors(engine):
    args = PrimitiveArgs(flow="survey", metric="nps", group_by=("SurveyPractice",),
                         filters={"SurveyCountry": "Singapore", "Carrier": "Zurich", "Survey_Year": 2024})
    facts = compute_nps(args, engine=engine)
    # Zurich Property NPS scores [10, 9] -> both promoters -> +100.0.
    assert {f.dims["SurveyPractice"]: f.value for f in facts} == {"Property": 100.0}


# ── compute_attribute_breakdown ────────────────────────────────────────────

def test_attribute_breakdown_survey(engine):
    # NB: grouped by SurveyPractice (declared in the registry). The DB column
    # `Attribute` is NOT in the registry's survey `columns` block — it declares
    # `Attributes`/`Sections` (plural) while rules/survey.py uses the singular
    # forms. Reconcile the registry before attribute/section-level grouping works
    # end-to-end (see the chat note).
    args = PrimitiveArgs(flow="survey", metric="score", group_by=("SurveyPractice",),
                         filters={"SurveyCountry": "Singapore", "Carrier": "Zurich", "Survey_Year": 2024})
    facts = compute_attribute_breakdown(args, engine=engine)
    assert {f.dims["SurveyPractice"]: f.value for f in facts} == {"Property": 7.0}  # AVG(6, 8)
    assert facts[0].name == "attribute_breakdown"


# ── find_service_gaps (survey composite) ───────────────────────────────────

def test_find_service_gaps_flags_below_peer(engine):
    args = PrimitiveArgs(flow="survey", metric="score", group_by=("SurveyPractice",),
                         filters={"SurveyCountry": "Singapore", "Carrier": "Zurich", "Survey_Year": 2024})
    gaps = find_service_gaps(args, engine=engine)
    # Zurich Property avg 7.0 vs peer avg 8.0 -> shortfall 1.0 -> a service gap.
    assert [g.dims["SurveyPractice"] for g in gaps] == ["Property"]
    assert gaps[0].value == 1.0
    assert gaps[0].name == "service_gap"
