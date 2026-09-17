"""The indexed cube — the part that had to change for a real warehouse.

``tests/test_filter_cube.py`` and ``tests/test_scope_cube.py`` already pin the ANSWERS: for
any selection, the cubes must return exactly what the per-column SQL cascade and the analytics
aggregates return on the seed book. Those tests still pass unchanged, and they are the contract.

What is tested here is the reason the cubes were rebuilt: on the real book the filter grain is
millions of combinations, the cube declined past its 400k cap, and every filter change fell
back to ten ``SELECT DISTINCT … WHERE`` scans of the fact table. So these tests work at a size
the old cube refused, and pin the three properties that make that size affordable — the plan
starts from the narrowest constraint, the artifact is mapped rather than parsed, and the two
cubes share one scan of the fact table.
"""
from __future__ import annotations

import sqlite3
import time
from itertools import product

import numpy as np
import pytest
from sqlalchemy import create_engine

from studio import cube_store, filter_cube as FC, scope_cube as SC
from studio.cube_index import CubeIndex, encode_rows

# 100 countries x 40 carriers x 5 years x 3 products = 60,000 combinations, and the fact
# table carries two rows per combination. Small enough for a test suite, and the size is
# beside the point: the cap it has to clear is set to 400k below, the value that used to
# send the real book back to SQL.
_COUNTRIES = [f"C{i:03d}" for i in range(100)]
_CARRIERS = [f"Carrier {i:02d}" for i in range(40)]
_YEARS = [2021, 2022, 2023, 2024, 2025]
_PRODUCTS = ["Marine", "Cyber", "Property"]
_COLUMNS = ("Country", "Carrier_Group", "Year", "Product_Line")

_OLD_CAP = 400_000


@pytest.fixture(scope="module")
def wide_book(tmp_path_factory):
    """A book whose dimensional grain is wider than the old cube would build.

    Written with raw ``sqlite3`` and one ``executemany``: the point of the fixture is the
    shape of the data, and a slow insert would only make the suite slower.
    """
    path = tmp_path_factory.mktemp("wide") / "wide.db"
    combinations = list(product(_COUNTRIES, _CARRIERS, _YEARS, _PRODUCTS))
    rows = [(*combination, float(i % 97) + 1.0)
            for i, combination in enumerate(combinations)]
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE GPR (Country TEXT, Carrier_Group TEXT, "Year" INT, '
                     "Product_Line TEXT, Premium REAL)")
        conn.executemany("INSERT INTO GPR VALUES (?, ?, ?, ?, ?)", rows + rows)
        conn.commit()
    return path


@pytest.fixture
def wide_engine(wide_book):
    engine = create_engine(f"sqlite:///{wide_book}")
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_cubes():
    FC.clear()
    SC.clear()
    yield
    FC.clear()
    SC.clear()


def _brute_force_cascade(rows, selected):
    """The cascade computed the obvious way, to check the index against.

    Deliberately naive — a row scan per column, exactly what the cube used to do — because a
    second implementation of the fast path would only repeat its mistakes.
    """
    out = {}
    for i, column in enumerate(_COLUMNS):
        live = [row for row in rows
                if all(str(row[_COLUMNS.index(c)]) in {str(x) for x in
                       (v if isinstance(v, (list, tuple)) else [v])}
                       for c, v in selected.items() if c != column)]
        out[column] = sorted({str(row[i]) for row in live})
    return out


SELECTIONS = [
    {},
    {"Country": "C007"},
    {"Carrier_Group": "Carrier 03"},
    {"Country": ["C001", "C002"], "Year": 2024},
    {"Carrier_Group": "Carrier 03", "Product_Line": ["Cyber"], "Year": [2024, 2025]},
    {"Country": "C007", "Carrier_Group": "Carrier 03", "Year": 2023,
     "Product_Line": "Marine"},
    {"Country": "Nowhere"},                                   # matches nothing
    {"Country": "C007", "Year": 1999},                        # a real value, no rows
]


@pytest.mark.parametrize("selected", SELECTIONS, ids=lambda s: ",".join(s) or "unfiltered")
def test_a_cube_past_the_old_cap_cascades_correctly(wide_engine, selected):
    """THE regression this rebuild exists for: a grain the old cube refused, answered right."""
    cube = FC.build_sql_cube(wide_engine, "GPR", _COLUMNS)
    assert cube is not None and cube.n_rows > 0

    rows = list(product(_COUNTRIES, _CARRIERS, _YEARS, _PRODUCTS))
    expected = _brute_force_cascade(rows, selected)
    actual = {c: [str(v) for v in vals] for c, vals in cube.cascade(selected).items()}
    assert actual == expected


def test_the_cube_no_longer_declines_at_the_old_cap(wide_engine, monkeypatch):
    """The cap that sent a real warehouse back to SQL is not a limit on the answer any more.

    Resolving a selection costs what its narrowest constraint admits, not the size of the
    cube, so the cap is about memory footprint — and the old 400k would decline a book this
    shape, which is precisely what made the Setup page slow.
    """
    monkeypatch.setattr(FC, "_MAX_ROWS", _OLD_CAP)
    assert FC.build_sql_cube(wide_engine, "GPR", _COLUMNS) is not None
    # …and the cap is still honoured when it genuinely binds.
    monkeypatch.setattr(FC, "_MAX_ROWS", 10)
    assert FC.build_sql_cube(wide_engine, "GPR", _COLUMNS) is None


def test_a_cascade_on_a_wide_cube_is_fast_enough_to_type_through(wide_engine):
    """A filter change must stay in "no spinner needed" territory once the cube is built.

    The threshold is deliberately loose (a CI box under load is not a benchmark); what it
    catches is a regression back to a per-keystroke scan, which is orders out, not percent.
    """
    cube = FC.build_sql_cube(wide_engine, "GPR", _COLUMNS)
    cube.cascade({"Country": "C007"})                       # warm the posting lists

    started = time.perf_counter()
    for selected in SELECTIONS:
        cube.cascade(selected)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"{len(SELECTIONS)} cascades took {elapsed:.2f}s"


def test_the_plan_starts_from_the_narrowest_constraint():
    """The whole optimisation: the first constraint decides how many rows the rest touches.

    Year here admits nearly every row and the product admits a sixth of them, so a plan that
    started with the year would read six times the ids for the same answer.
    """
    rows = [("Japan", "Marine" if i % 6 == 0 else "Cyber", 2025) for i in range(600)]
    index, _ = encode_rows(("Country", "Product_Line", "Year"), rows)

    plans = index._plan(index.constraints({"Year": 2025, "Product_Line": "Marine"}))
    assert [column for _, column, _ in plans] == ["Product_Line", "Year"]
    assert [admitted for admitted, _, _ in plans] == [100, 600]


def test_a_value_the_cube_has_never_seen_matches_nothing():
    """An impossible selection must resolve to no rows without scanning for them."""
    index, _ = encode_rows(("Country",), [("Japan",), ("Singapore",)])
    ids = index.select(index.constraints({"Country": "Nowhere"}))
    assert ids is not None and ids.size == 0
    assert index.distinct_values("Country", ids) == []


def test_an_unconstrained_selection_is_answered_without_touching_a_row():
    """``None`` means "every row", so the commonest case in a cascade costs nothing."""
    index, _ = encode_rows(("Country",), [("Japan",), ("Singapore",)])
    assert index.select(index.constraints({})) is None
    assert index.distinct_values("Country", None) == ["Japan", "Singapore"]


def test_values_come_back_key_sorted_with_their_original_types():
    """Codes are assigned in key order, which is what makes a read come back sorted; and a
    year must stay an ``int`` or a dropdown option never matches the stored selection."""
    index, _ = encode_rows(("Year",), [(2025,), (2023,), (2024,), (2023,)])
    assert index.distinct_values("Year", None) == [2023, 2024, 2025]
    assert all(isinstance(y, int) for y in index.distinct_values("Year", None))


def test_the_measure_is_summed_over_the_selected_rows_only():
    index, measures = encode_rows(
        ("Country",), [("Japan", 10.0), ("Japan", 5.0), ("Singapore", 2.0)],
        with_measure=True)
    japan = index.select(index.constraints({"Country": "Japan"}))
    assert index.sum_over(japan, measures) == pytest.approx(15.0)
    assert index.sum_over(None, measures) == pytest.approx(17.0)
    assert dict(index.sums_by_code("Country", None, measures)) == {
        "Japan": pytest.approx(15.0), "Singapore": pytest.approx(2.0)}


# ── the disk artifact ────────────────────────────────────────────────────────


def test_the_artifact_is_mapped_from_disk_not_parsed(wide_engine, tmp_path):
    """Arrays, not JSON: a few-million-row cube as JSON costs more to parse than to query.

    Mapped means the cascade pages in only the columns it reads, so a second process (or the
    other cube) shares them instead of copying.
    """
    columns, measure = _COLUMNS, "Premium"
    built = cube_store.load_or_build_sql(wide_engine, "GPR", columns, measure=measure,
                                         disk_dir=tmp_path)
    assert built is not None and built.measures is not None

    mapped = cube_store.load_or_build_sql(wide_engine, "GPR", columns, measure=measure,
                                          disk_dir=tmp_path)
    assert isinstance(mapped.index.column("Country").codes, np.memmap)
    assert isinstance(mapped.measures, np.memmap)

    selection = {"Country": "C007", "Product_Line": "Cyber"}
    assert mapped.index.distinct_values("Carrier_Group",
                                        mapped.index.select(mapped.index.constraints(selection))) \
        == built.index.distinct_values("Carrier_Group",
                                       built.index.select(built.index.constraints(selection)))
    assert (np.asarray(mapped.measures) == np.asarray(built.measures)).all()


def test_an_incomplete_artifact_is_ignored_rather_than_half_read(wide_engine, tmp_path):
    """``meta.json`` is written last, so a build killed half way is simply not found."""
    directory = cube_store.artifact_dir(tmp_path, ("fp",), _COLUMNS, None)
    cube = cube_store.build_sql(wide_engine, "GPR", _COLUMNS)
    cube_store.write_disk(directory, cube, None)
    assert cube_store.read_disk(directory, _COLUMNS, None) is not None

    (directory / cube_store._META).unlink()
    assert cube_store.read_disk(directory, _COLUMNS, None) is None


def test_an_artifact_for_other_columns_is_not_served(wide_engine, tmp_path):
    directory = cube_store.artifact_dir(tmp_path, ("fp",), _COLUMNS, None)
    cube_store.write_disk(directory, cube_store.build_sql(wide_engine, "GPR", _COLUMNS), None)
    assert cube_store.read_disk(directory, ("Country", "Year"), None) is None
    assert cube_store.read_disk(directory, _COLUMNS, "Premium") is None


# ── one scan of the fact table, not two ──────────────────────────────────────


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


def test_the_two_cubes_share_one_scan_of_the_fact_table(wide_engine, tmp_path, monkeypatch):
    """The cascade and the preview are the same combinations at the same grain.

    Built separately they were two ``GROUP BY``s over the whole book — on an 80M-row
    warehouse, two long waits on a cold cache. Keyed on (database, columns, measure), the
    second cube finds the first one's artifact and maps it.
    """
    monkeypatch.setattr(FC, "_DISK_DIR", tmp_path)
    monkeypatch.setattr(SC, "_DISK_DIR", tmp_path)
    counting = _CountingEngine(wide_engine)

    assert FC.sql_cube(counting, "GPR", _COLUMNS, "Premium") is not None
    scanned = counting.connects
    assert scanned >= 1, "the first cube should build"

    SC.clear()                                    # a cold memory tier for the second cube
    rollup = SC.sql_rollup(counting, "GPR", _COLUMNS, "Premium")
    assert rollup is not None and rollup.total({"Country": "C007"}) > 0
    assert counting.connects == scanned, "the second cube re-scanned the fact table"


def test_the_index_is_empty_but_answerable_for_a_cube_with_no_rows():
    """An empty source must not raise — an empty form is a legitimate read-out."""
    index = CubeIndex((), {})
    assert index.n_rows == 0
    assert index.select([]) is None
    assert index.distinct_values("Country", None) == []
