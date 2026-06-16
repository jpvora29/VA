"""Unit tests for the consolidated execute_sql tool (Phase A).

Self-contained: spins up an in-memory SQLite DB and points
`Initialization.Session` at it, so no real warehouse / env is required.

Run:  pytest tests/test_mcp_tools.py -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.initialization import Initialization
from core.mcp import tools as mcp_tools


@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Point the tool's session factory at a throwaway in-memory DB."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER, name TEXT)"))
        conn.execute(
            text("INSERT INTO t (id, name) VALUES (:id, :name)"),
            [{"id": i, "name": f"row{i}"} for i in range(1, 51)],  # 50 rows
        )
    monkeypatch.setattr(Initialization, "Session", sessionmaker(bind=engine))
    yield


def test_valid_select_returns_rows():
    result = mcp_tools.execute_sql("gpr", "SELECT id, name FROM t WHERE id <= 3")
    assert result.error is None
    assert result.ok
    assert result.row_count == 3
    assert result.rows[0] == {"id": 1, "name": "row1"}
    assert result.columns == ["id", "name"]
    assert result.overflow is False


def test_write_statement_is_blocked():
    result = mcp_tools.execute_sql("gpr", "UPDATE t SET name = 'x' WHERE id = 1")
    assert result.error is not None
    assert result.rows is None
    # Confirm the row was NOT mutated.
    check = mcp_tools.execute_sql("gpr", "SELECT name FROM t WHERE id = 1")
    assert check.rows[0]["name"] == "row1"


def test_drop_is_blocked():
    result = mcp_tools.execute_sql("gpr", "DROP TABLE t")
    assert result.error is not None
    # Table still queryable.
    assert mcp_tools.execute_sql("gpr", "SELECT COUNT(*) AS c FROM t").rows[0]["c"] == 50


def test_bad_sql_returns_error_without_raising():
    result = mcp_tools.execute_sql("gpr", "SELECT nope FROM no_such_table")
    assert result.error is not None
    assert result.rows is None


def test_overflow_flag_above_threshold():
    result = mcp_tools.execute_sql("gpr", "SELECT id FROM t")  # 50 rows > 40
    assert result.error is None
    assert result.row_count == 50
    assert result.overflow is True


# --------------------------------------------------------------------------- #
# Column-value matching (DB-backed distinct + fuzzy match)                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def gpr_db(monkeypatch):
    """A real `GPR` table so get_database_schema (4 fixed table names) works."""
    from core.data.general import GeneralFunctions

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                'CREATE TABLE "GPR" ('
                '"Carrier_Group" TEXT, "SIC_Major_Class" TEXT, "Premium" REAL)'
            )
        )
        conn.execute(
            text(
                'INSERT INTO "GPR" ("Carrier_Group","SIC_Major_Class","Premium") '
                "VALUES (:cg, :sic, :p)"
            ),
            [
                {"cg": "ZURICH GROUP", "sic": "Manufacturing", "p": 100.0},
                {"cg": "CHUBB", "sic": "Services", "p": 50.0},
                {"cg": "AXA", "sic": "Construction", "p": 25.0},
            ],
        )
    monkeypatch.setattr(mcp_tools.Initialization, "engine", engine)
    monkeypatch.setattr(mcp_tools.Initialization, "Session", sessionmaker(bind=engine))
    GeneralFunctions.clear_schema_cache()
    mcp_tools._DISTINCT_CACHE.clear()
    yield
    GeneralFunctions.clear_schema_cache()
    mcp_tools._DISTINCT_CACHE.clear()


def test_get_distinct_values_from_db(gpr_db):
    values = mcp_tools.get_distinct_values("gpr", "SIC_Major_Class")
    assert set(values) == {"Construction", "Manufacturing", "Services"}


def test_get_distinct_values_unknown_column_is_safe(gpr_db):
    # Unknown / non-schema column must not be interpolated into SQL.
    assert mcp_tools.get_distinct_values("gpr", "DROP TABLE GPR; --") == []


def test_match_column_values_fuzzy(gpr_db):
    matches = mcp_tools.match_column_values("gpr", "SIC_Major_Class", "manufactring")
    assert matches and matches[0] == "Manufacturing"


def test_match_expands_country_acronym(fake_candidates):
    # "UK" shares no string with "United Kingdom"; the value-synonym map bridges
    # it deterministically, then the exact pass returns the real stored value.
    assert mcp_tools.match_column_values("gpr", "Country", "UK") == ["United Kingdom"]
    assert mcp_tools.match_column_values("gpr", "Country", "usa") == ["United States"]


def test_match_rejects_discriminating_sibling(monkeypatch):
    monkeypatch.setattr(
        mcp_tools,
        "_candidate_values",
        lambda flow, column: {
            "Business_Line": ["Accident & Health", "Marine", "Property"],
            "Product_Line": ["Accident & Travel", "Motor"],
        }.get(column, []),
    )
    # A shared token ("accident") must not let the sibling business line absorb a
    # product term — "travel" vs "health" is a discriminating mismatch.
    assert mcp_tools.match_column_values("gpr", "Business_Line", "Accident & Travel") == []
    # The real product value still resolves (exact).
    assert mcp_tools.match_column_values(
        "gpr", "Product_Line", "Accident & Travel"
    ) == ["Accident & Travel"]


def test_match_keeps_shorter_subset(monkeypatch):
    monkeypatch.setattr(
        mcp_tools, "_candidate_values", lambda flow, column: ["SWISS RE", "SWISS LIFE"]
    )
    # "Swiss" is fully carried by the candidate (one-sided, not mutual), so the
    # subset still resolves — the guard only rejects mutual mismatches.
    assert "SWISS RE" in mcp_tools.match_column_values("gpr", "Carrier_Group", "Swiss")


# ── audit_sql_filters (zero-row guard) ───────────────────────────────────────


@pytest.fixture
def fake_candidates(monkeypatch):
    """Replace the candidate-value lookup with a fixed in-memory dictionary."""
    values = {
        "Country": ["United Kingdom", "United States", "Canada"],
        "Carrier_Group": ["ZURICH GROUP", "CHUBB LIMITED", "AXA"],
    }
    monkeypatch.setattr(
        mcp_tools, "_candidate_values", lambda flow, column: values.get(column, [])
    )
    yield


def test_audit_flags_missing_equality_value(fake_candidates):
    suspects = mcp_tools.audit_sql_filters(
        "gpr", "SELECT SUM(Premium) FROM GPR WHERE Country = 'UK'"
    )
    assert len(suspects) == 1
    assert suspects[0]["column"] == "Country"
    assert suspects[0]["value"] == "UK"


def test_audit_accepts_valid_value_case_insensitively(fake_candidates):
    sql = "SELECT * FROM GPR WHERE Country = 'united kingdom'"
    assert mcp_tools.audit_sql_filters("gpr", sql) == []


def test_audit_skips_numeric_and_unknown_columns(fake_candidates):
    sql = "SELECT * FROM GPR WHERE Year = '2024' AND Unknown_Col = 'whatever'"
    assert mcp_tools.audit_sql_filters("gpr", sql) == []


def test_audit_flags_only_the_bad_value_in_an_in_list(fake_candidates):
    sql = "SELECT * FROM GPR WHERE Country IN ('UK', 'Canada')"
    suspects = mcp_tools.audit_sql_filters("gpr", sql)
    assert [s["value"] for s in suspects] == ["UK"]


def test_audit_like_checks_wildcard_stripped_containment(fake_candidates):
    ok = "SELECT * FROM GPR WHERE Country LIKE '%Kingdom%'"
    assert mcp_tools.audit_sql_filters("gpr", ok) == []
    bad = "SELECT * FROM GPR WHERE Country LIKE '%Atlantis%'"
    suspects = mcp_tools.audit_sql_filters("gpr", bad)
    assert [s["value"] for s in suspects] == ["%Atlantis%"]


def test_audit_sees_through_upper_lower_wrapping(fake_candidates):
    sql = "SELECT * FROM GPR WHERE UPPER(Country) = 'UK'"
    suspects = mcp_tools.audit_sql_filters("gpr", sql)
    assert len(suspects) == 1 and suspects[0]["column"] == "Country"


def test_audit_suggests_close_valid_values(fake_candidates):
    sql = "SELECT * FROM GPR WHERE Carrier_Group = 'Zurich'"
    suspects = mcp_tools.audit_sql_filters("gpr", sql)
    assert len(suspects) == 1
    assert "ZURICH GROUP" in suspects[0]["suggestions"]


def test_audit_skips_unbounded_candidate_lists(monkeypatch):
    monkeypatch.setattr(
        mcp_tools,
        "_candidate_values",
        lambda flow, column: [f"v{i}" for i in range(3000)],
    )
    sql = "SELECT * FROM GPR WHERE Billing_Date = 'nope'"
    assert mcp_tools.audit_sql_filters("gpr", sql) == []
