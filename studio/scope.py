"""The Setup preview's two figures — the selected scope's total, and the subject's rank.

One question ("what does this scope come to?") asked two ways, and the ONLY part of a filter
change that genuinely reads data. It is answered from the pre-aggregated rollup
(:mod:`studio.scope_cube`) whenever the rollup spans the selection, and from the analytics
primitives otherwise — same numbers, and the fallback keeps a source the rollup declines
(too wide, unreadable, filtered on a column outside the filter grain) working as before.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScopeFigures:
    """What the preview needs: the scope's measure total, and where the subject ranks."""

    total: float
    rank: Optional[int] = None
    of_n: Optional[int] = None

    @property
    def rank_rendered(self) -> str:
        """The rank as the deck writes it (``#3 of 12``), or an em dash when unranked."""
        return f"#{self.rank} of {self.of_n}" if self.rank else "—"


def _rollup_for(flow: str, engine, dataset_id: Optional[str]):
    """The cached rollup for whichever source is in use, or None if there is none."""
    from core.analytics.sql import flow_spec, resolve_measure
    from studio import scope_cube
    from studio.data import cube_columns

    spec = flow_spec(flow)
    measure, _agg = resolve_measure(spec, "premium")
    columns = cube_columns(flow)
    if not columns:
        return None, measure
    if dataset_id:
        from studio.dataset.source import dataset_frame

        frame = dataset_frame(dataset_id)
        if frame is None:
            return None, measure
        return scope_cube.frame_rollup(dataset_id, frame, columns, measure), measure
    return scope_cube.sql_rollup(engine, spec.primary_table, columns, measure), measure


def _from_rollup(cube, entity_column: str, subject: Any,
                 filters: Mapping[str, Any]) -> Optional[ScopeFigures]:
    """The figures read off the rollup, or None when it cannot answer this selection."""
    if cube is None or not cube.can_answer(filters):
        return None
    total = cube.total(filters)
    if not subject:
        return ScopeFigures(total=total)
    # The rank is over the FULL field, so the subject's own filter is lifted — ranking a
    # carrier against a market narrowed to itself would always return #1 of 1.
    field = {c: v for c, v in filters.items() if c != entity_column}
    placed = cube.rank(entity_column, subject, field)
    return ScopeFigures(total=total, rank=placed[0] if placed else None,
                        of_n=placed[1] if placed else None)


def _from_sql(flow: str, engine, entity_column: str, subject: Any,
              filters: Mapping[str, Any]) -> ScopeFigures:
    """The original path: one aggregate for the total, one ranked aggregate for the field."""
    from core.analytics.library import compute_breakdown, compute_rank
    from core.analytics.types import PrimitiveArgs

    totals = compute_breakdown(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=filters), engine=engine)
    total = totals[0].value if totals else 0.0
    if not subject:
        return ScopeFigures(total=total)

    field = {c: v for c, v in filters.items() if c != entity_column}
    ranked = compute_rank(
        PrimitiveArgs(flow=flow, metric="premium", group_by=(), filters=field), engine=engine)
    mine = next((f for f in ranked
                 if str(f.dims.get("entity", "")).lower() == str(subject).lower()), None)
    return ScopeFigures(total=total,
                        rank=int(mine.value) if mine else None,
                        of_n=len(ranked) if mine else None)


def scope_figures(filters: Mapping[str, Any], *, flow: str = "gpr", engine=None,
                  dataset_id: Optional[str] = None) -> ScopeFigures:
    """The preview's figures for ``filters`` (already resolved to real column names)."""
    from core.analytics.sql import flow_spec

    spec = flow_spec(flow)
    entity_column = spec.entity_columns.get("carrier", "")
    subject = filters.get(entity_column)

    cube, _measure = _rollup_for(flow, engine, dataset_id)
    from_rollup = _from_rollup(cube, entity_column, subject, filters)
    if from_rollup is not None:
        return from_rollup
    return _from_sql(flow, engine, entity_column, subject, filters)
