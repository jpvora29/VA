"""The filter cube — the Setup cascade served from memory instead of ten SQL scans.

The cube is a pure optimisation, so the tests that matter are EQUIVALENCE tests: for any
selection it must return exactly what the per-column ``SELECT DISTINCT … WHERE`` cascade
returned, on the real seed database. The rest pin the properties that make it fast (no
queries once built) and safe (a too-wide source falls back, types survive the disk cache).
"""
from __future__ import annotations

import pytest

from studio import filter_cube as FC
from studio.authoring.setup import cascade_filter_options
from studio.compute import FILTER_COLUMN
from studio.data import cascade_options, cube_columns, dependent_options, get_engine

# Selections a user actually walks through, including the awkward ones: a multi-select, a
# filter that narrows nothing, and a combination with no rows at all.
SELECTIONS = [
    {},
    {"carrier": "Zurich"},
    {"carrier": "Zurich", "year": 2025},
    {"carrier": "Zurich", "country": ["Singapore"]},
    {"carrier": "Zurich", "country": ["Singapore", "Japan"], "year": 2025},
    {"region": "Asia", "carrier": "AIG", "product_line": ["Marine", "Cyber"]},
    {"country": ["Japan"], "industry": ["Manufacturing"]},
    {"carrier": "Chubb", "client_segment": "Corporate", "cover_line": ["Property"]},
    {"year": [2023, 2024, 2025]},
    {"carrier": "Zurich", "country": ["Australia"], "product_line": ["Cyber"]},
    {"country": "Nowhere"},                                    # matches nothing
]


@pytest.fixture(autouse=True)
def _fresh_cube():
    FC.clear()
    yield
    FC.clear()


def _sql_cascade(selected):
    """The ORIGINAL path: one ``dependent_options`` query per column."""
    return {
        fid: [o["value"] for o in dependent_options(
            "gpr", col, {FILTER_COLUMN[c]: v for c, v in selected.items()
                         if c != fid and c in FILTER_COLUMN})]
        for fid, col in FILTER_COLUMN.items()
    }


def _cube_cascade(selected):
    return {fid: [o["value"] for o in opts]
            for fid, opts in cascade_filter_options(selected, None).items()}


# ── equivalence: the cube must not change a single answer ─────────────────────


@pytest.mark.parametrize("selected", SELECTIONS, ids=lambda s: ",".join(s) or "unfiltered")
def test_cube_cascade_matches_the_sql_cascade(selected):
    assert _cube_cascade(selected) == _sql_cascade(selected)


def test_a_columns_own_selection_does_not_collapse_its_own_list():
    """Picking Singapore must leave Japan selectable — otherwise a multi-select can never
    gain a second value, and a single-select can never be changed."""
    options = _cube_cascade({"carrier": "Zurich", "country": ["Singapore"]})
    assert "Japan" in options["country"]
    # …while a genuinely constrained column IS narrowed.
    everything = _cube_cascade({})
    assert set(options["carrier"]) <= set(everything["carrier"])


def test_an_impossible_selection_empties_the_others_but_leaves_a_way_back():
    options = _cube_cascade({"country": "Nowhere"})
    assert options["carrier"] == [] and options["product_line"] == []
    # Country keeps its full list — its own selection is skipped, which is what lets the
    # user correct a choice that matches nothing instead of being stuck with it.
    assert "Singapore" in options["country"]


def test_single_pass_cascade_matches_column_by_column():
    """``cascade`` folds ten answers out of one scan; it must agree with ``values``."""
    cube = FC.sql_cube(get_engine(), "GPR", cube_columns("gpr"))
    assert cube is not None
    for selected in SELECTIONS:
        where = {FILTER_COLUMN[c]: v for c, v in selected.items() if c in FILTER_COLUMN}
        one_pass = cube.cascade(where)
        for column in cube.columns:
            assert one_pass[column] == cube.values(column, where), (column, selected)


# ── the properties that make it fast ─────────────────────────────────────────


class _CountingEngine:
    """Wraps an engine and counts how many connections a call opens."""

    def __init__(self, engine):
        self._engine = engine
        self.connects = 0

    def connect(self):
        self.connects += 1
        return self._engine.connect()

    def __getattr__(self, name):
        return getattr(self._engine, name)


def test_a_cascade_runs_no_queries_once_the_cube_is_built(monkeypatch, tmp_path):
    """THE performance contract: after one build, changing a filter must not touch the DB.

    This is what makes the filter pane instant — a regression here (a cube that stops being
    reused, or a column that silently falls back to SQL) shows up as a wait for the user.
    """
    from studio import data as D

    monkeypatch.setattr(FC, "_DISK_DIR", tmp_path)     # an empty disk tier, so it must build
    counting = _CountingEngine(get_engine())
    monkeypatch.setattr(D, "get_engine", lambda: counting)

    cascade_options("gpr", cube_columns("gpr"), {"Carrier_Group": "Zurich"})   # builds
    built = counting.connects
    assert built >= 1, "the first cascade should build the cube"

    for selected in SELECTIONS:
        cascade_options("gpr", cube_columns("gpr"),
                        {FILTER_COLUMN[c]: v for c, v in selected.items() if c in FILTER_COLUMN})
    assert counting.connects == built, "a cascade queried the database after the cube was built"


def test_the_cube_spans_the_filter_vocabulary_only():
    """Not every entity/temporal column: ``CLIENT_NAME`` and ``Billing_Date`` are both, and
    either would make the cube as large as the fact table it is meant to avoid scanning."""
    columns = cube_columns("gpr")
    assert set(columns) == set(FILTER_COLUMN.values())
    assert "CLIENT_NAME" not in columns and "Billing_Date" not in columns


# ── the properties that make it safe ─────────────────────────────────────────


def test_a_source_too_wide_to_cube_falls_back_to_sql(monkeypatch):
    monkeypatch.setattr(FC, "_MAX_ROWS", 5)
    assert FC.build_sql_cube(get_engine(), "GPR", cube_columns("gpr")) is None
    # …and the cascade still answers correctly, just via SQL.
    FC.clear()
    monkeypatch.setattr(FC, "_MAX_ROWS", 5)
    assert _cube_cascade({"carrier": "Zurich"}) == _sql_cascade({"carrier": "Zurich"})


def test_an_unreadable_source_falls_back_rather_than_raising():
    assert FC.build_sql_cube(get_engine(), "NoSuchTable", ("Country",)) is None


def test_values_keep_their_type_through_the_disk_cache(tmp_path, monkeypatch):
    """Year is an int in the database and must reach Dash as an int — a dropdown whose
    option value is "2025" never matches a stored selection of 2025."""
    monkeypatch.setattr(FC, "_DISK_DIR", tmp_path)
    columns = cube_columns("gpr")

    fresh = FC.sql_cube(get_engine(), "GPR", columns)
    years = fresh.values("Year", {})
    assert years and all(isinstance(y, int) for y in years)

    FC._cache.clear()                                  # force the disk tier
    from_disk = FC.sql_cube(get_engine(), "GPR", columns)
    assert from_disk.values("Year", {}) == years
    assert from_disk.cascade({}) == fresh.cascade({})


def test_the_cube_is_rebuilt_when_the_database_changes(tmp_path, monkeypatch):
    """A refreshed database must not serve a stale cube: the cache key carries the file's
    size+mtime, so new data invalidates both the memory and the disk tier."""
    from sqlalchemy import create_engine, text

    monkeypatch.setattr(FC, "_DISK_DIR", tmp_path / "cache")
    engine = create_engine(f"sqlite:///{tmp_path / 'small.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE GPR (Country TEXT, Year INT)"))
        conn.execute(text("INSERT INTO GPR VALUES ('Japan', 2025)"))

    before = FC.sql_cube(engine, "GPR", ("Country", "Year"))
    assert before.values("Country", {}) == ["Japan"]
    first = FC._sql_fingerprint(engine, "GPR")

    # Enough rows to grow the file, so the fingerprint moves even though mtime has
    # only one-second resolution.
    with engine.begin() as conn:
        for i in range(2000):
            conn.execute(text("INSERT INTO GPR VALUES (:c, 2025)"), {"c": f"C{i}"})
    assert FC._sql_fingerprint(engine, "GPR") != first

    after = FC.sql_cube(engine, "GPR", ("Country", "Year"))
    assert "C0" in after.values("Country", {}), "a stale cube was served after a data change"
    engine.dispose()


# ── the uploaded-dataset twin ────────────────────────────────────────────────


def test_frame_cube_cascades_like_the_sql_one():
    import pandas as pd

    frame = pd.DataFrame({
        "Country": ["Japan", "Japan", "Singapore", "Singapore"],
        "Carrier_Group": ["AIG", "Chubb", "AIG", "Zurich"],
        "Year": [2025, 2025, 2024, 2025],
    })
    cube = FC.build_frame_cube(frame, ("Country", "Carrier_Group", "Year"))
    assert cube is not None

    assert cube.values("Carrier_Group", {"Country": "Japan"}) == ["AIG", "Chubb"]
    assert cube.values("Country", {"Carrier_Group": "Zurich"}) == ["Singapore"]
    # A column's own selection is skipped here too.
    assert cube.values("Country", {"Country": "Japan"}) == ["Japan", "Singapore"]
    assert cube.values("Year", {"Country": "Singapore"}) == [2024, 2025]
