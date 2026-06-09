"""Step-3 DistinctValueRegistry — against an in-memory SQLite DB (no creds).

The engine is injected via `engine_provider`, so this runs anywhere.

Run:  pytest tests/registry/test_values.py -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.registry.values import DistinctValueRegistry


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        # 'Carriers' is one of survey's allowed_tables in the registry.
        conn.execute(text("CREATE TABLE Carriers (Carrier TEXT, Score INTEGER)"))
        conn.execute(
            text("INSERT INTO Carriers (Carrier, Score) VALUES (:c, :s)"),
            [
                {"c": "Zurich", "s": 7},
                {"c": "AIG", "s": 8},
                {"c": "Zurich", "s": 6},   # duplicate carrier
                {"c": None, "s": 5},        # null carrier
            ],
        )
    return eng


def test_distinct_dedups_and_skips_null(engine):
    reg = DistinctValueRegistry(engine_provider=lambda: engine)
    assert reg.distinct("Carriers", "Carrier") == ["AIG", "Zurich"]


def test_unknown_column_returns_empty(engine):
    reg = DistinctValueRegistry(engine_provider=lambda: engine)
    assert reg.distinct("Carriers", "NoSuchColumn") == []


def test_unknown_table_returns_empty(engine):
    reg = DistinctValueRegistry(engine_provider=lambda: engine)
    assert reg.distinct("NoSuchTable", "Carrier") == []


def test_cache_holds_until_refresh(engine):
    reg = DistinctValueRegistry(engine_provider=lambda: engine)
    assert reg.distinct("Carriers", "Carrier") == ["AIG", "Zurich"]
    # Mutate the table; cached result should NOT change until refresh().
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO Carriers (Carrier) VALUES ('Allianz')"))
    assert reg.distinct("Carriers", "Carrier") == ["AIG", "Zurich"]  # cached
    reg.refresh()
    assert reg.distinct("Carriers", "Carrier") == ["AIG", "Allianz", "Zurich"]


def test_for_flow_column_searches_allowed_tables(engine):
    reg = DistinctValueRegistry(engine_provider=lambda: engine)
    # survey allowed_tables = [Carriers, Peers]; Carrier lives in Carriers.
    assert reg.for_flow_column("survey", "Carrier") == ["AIG", "Zurich"]
    assert reg.for_flow_column("survey", "Nope") == []
