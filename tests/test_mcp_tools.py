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
        conn.executemany(
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
        conn.executemany(
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
