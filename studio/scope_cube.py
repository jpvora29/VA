"""Scope cube — the Setup preview's figures answered from a rollup, not the fact table.

The live preview shows the selected scope's total premium and the subject's market rank, and
it re-derives them on EVERY filter change. Both were full aggregate scans of the fact table:

    SELECT SUM(Premium) FROM GPR WHERE …                       -- the total
    SELECT Carrier_Group, SUM(Premium) … GROUP BY Carrier_Group -- the rank

Their cost is linear in ROW COUNT, so a warehouse ten times the size makes the filter pane ten
times slower — which is exactly what a big dataset felt like.

Both questions, though, only ever slice on the ten FILTER columns, and premium is additive. So
a rollup at the filter grain answers them exactly:

    SELECT <filter columns>, SUM(Premium) FROM GPR GROUP BY <filter columns>

Its size is the dimensional grain, not the row count, and it does not grow with the warehouse.
Built once per data source, cached to disk as arrays, and every subsequent preview is an
indexed read of it (:mod:`studio.cube_index`): the total is a summed slice of the measure
column, and the whole ranked field is one ``bincount`` over the carrier codes.

    two aggregate scans per change  →  one rollup per dataset, then an indexed lookup

Safety, exactly as for the filter cube: a grain wider than :data:`_MAX_ROWS` declines and
returns ``None``, and a selection that constrains a column the rollup does not span is refused
(:meth:`ScopeCube.can_answer`). The caller then runs the original SQL. Same numbers either
way; only the speed differs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from logger import get_logger
from studio import cube_core, cube_store

logger = get_logger(__name__)

# The most rollup rows worth cubing. ``None`` defers to ``STUDIO_CUBE_MAX_ROWS``, read at call
# time (see :func:`studio.cube_store.max_rows` and the note in :mod:`studio.filter_cube`).
_MAX_ROWS: Optional[int] = None


@dataclass(frozen=True)
class ScopeCube:
    """A measure rolled up to the filter grain, plus the reads the preview needs."""

    data: cube_store.CubeData

    @property
    def columns(self) -> tuple:
        return self.data.columns

    @property
    def measures(self) -> np.ndarray:
        measures = self.data.measures
        return np.empty(0, dtype=np.float64) if measures is None else measures

    def can_answer(self, selected: Mapping[str, Any]) -> bool:
        """Whether every constraining column in ``selected`` is one this rollup spans."""
        return not cube_core.unknown_columns(self.columns, selected)

    def _live(self, selected: Mapping[str, Any]):
        index = self.data.index
        return index.select(index.constraints(selected))

    def total(self, selected: Mapping[str, Any]) -> float:
        """``SUM(measure)`` over the selected scope."""
        return self.data.index.sum_over(self._live(selected), self.measures)

    def totals_by(self, column: str, selected: Mapping[str, Any]) -> Dict[str, float]:
        """``{value: SUM(measure)}`` for ``column`` over the selected scope."""
        index = self.data.index
        if not index.has(column):
            return {}
        return dict(index.sums_by_code(column, self._live(selected), self.measures))

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


def from_rows(columns: Sequence[str], raw) -> ScopeCube:
    """Fold ``(dim…, measure)`` records into a cube. The measure is the LAST field."""
    return ScopeCube(cube_store.from_rows(columns, raw, measure=True))


def build_sql_rollup(engine, table: str, columns: Sequence[str],
                     measure: str) -> Optional[ScopeCube]:
    """One streamed ``GROUP BY`` over ``columns``; None when the grain is too wide."""
    data = cube_store.build_sql(engine, table, columns, measure=measure, cap=_MAX_ROWS)
    return None if data is None else ScopeCube(data)


def build_frame_rollup(frame, columns: Sequence[str], measure: str) -> Optional[ScopeCube]:
    """The same rollup for an uploaded dataset's in-memory frame."""
    data = cube_store.build_frame(frame, columns, measure=measure, cap=_MAX_ROWS)
    return None if data is None else ScopeCube(data)


# ── caching (per source, invalidated when the source changes) ────────────────

_cache: Dict[Any, Optional[ScopeCube]] = {}

# ``None`` defers to ``STUDIO_CACHE_DIR`` — see :func:`studio.filter_cube.disk_dir`.
_DISK_DIR: Optional[Path] = None


def disk_dir() -> Path:
    """Where built rollups are persisted — the same artifact the filter cube writes."""
    return _DISK_DIR or cube_store.cache_dir()


def sql_rollup(engine, table: str, columns: Sequence[str],
               measure: str) -> Optional[ScopeCube]:
    """The cached rollup for a database table — memory, then disk, then one streamed scan.

    The disk artifact is the one the filter cube builds for the same (database, columns,
    measure), so whichever of the two is asked for first pays for the scan and the other maps
    it (:func:`studio.cube_store.load_or_build_sql`).
    """
    fingerprint = cube_core.source_fingerprint(engine, table)
    key = ("sql", fingerprint, tuple(columns), measure)
    if key in _cache:
        return _cache[key]

    data = cube_store.load_or_build_sql(engine, table, columns, measure=measure,
                                        disk_dir=disk_dir(), cap=_MAX_ROWS)
    cube = None if data is None else ScopeCube(data)
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
    """Drop every cached rollup, including the shared store's copy of it."""
    _cache.clear()
    cube_store.clear()
