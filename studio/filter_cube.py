"""Filter cube — every filter cascade answered from ONE cached distinct-combination set.

The Setup form's ten dropdowns each narrow to what the *other* selections allow. Done in
SQL that is one ``SELECT DISTINCT <col> … WHERE <others>`` per column — ten scans of the
fact table per keystroke, and the per-combination cache is cold every time the user picks
something new. On a warehouse of any size that is the wait.

The insight: the cascade only ever needs the DISTINCT COMBINATIONS of the filter columns,
and there are far fewer of those than fact rows — the combinations are bounded by the real
dimensional grain, not by row count (a 152k-row book collapses to ~13k tuples, ~2 MB). So we
read that cube ONCE per data source and answer every subsequent cascade from memory:

    ten SQL scans per change  →  one scan per session, then a ~2 ms in-memory filter

Safety: a source whose cube is implausibly wide (a filter column with client-level grain)
would defeat the point, so :func:`build_cube` refuses past ``_MAX_ROWS`` and returns
``None`` — the caller then falls back to the original SQL cascade. Correctness is identical
either way; only the speed differs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import text

from logger import get_logger
from studio import cube_core

logger = get_logger(__name__)

# Values that mean "no constraint" on a Setup control.
BLANK = cube_core.BLANK
# Above this many distinct combinations the cube stops being a shortcut (it would cost more
# to ship and scan than the SQL it replaces), so we decline and let SQL handle it.
_MAX_ROWS = 400_000

# How a selection becomes constraints is shared with the scope cube (``studio.cube_core``);
# both slice the same filter grain, and they must agree on what "no constraint" means.
_as_values = cube_core.as_values


@dataclass(frozen=True)
class FilterCube:
    """The distinct combinations of ``columns``, with the cascade over them.

    ``rows`` holds each combination as a tuple of strings in ``columns`` order; ``display``
    maps a column's string form back to the ORIGINAL value, so a numeric year still reaches
    Dash as an int (the dropdowns' values must keep their type to match the stored selection).
    """

    columns: Tuple[str, ...]
    rows: Tuple[Tuple[str, ...], ...]
    display: Mapping[str, Mapping[str, Any]]

    def _index(self, column: str) -> Optional[int]:
        try:
            return self.columns.index(column)
        except ValueError:
            return None

    def _matching(self, constraints: Sequence[Tuple[int, Tuple[str, ...]]]) -> Iterable[Tuple[str, ...]]:
        if not constraints:
            return self.rows
        return (row for row in self.rows
                if all(row[i] in allowed for i, allowed in constraints))

    def _constraints(self, selected: Mapping[str, Any],
                     *, skip: Tuple[str, ...] = ()) -> List[Tuple[int, Tuple[str, ...]]]:
        return cube_core.constraints_for(self.columns, selected, skip=skip)

    def values(self, column: str, selected: Mapping[str, Any]) -> Optional[List[Any]]:
        """``column``'s values that survive every OTHER selection, or None if unknown here.

        The column's own selection is skipped — a dropdown must keep offering the siblings
        of what is already chosen, or picking one value would collapse its own list to it.
        """
        i = self._index(column)
        if i is None:
            return None
        back = self.display.get(column, {})
        seen = {row[i] for row in self._matching(self._constraints(selected, skip=(column,)))}
        return [back.get(v, v) for v in sorted(seen)]

    def cascade(self, selected: Mapping[str, Any]) -> Dict[str, List[Any]]:
        """``{column: surviving values}`` for EVERY column, in a single pass over the cube.

        Asking column by column would re-scan the cube once per dropdown (ten scans, and the
        cost the cube exists to remove). One pass suffices because of how "skip the column's
        own selection" behaves: count each row's violated constraints, and

          * 0 violations → the row is live for every column;
          * exactly 1 violation → the row is live ONLY for the column it violates (that is
            precisely the column whose own constraint is skipped);
          * 2 or more → the row is live for no column.
        """
        constraints = self._constraints(selected)
        if not constraints:
            live = [(row, None) for row in self.rows]
        else:
            live = []
            for row in self.rows:
                violated = [i for i, allowed in constraints if row[i] not in allowed]
                if not violated:
                    live.append((row, None))
                elif len(violated) == 1:
                    live.append((row, violated[0]))

        seen: Dict[int, set] = {i: set() for i in range(len(self.columns))}
        for row, only in live:
            if only is None:
                for i, value in enumerate(row):
                    seen[i].add(value)
            else:
                seen[only].add(row[only])
        return {
            column: [self.display[column].get(v, v) for v in sorted(seen[i])]
            for i, column in enumerate(self.columns)
        }


# ── building (once per source) ───────────────────────────────────────────────


def _cube_from_rows(columns: Sequence[str], raw: Iterable[Sequence[Any]]) -> FilterCube:
    """Fold raw distinct tuples into a cube, remembering each value's original type."""
    columns = tuple(columns)
    display: Dict[str, Dict[str, Any]] = {c: {} for c in columns}
    rows: List[Tuple[str, ...]] = []
    for record in raw:
        keys = []
        for column, value in zip(columns, record):
            key = cube_core.key_of(value)
            display[column].setdefault(key, value)
            keys.append(key)
        rows.append(tuple(keys))
    return FilterCube(columns=columns, rows=tuple(rows), display=display)


def build_sql_cube(engine, table: str, columns: Sequence[str]) -> Optional[FilterCube]:
    """One ``SELECT DISTINCT`` over ``columns``; None when it is too wide to be worth it.

    ``columns`` are verified schema identifiers supplied by the flow registry, never user
    input. The row cap is applied in SQL so an unexpectedly wide source is cheap to reject.
    """
    quoted = ", ".join(f'"{c}"' for c in columns)
    sql = f"SELECT DISTINCT {quoted} FROM \"{table}\" LIMIT {_MAX_ROWS + 1}"
    try:
        with engine.connect() as conn:
            raw = conn.execute(text(sql)).fetchall()
    except Exception as exc:  # noqa: BLE001 — a cube is an optimisation, never a requirement
        logger.warning("filter_cube: %s cube unavailable, falling back to SQL: %s", table, exc)
        return None
    if len(raw) > _MAX_ROWS:
        logger.warning("filter_cube: %s has >%d filter combinations — using SQL cascade",
                       table, _MAX_ROWS)
        return None
    cube = _cube_from_rows(columns, raw)
    logger.info("filter_cube: %s cube built — %d combination(s) over %d column(s)",
                table, len(cube.rows), len(cube.columns))
    return cube


def build_frame_cube(frame, columns: Sequence[str]) -> Optional[FilterCube]:
    """The same cube for an uploaded dataset's in-memory frame."""
    present = [c for c in columns if c in getattr(frame, "columns", ())]
    if not present:
        return None
    unique = frame[present].drop_duplicates()
    if len(unique) > _MAX_ROWS:
        logger.warning("filter_cube: dataset has >%d filter combinations — using the frame scan",
                       _MAX_ROWS)
        return None
    return _cube_from_rows(present, unique.itertuples(index=False, name=None))


# ── caching (per source, invalidated when the source changes) ────────────────

_cache: Dict[Any, Optional[FilterCube]] = {}
_DISK_DIR = Path(__file__).resolve().parent / "_cache"


_sql_fingerprint = cube_core.source_fingerprint


def _disk_path(fingerprint: Any, columns: Sequence[str]) -> Path:
    return cube_core.cache_path(_DISK_DIR, "cube", fingerprint, tuple(columns))


def _read_disk(path: Path, columns: Sequence[str]) -> Optional[FilterCube]:
    """A cube persisted by an earlier launch, or None.

    The DISTINCT scan is the only expensive step, and it is invalidated by the database's
    own size+mtime — so persisting it means only the FIRST launch for a given dataset pays,
    however big the warehouse is.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    if tuple(payload.get("columns", ())) != tuple(columns):
        return None
    return _cube_from_rows(columns, payload.get("rows", ()))


def _write_disk(path: Path, cube: FilterCube) -> None:
    try:
        _DISK_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            # The original values (not the string keys), so types survive the round-trip.
            back = [cube.display[c] for c in cube.columns]
            json.dump({"columns": list(cube.columns),
                       "rows": [[b.get(k, k) for b, k in zip(back, row)] for row in cube.rows]}, fh)
        tmp.replace(path)                              # atomic swap
    except (OSError, TypeError, ValueError) as exc:    # noqa: BLE001 — cache is best-effort
        logger.debug("filter_cube: disk write failed: %s", exc)


def sql_cube(engine, table: str, columns: Sequence[str]) -> Optional[FilterCube]:
    """The cached cube for a database table — memory, then disk, then one DISTINCT scan."""
    fingerprint = _sql_fingerprint(engine, table)
    key = ("sql", fingerprint, tuple(columns))
    if key in _cache:
        return _cache[key]

    path = _disk_path(fingerprint, columns)
    cube = _read_disk(path, columns)
    if cube is not None:
        logger.info("filter_cube: %s cube from disk cache (%d combinations)", table, len(cube.rows))
    else:
        cube = build_sql_cube(engine, table, columns)
        if cube is not None:
            _write_disk(path, cube)
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

# A user revisits the same scope constantly while trying filter combinations, so the last
# few hundred cascades are worth keeping. Bounded, and dropped whenever a cube is.
_CASCADE_CACHE_MAX = 512
_cascade_cache: Dict[Any, Dict[str, List[Any]]] = {}


def _selection_key(selected: Mapping[str, Any]) -> Tuple:
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
