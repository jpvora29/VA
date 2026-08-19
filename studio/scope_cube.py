"""Scope cube — the Setup preview's figures answered from a rollup, not the fact table.

The live preview shows the selected scope's total premium and the subject's market rank, and
it re-derives them on EVERY filter change. Both were full aggregate scans of the fact table:

    SELECT SUM(Premium) FROM GPR WHERE …                       -- the total
    SELECT Carrier_Group, SUM(Premium) … GROUP BY Carrier_Group -- the rank

Their cost is linear in ROW COUNT, so a warehouse ten times the size makes the filter pane
ten times slower — which is exactly what a big dataset felt like.

Both questions, though, only ever slice on the ten FILTER columns, and premium is additive.
So a rollup at the filter grain answers them exactly:

    SELECT <filter columns>, SUM(Premium), COUNT(*) FROM GPR GROUP BY <filter columns>

Its size is the dimensional grain, not the row count (a 152k-row book rolls up to ~13k rows),
and it does not grow with the warehouse — a 10M-row book with the same dimensions rolls up to
the same ~13k. Built once per data source, cached to disk like the filter cube, and every
subsequent preview is an in-memory pass:

    two aggregate scans per change  →  one rollup per dataset, then a ~2 ms scan

Safety, exactly as for the filter cube: a rollup that is not much smaller than the source is
no shortcut, so :func:`build_sql_rollup` declines past ``_MAX_ROWS`` and returns ``None``, and
a selection that constrains a column the rollup does not span is refused
(:meth:`ScopeCube.can_answer`). The caller then runs the original SQL. Same numbers either
way; only the speed differs.
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

# Above this many rollup rows the cube stops being a shortcut over the source it replaces.
_MAX_ROWS = 400_000


@dataclass(frozen=True)
class ScopeCube:
    """A measure rolled up to the filter grain, plus the two reads the preview needs."""

    columns: Tuple[str, ...]
    rows: Tuple[Tuple[str, ...], ...]
    measures: Tuple[float, ...]

    def can_answer(self, selected: Mapping[str, Any]) -> bool:
        """Whether every constraining column in ``selected`` is one this rollup spans."""
        return not cube_core.unknown_columns(self.columns, selected)

    def _live(self, selected: Mapping[str, Any]) -> Iterable[int]:
        return cube_core.matching(self.rows,
                                  cube_core.constraints_for(self.columns, selected))

    def total(self, selected: Mapping[str, Any]) -> float:
        """``SUM(measure)`` over the selected scope."""
        return sum(self.measures[i] for i in self._live(selected))

    def totals_by(self, column: str, selected: Mapping[str, Any]) -> Dict[str, float]:
        """``{value: SUM(measure)}`` for ``column`` over the selected scope."""
        try:
            at = self.columns.index(column)
        except ValueError:
            return {}
        out: Dict[str, float] = {}
        for i in self._live(selected):
            key = self.rows[i][at]
            out[key] = out.get(key, 0.0) + self.measures[i]
        return out

    def rank(self, column: str, entity: Any,
             selected: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
        """``(rank, of_n)`` for ``entity`` among ``column``'s values, or None if absent.

        Ties share a rank and the next rank is skipped — SQL's ``RANK()``, which is what the
        query this replaces used, so the read-out is unchanged.
        """
        totals = self.totals_by(column, selected)
        if not totals:
            return None
        target = cube_core.key_of(entity).lower()
        mine = next((v for k, v in totals.items() if k.lower() == target), None)
        if mine is None:
            return None
        ahead = sum(1 for v in totals.values() if v > mine)
        return ahead + 1, len(totals)


# ── building (once per source) ───────────────────────────────────────────────


def _rollup_from_rows(columns: Sequence[str],
                      raw: Iterable[Sequence[Any]]) -> ScopeCube:
    """Fold ``(dim…, measure)`` records into a cube. The measure is the LAST field."""
    rows: List[Tuple[str, ...]] = []
    measures: List[float] = []
    for record in raw:
        rows.append(tuple(cube_core.key_of(v) for v in record[:-1]))
        measures.append(float(record[-1] or 0.0))
    return ScopeCube(columns=tuple(columns), rows=tuple(rows), measures=tuple(measures))


def build_sql_rollup(engine, table: str, columns: Sequence[str],
                     measure: str) -> Optional[ScopeCube]:
    """One ``GROUP BY`` over ``columns``; None when the result is too wide to be worth it.

    ``columns``, ``table`` and ``measure`` are verified schema identifiers supplied by the
    flow registry, never user input. The row cap is applied in SQL so an unexpectedly wide
    source is cheap to reject.
    """
    quoted = ", ".join(f'"{c}"' for c in columns)
    sql = (f'SELECT {quoted}, SUM("{measure}") FROM "{table}" '
           f"GROUP BY {quoted} LIMIT {_MAX_ROWS + 1}")
    try:
        with engine.connect() as conn:
            raw = conn.execute(text(sql)).fetchall()
    except Exception as exc:  # noqa: BLE001 — a rollup is an optimisation, never a requirement
        logger.warning("scope_cube: %s rollup unavailable, falling back to SQL: %s", table, exc)
        return None
    if len(raw) > _MAX_ROWS:
        logger.warning("scope_cube: %s rolls up to >%d rows — using the aggregate queries",
                       table, _MAX_ROWS)
        return None
    cube = _rollup_from_rows(columns, raw)
    logger.info("scope_cube: %s rollup built — %d row(s) over %d column(s)",
                table, len(cube.rows), len(cube.columns))
    return cube


def build_frame_rollup(frame, columns: Sequence[str], measure: str) -> Optional[ScopeCube]:
    """The same rollup for an uploaded dataset's in-memory frame."""
    present = [c for c in columns if c in getattr(frame, "columns", ())]
    if not present or measure not in getattr(frame, "columns", ()):
        return None
    grouped = frame.groupby(present, dropna=False)[measure].sum().reset_index()
    if len(grouped) > _MAX_ROWS:
        logger.warning("scope_cube: dataset rolls up to >%d rows — using the frame scan",
                       _MAX_ROWS)
        return None
    return _rollup_from_rows(present, grouped.itertuples(index=False, name=None))


# ── caching (per source, invalidated when the source changes) ────────────────

_cache: Dict[Any, Optional[ScopeCube]] = {}
_DISK_DIR = Path(__file__).resolve().parent / "_cache"


def _read_disk(path: Path, columns: Sequence[str]) -> Optional[ScopeCube]:
    """A rollup persisted by an earlier launch, or None.

    The ``GROUP BY`` is the only expensive step and it is invalidated by the database's own
    size+mtime, so persisting it means only the FIRST launch for a given dataset pays —
    however big the warehouse is.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    if tuple(payload.get("columns", ())) != tuple(columns):
        return None
    rows = tuple(tuple(r) for r in payload.get("rows", ()))
    measures = tuple(float(m) for m in payload.get("measures", ()))
    if len(rows) != len(measures):
        return None
    return ScopeCube(columns=tuple(columns), rows=rows, measures=measures)


def _write_disk(path: Path, cube: ScopeCube) -> None:
    try:
        _DISK_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"columns": list(cube.columns),
                       "rows": [list(r) for r in cube.rows],
                       "measures": list(cube.measures)}, fh)
        tmp.replace(path)                              # atomic swap
    except (OSError, TypeError, ValueError) as exc:    # noqa: BLE001 — cache is best-effort
        logger.debug("scope_cube: disk write failed: %s", exc)


def sql_rollup(engine, table: str, columns: Sequence[str],
               measure: str) -> Optional[ScopeCube]:
    """The cached rollup for a database table — memory, then disk, then one ``GROUP BY``."""
    fingerprint = cube_core.source_fingerprint(engine, table)
    key = ("sql", fingerprint, tuple(columns), measure)
    if key in _cache:
        return _cache[key]

    path = cube_core.cache_path(_DISK_DIR, "rollup", fingerprint, tuple(columns), measure)
    cube = _read_disk(path, columns)
    if cube is not None:
        logger.info("scope_cube: %s rollup from disk cache (%d rows)", table, len(cube.rows))
    else:
        cube = build_sql_rollup(engine, table, columns, measure)
        if cube is not None:
            _write_disk(path, cube)
    _cache[key] = cube
    return cube


def frame_rollup(dataset_id: str, frame, columns: Sequence[str],
                 measure: str) -> Optional[ScopeCube]:
    """The cached rollup for an uploaded dataset (keyed by its id)."""
    key = ("frame", dataset_id, tuple(columns), measure)
    if key not in _cache:
        _cache[key] = build_frame_rollup(frame, columns, measure)
    return _cache[key]


def clear() -> None:
    """Drop every cached rollup (after a data refresh, or in tests)."""
    _cache.clear()
