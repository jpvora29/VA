"""Analytics indexes: the plan, the one-time build, and the opt-out.

Why this exists: a Studio build issues a few thousand filtered aggregates. On an
unindexed table each is a full scan, which is what made a single-country deck take
hours. `test_the_index_is_actually_used` is the one that matters — it asserts
SQLite's own query plan picks the index, so a shape that stops matching the
queries fails here rather than silently costing minutes.
"""
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, text

from studio.indexes import (
    IndexSpec,
    auto_index_enabled,
    ensure_indexes,
    existing_indexes,
    index_plan,
    missing_indexes,
)


ROWS = [
    ("Singapore", "Zurich", "Property", "Corporate", 2024, 150.0),
    ("Singapore", "Zurich", "Cyber", "Corporate", 2024, 50.0),
    ("Singapore", "AIG", "Property", "Mid-Market", 2024, 200.0),
    ("Japan", "Zurich", "Property", "Corporate", 2024, 90.0),
]


@pytest.fixture
def engine(tmp_path):
    """A throwaway GPR-shaped database with no indexes."""
    eng = create_engine(f"sqlite:///{tmp_path / 'gpr.db'}")
    with eng.begin() as conn:
        conn.execute(text(
            'CREATE TABLE GPR (Country TEXT, Carrier_Group TEXT, Product_Line TEXT, '
            'Client_Segment TEXT, Year INTEGER, Premium REAL)'
        ))
        for row in ROWS:
            conn.execute(
                text('INSERT INTO GPR VALUES (:co, :cg, :pl, :cs, :yr, :pr)'),
                dict(zip(("co", "cg", "pl", "cs", "yr", "pr"), row)),
            )
    return eng


# ── the plan ─────────────────────────────────────────────────────────────────

def test_the_plan_is_built_from_the_registry_not_hardcoded_names():
    plan = index_plan("gpr")
    assert plan
    by_name = {spec.name: spec.columns for spec in plan}
    assert by_name["ix_studio_gpr_carrier_country_year"] == (
        "Carrier_Group", "Country", "Year", "Premium",
    )


def test_every_index_is_covering():
    """The measure rides last, so a filtered aggregate never touches the table."""
    for spec in index_plan("gpr"):
        assert spec.columns[-1] == "Premium"


def test_the_survey_flow_resolves_its_own_column_names():
    """Regression: survey's year is `Survey_Year`, and it declares four measures.

    A stricter match produced an EMPTY survey plan — silently no indexes at all.
    """
    plan = index_plan("survey")
    assert plan
    for spec in plan:
        assert "Survey_Year" in spec.columns
        assert spec.columns[-1] == "Score"


def test_a_row_grain_temporal_column_is_never_indexed():
    """Billing_Date/Month_Name would be as large as the table and no more selective."""
    for spec in index_plan("gpr"):
        assert "Billing_Date" not in spec.columns
        assert "Month_Name" not in spec.columns


def test_an_unknown_flow_plans_nothing():
    assert index_plan("nope") == ()


def test_plans_are_deduplicated():
    names = [spec.name for spec in index_plan("gpr")]
    assert len(names) == len(set(names))


# ── building them ────────────────────────────────────────────────────────────

def test_indexes_are_created_once(engine):
    made = ensure_indexes("gpr", engine)
    assert made
    assert missing_indexes("gpr", engine) == ()


def test_a_second_call_is_a_no_op(engine):
    ensure_indexes("gpr", engine)
    assert ensure_indexes("gpr", engine) == []


def test_existing_indexes_are_reported(engine):
    ensure_indexes("gpr", engine)
    have = existing_indexes(engine, "GPR")
    assert {spec.name for spec in index_plan("gpr")} <= have


def test_the_index_is_actually_used_by_the_query_planner(engine, tmp_path):
    """The point of the whole module: SQLite must CHOOSE the index.

    An index the planner ignores costs disk and buys nothing, so this asserts the
    shape still matches the WHERE clause a build issues.
    """
    ensure_indexes("gpr", engine)
    con = sqlite3.connect(tmp_path / "gpr.db")
    plan = con.execute(
        "EXPLAIN QUERY PLAN SELECT Product_Line, SUM(Premium) FROM GPR "
        "WHERE Country=? AND Carrier_Group=? AND Year=? GROUP BY Product_Line",
        ("Singapore", "Zurich", 2024),
    ).fetchall()
    detail = " ".join(str(row[-1]) for row in plan)
    assert "ix_studio_gpr" in detail, detail
    assert "SCAN GPR" not in detail, detail


def test_results_are_identical_with_and_without_indexes(engine):
    """An index may never change an answer."""
    q = text('SELECT Product_Line, SUM(Premium) FROM GPR '
             'WHERE Country=:c AND Carrier_Group=:g AND Year=:y GROUP BY Product_Line '
             'ORDER BY Product_Line')
    args = {"c": "Singapore", "g": "Zurich", "y": 2024}
    with engine.connect() as conn:
        before = conn.execute(q, args).fetchall()
    ensure_indexes("gpr", engine)
    with engine.connect() as conn:
        after = conn.execute(q, args).fetchall()
    assert before == after == [("Cyber", 50.0), ("Property", 150.0)]


def test_a_missing_table_is_survived(tmp_path):
    """A database without the flow's table gets no indexes and no exception."""
    eng = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    assert ensure_indexes("gpr", eng) == []


# ── the opt-out ──────────────────────────────────────────────────────────────

def test_auto_index_is_on_by_default(monkeypatch):
    monkeypatch.delenv("STUDIO_AUTO_INDEX", raising=False)
    assert auto_index_enabled() is True


def test_auto_index_can_be_turned_off(monkeypatch):
    """A read-only or externally-managed warehouse has to say so explicitly."""
    monkeypatch.setenv("STUDIO_AUTO_INDEX", "off")
    assert auto_index_enabled() is False
    monkeypatch.setenv("STUDIO_AUTO_INDEX", "OFF")
    assert auto_index_enabled() is False


def test_create_sql_quotes_identifiers():
    spec = IndexSpec(name="ix_x", table="GPR", columns=("Country", "NPS Score"))
    assert spec.create_sql() == (
        'CREATE INDEX IF NOT EXISTS "ix_x" ON "GPR" ("Country", "NPS Score")'
    )
