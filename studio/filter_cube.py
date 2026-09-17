"""Filter cube — every filter cascade answered from ONE cached, indexed combination set.

The Setup form's ten dropdowns each narrow to what the *other* selections allow. Done in SQL
that is one ``SELECT DISTINCT <col> … WHERE <others>`` per column — ten scans of the fact
table per keystroke, and the per-combination cache is cold every time the user picks something
new. On a warehouse of any size that is the wait.

The insight: the cascade only ever needs the DISTINCT COMBINATIONS of the filter columns, and
there are far fewer of those than fact rows — they are bounded by the real dimensional grain,
not by row count. So we read that cube ONCE per data source and answer every subsequent
cascade from memory:

    ten SQL scans per change  →  one scan per dataset, then an indexed lookup

*Indexed*, not scanned. An earlier version of this cube walked every combination in Python per
keystroke, which put it back in the business of being O(size): a real 80M-row book has
millions of combinations, the cube declined past its cap, and the cascade quietly went back to
SQL. The combinations now live in an inverted index (:mod:`studio.cube_index`) — dictionary
encoded columns plus a posting list per value — so a selection is resolved from the rows its
narrowest constraint admits, and the answer no longer depends on how big the cube is.

Safety: a source whose dimensional grain is wider than :data:`_MAX_ROWS` combinations declines
(:func:`build_sql_cube` returns ``None``) and the caller falls back to the original SQL
cascade. Correctness is identical either way; only the speed differs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from logger import get_logger
from studio import cube_core, cube_store

logger = get_logger(__name__)

# Values that mean "no constraint" on a Setup control.
BLANK = cube_core.BLANK

# The most combinations worth cubing. ``None`` defers to :func:`studio.cube_store.max_rows`,
# which reads ``STUDIO_CUBE_MAX_ROWS`` AT CALL TIME — the app loads its ``.env`` after importing
# this module, so a cap captured here would silently ignore the setting. Kept as a module
# attribute because it is the knob that decides whether a warehouse is served by cube or by SQL.
_MAX_ROWS: Optional[int] = None

# How a selection becomes constraints is shared with the scope cube (``studio.cube_core``);
# both slice the same filter grain, and they must agree on what "no constraint" means.
_as_values = cube_core.as_values


@dataclass(frozen=True)
class FilterCube:
    """The distinct combinations of the filter columns, with the cascade over them."""

    data: cube_store.CubeData

    @property
    def columns(self) -> tuple:
        return self.data.columns

    @property
    def n_rows(self) -> int:
        return self.data.n_rows

    def values(self, column: str, selected: Mapping[str, Any]) -> Optional[List[Any]]:
        """``column``'s values that survive every OTHER selection, or None if unknown here.

        The column's own selection is skipped — a dropdown must keep offering the siblings
        of what is already chosen, or picking one value would collapse its own list to it.
        """
        index = self.data.index
        if not index.has(column):
            return None
        ids = index.select(index.constraints(selected, skip=(column,)))
        return index.distinct_values(column, ids)

    def cascade(self, selected: Mapping[str, Any]) -> Dict[str, List[Any]]:
        """``{column: surviving values}`` for EVERY column of the cube.

        One selection resolved per DISTINCT question, which is at most eleven: the columns
        with no selection of their own all ask the same question (every constraint applies),
        so they share one answer; each constrained column asks its own (its own constraint
        lifted). Each is an index lookup, so a cascade is bounded by the constraints the user
        has actually made — never by the size of the cube.
        """
        index = self.data.index
        constraints = index.constraints(selected)
        constrained = {column for column, _ in constraints}
        unconstrained_ids = index.select(constraints)

        out: Dict[str, List[Any]] = {}
        for column in self.columns:
            if column in constrained:
                others = [(c, keys) for c, keys in constraints if c != column]
                ids = index.select(others)
            else:
                ids = unconstrained_ids
            out[column] = index.distinct_values(column, ids)
        return out


# ── building (once per source) ───────────────────────────────────────────────


def build_sql_cube(engine, table: str, columns: Sequence[str],
                   measure: Optional[str] = None) -> Optional[FilterCube]:
    """One streamed pass over ``columns``; None when the grain is too wide to be worth it.

    ``measure`` is not used by the cascade. It is accepted so the artifact this writes is the
    SAME one the scope cube needs (:mod:`studio.scope_cube`), which is what keeps a cold start
    to one scan of the fact table instead of two.
    """
    data = cube_store.build_sql(engine, table, columns, measure=measure, cap=_MAX_ROWS)
    return None if data is None else FilterCube(data)


def build_frame_cube(frame, columns: Sequence[str]) -> Optional[FilterCube]:
    """The same cube for an uploaded dataset's in-memory frame."""
    data = cube_store.build_frame(frame, columns, cap=_MAX_ROWS)
    return None if data is None else FilterCube(data)


# ── caching (per source, invalidated when the source changes) ────────────────

_cache: Dict[Any, Optional[FilterCube]] = {}
_DISK_DIR = Path(__file__).resolve().parent / "_cache"


_sql_fingerprint = cube_core.source_fingerprint


def disk_dir() -> Path:
    """Where built cubes are persisted — read through a function so tests can redirect it."""
    return _DISK_DIR


def sql_cube(engine, table: str, columns: Sequence[str],
             measure: Optional[str] = None) -> Optional[FilterCube]:
    """The cached cube for a database table — memory, then disk, then one streamed scan.

    The disk tier is what makes a big warehouse bearable: the scan is invalidated by the
    database's own size+mtime, so only the FIRST launch for a given dataset pays for it.
    """
    fingerprint = _sql_fingerprint(engine, table)
    key = ("sql", fingerprint, tuple(columns), measure)
    if key in _cache:
        return _cache[key]

    data = cube_store.load_or_build_sql(engine, table, columns, measure=measure,
                                        disk_dir=_DISK_DIR, cap=_MAX_ROWS)
    cube = None if data is None else FilterCube(data)
    _cache[key] = cube
    return cube


def frame_cube(dataset_id: str, frame, columns: Sequence[str]) -> Optional[FilterCube]:
    """The cached cube for an uploaded dataset (keyed by its id)."""
    key = ("frame", dataset_id, tuple(columns))
    if key not in _cache:
        _cache[key] = build_frame_cube(frame, columns)
    return _cache[key]


def clear() -> None:
    """Drop every cached cube and cascade (after a data refresh, or in tests)."""
    _cache.clear()
    _cascade_cache.clear()


# ── memoized cascades ────────────────────────────────────────────────────────

# A user revisits the same scope constantly while trying filter combinations, so the last few
# hundred cascades are worth keeping. Bounded, and dropped whenever a cube is.
_CASCADE_CACHE_MAX = 512
_cascade_cache: Dict[Any, Dict[str, List[Any]]] = {}


def _selection_key(selected: Mapping[str, Any]) -> tuple:
    return tuple(sorted((c, _as_values(v)) for c, v in (selected or {}).items()))


def cascade(cube: Optional[FilterCube],
            selected: Mapping[str, Any]) -> Dict[str, List[Any]]:
    """``{column: surviving values}`` for ``selected``, memoized per (cube, selection)."""
    if cube is None:
        return {}
    key = (id(cube), _selection_key(selected))
    hit = _cascade_cache.get(key)
    if hit is None:
        if len(_cascade_cache) >= _CASCADE_CACHE_MAX:
            _cascade_cache.clear()
        hit = _cascade_cache[key] = cube.cascade(selected)
    return hit
