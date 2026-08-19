"""The scope cube — the Setup preview's figures served from a rollup, not two table scans.

Like the filter cube, this is a pure optimisation, so the tests that matter are EQUIVALENCE
tests: for any selection the rollup must return exactly what ``compute_breakdown`` and
``compute_rank`` returned, on the real seed database. The rest pin the properties that make
it fast (no queries once built) and safe (a selection it cannot answer falls back rather than
reporting a wider scope, and a too-wide source declines).
"""
from __future__ import annotations

import pytest

from studio import scope as SCOPE
from studio import scope_cube as SC
from studio.compute import _CARRIER_COL, _resolve_filters
from studio.data import cube_columns, get_engine

# The selections a user actually walks through, including the awkward ones: a multi-select,
# a carrier with no filters at all, and a combination that matches nothing.
SELECTIONS = [
    {"carrier": "Zurich"},
    {"carrier": "Zurich", "year": 2025},
    {"carrier": "AIG", "country": ["Singapore"]},
    {"carrier": "AIG", "country": ["Singapore", "Japan"], "year": 2025},
    {"carrier": "Chubb", "region": "Asia", "product_line": ["Marine", "Cyber"]},
    {"carrier": "Chubb", "client_segment": "Corporate", "cover_line": ["Property"]},
    {"carrier": "Zurich", "year": [2023, 2024, 2025]},
    {"carrier": "Zurich", "country": "Nowhere"},                 # matches nothing
    {"country": ["Japan"]},                                      # no subject → no rank
    {},
]


@pytest.fixture(autouse=True)
def _fresh_rollup():
    SC.clear()
    yield
    SC.clear()


def _resolved(selected):
    return _resolve_filters(selected)


def _sql_figures(selected):
    """The ORIGINAL path, forced: the two analytics aggregates."""
    resolved = _resolved(selected)
    return SCOPE._from_sql("gpr", get_engine(), _CARRIER_COL,
                           resolved.get(_CARRIER_COL), resolved)


def _rollup_figures(selected):
    return SCOPE.scope_figures(_resolved(selected), flow="gpr", engine=get_engine())


# ── equivalence: the rollup must not change a single figure ──────────────────


@pytest.mark.parametrize("selected", SELECTIONS, ids=lambda s: ",".join(s) or "unfiltered")
def test_rollup_figures_match_the_sql_aggregates(selected):
    fast, slow = _rollup_figures(selected), _sql_figures(selected)
    assert fast.total == pytest.approx(slow.total, rel=1e-9, abs=1e-6)
    assert (fast.rank, fast.of_n) == (slow.rank, slow.of_n)
    assert fast.rank_rendered == slow.rank_rendered


def test_the_rank_is_over_the_full_field_not_the_carriers_own_slice():
    """Ranking inside a market narrowed to the subject would always read '#1 of 1'."""
    figures = _rollup_figures({"carrier": "Zurich", "country": ["Singapore"]})
    assert figures.of_n and figures.of_n > 1


def test_an_impossible_scope_totals_zero_and_ranks_nothing():
    figures = _rollup_figures({"carrier": "Zurich", "country": "Nowhere"})
    assert figures.total == 0 and figures.rank is None
    assert figures.rank_rendered == "—"


# ── the property that makes it fast ──────────────────────────────────────────


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


def test_the_preview_runs_no_queries_once_the_rollup_is_built(monkeypatch, tmp_path):
    """THE performance contract: after one build, changing a filter must not touch the DB.

    This is what stops the preview scaling with the warehouse — a regression here (a rollup
    that stops being reused, or a selection that silently falls back) shows up as a wait.
    """
    monkeypatch.setattr(SC, "_DISK_DIR", tmp_path)     # an empty disk tier, so it must build
    counting = _CountingEngine(get_engine())

    SCOPE.scope_figures(_resolved({"carrier": "Zurich"}), flow="gpr", engine=counting)
    built = counting.connects
    assert built >= 1, "the first preview should build the rollup"

    for selected in SELECTIONS:
        SCOPE.scope_figures(_resolved(selected), flow="gpr", engine=counting)
    assert counting.connects == built, "a preview queried the database after the rollup was built"


# ── the properties that make it safe ─────────────────────────────────────────


def test_a_selection_outside_the_filter_grain_falls_back_to_sql():
    """A column the rollup does not span cannot be honoured, and answering anyway would
    report a WIDER scope than the user asked for — so the rollup must decline."""
    cube = SC.sql_rollup(get_engine(), "GPR", cube_columns("gpr"), "Premium")
    assert cube is not None
    assert cube.can_answer({"Country": "Japan"})
    assert not cube.can_answer({"CLIENT_NAME": "Acme Ltd"})
    # …and a blank value on such a column constrains nothing, so it is still answerable.
    assert cube.can_answer({"CLIENT_NAME": None})


def test_a_source_too_wide_to_roll_up_declines(monkeypatch):
    monkeypatch.setattr(SC, "_MAX_ROWS", 5)
    assert SC.build_sql_rollup(get_engine(), "GPR", cube_columns("gpr"), "Premium") is None


def test_an_unreadable_source_falls_back_rather_than_raising():
    assert SC.build_sql_rollup(get_engine(), "NoSuchTable", ("Country",), "Premium") is None


def test_the_figures_survive_the_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(SC, "_DISK_DIR", tmp_path)
    columns = cube_columns("gpr")

    fresh = SC.sql_rollup(get_engine(), "GPR", columns, "Premium")
    where = _resolved({"carrier": "Zurich", "country": ["Singapore"]})

    SC._cache.clear()                                  # force the disk tier
    from_disk = SC.sql_rollup(get_engine(), "GPR", columns, "Premium")
    assert from_disk.total(where) == pytest.approx(fresh.total(where))
    assert from_disk.rank(_CARRIER_COL, "Zurich", {}) == fresh.rank(_CARRIER_COL, "Zurich", {})


def test_the_rollup_is_rebuilt_when_the_database_changes(tmp_path, monkeypatch):
    """A refreshed database must not serve stale figures: the cache key carries the file's
    size+mtime, so new data invalidates both the memory and the disk tier."""
    from sqlalchemy import create_engine, text

    monkeypatch.setattr(SC, "_DISK_DIR", tmp_path / "cache")
    engine = create_engine(f"sqlite:///{tmp_path / 'small.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE GPR (Country TEXT, Premium FLOAT)"))
        conn.execute(text("INSERT INTO GPR VALUES ('Japan', 100.0)"))

    before = SC.sql_rollup(engine, "GPR", ("Country",), "Premium")
    assert before.total({}) == pytest.approx(100.0)

    with engine.begin() as conn:
        for i in range(2000):                          # enough rows to move size+mtime
            conn.execute(text("INSERT INTO GPR VALUES ('Japan', 1.0)"))

    after = SC.sql_rollup(engine, "GPR", ("Country",), "Premium")
    assert after.total({}) == pytest.approx(2100.0), "a stale rollup was served after a data change"
    engine.dispose()


# ── end to end: the preview a user reads is the deck they will get ───────────


@pytest.mark.parametrize("selected", [
    {"carrier": "Zurich", "country": ["Singapore"], "year": 2025},
    {"carrier": "AIG", "region": "Asia", "year": 2025},
])
def test_the_setup_preview_tiles_match_the_decks_own_kpis(selected):
    """The business contract, end to end.

    The Setup preview and the deck's KPI band answer the same two questions about the same
    scope, by different routes: the preview now reads the rollup, the deck runs the analytics
    primitives against the fact table. A user who reads "USD 207.9M, #5 of 12" on Setup and
    then generates must find those exact figures on the deck's first page — so this walks the
    real callback path (form filters → resolved selection → rendered tiles) and compares it
    with what ``studio.compute`` puts in the deck.
    """
    from studio.authoring.setup import _hashable, _scope_figures
    from studio.compute import _kpis
    from studio.data import get_engine
    from studio.facts import FactStore

    key = tuple(sorted((c, _hashable(v)) for c, v in selected.items()))
    tiles = {t["label"]: t["value"] for t in _scope_figures(key, None)}

    resolved = _resolved(selected)
    deck_kpis = _kpis("gpr", resolved, get_engine(), FactStore(),
                      resolved.get(_CARRIER_COL))
    by_label = {k["label"]: k["value"] for k in deck_kpis}

    assert tiles["Total GWP"] == by_label["Total GWP"]
    assert tiles["Market rank"] == by_label["Market Rank"]


def test_ties_share_a_rank_like_sql():
    cube = SC.ScopeCube(
        columns=("Carrier_Group",),
        rows=(("A",), ("B",), ("C",), ("D",)),
        measures=(10.0, 10.0, 5.0, 1.0),
    )
    assert cube.rank("Carrier_Group", "A", {}) == (1, 4)
    assert cube.rank("Carrier_Group", "B", {}) == (1, 4)
    assert cube.rank("Carrier_Group", "C", {}) == (3, 4)      # RANK() skips 2
    assert cube.rank("Carrier_Group", "Absent", {}) is None
