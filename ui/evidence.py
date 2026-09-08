"""The evidence behind an answer: one panel, one view per result set.

A turn can produce several result sets — the premium lens and the survey lens, or
the two or three cuts an analyst turn ran. They used to be appended as separate
chart blocks stacked down the transcript, so reading an answer meant scrolling
past three plots to reach the next message.

Here they become VIEWS of one panel: the reader switches between them in place,
and every view can be read as a chart or as its rows. A view with nothing
chartable is still a view — its table is the evidence — which is what gives an
answer a table even when no chart was designed for it.

This module is the data half (rows in, figures built); :mod:`ui.components.evidence`
is the rendering half.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from logger import get_logger
from ui.chart_functions import generate_chart

logger = get_logger(__name__)

# Lens key -> what the tab calls it. A view the user is switching between needs a
# business name, not a state key.
LENS_LABELS = {
    "premium": "Premium",
    "gpr": "Premium",
    "survey": "Broker survey",
    "gimmi": "GIMMI",
    "combined": "Combined",
}


@dataclass(frozen=True)
class EvidenceView:
    """One result set, ready to render: its rows, and its chart when it has one."""

    label: str
    columns: List[str]
    records: List[Dict[str, Any]]
    figure: Optional[Any] = None
    note: str = ""

    @property
    def has_chart(self) -> bool:
        return self.figure is not None


def label_for(lens: str, index: int, spec: Optional[Dict[str, Any]] = None) -> str:
    """The tab name for a view: its chart's title, its lens, else its position."""
    title = str((spec or {}).get("title") or "").strip()
    if title:
        return title
    return LENS_LABELS.get((lens or "").lower(), "") or f"View {index + 1}"


def _frame(rows: Any) -> pd.DataFrame:
    """Rows as a frame, tolerating a scalar result set (`[3]`, `["ok"]`).

    A non-list is NOT a result set — on a SQL error the rails leave an error
    STRING where the rows go, and iterating that would build a table one
    character per row.
    """
    if not isinstance(rows, (list, tuple)):
        return pd.DataFrame()
    records = [r if isinstance(r, dict) else {"value": r} for r in rows]
    return pd.DataFrame(records)


def build_view(
    rows: Sequence[Any], chart_data: Optional[Dict[str, Any]], *, label: str
) -> Optional[EvidenceView]:
    """One view from one result set, or ``None`` when there is nothing to show.

    Charting is best-effort: a spec that cannot be drawn costs the chart, never
    the table. `chart_data` that is empty (or carries no `chart_type`) simply
    means no chart was designed for this result — the rows are still evidence.
    """
    frame = _frame(rows)
    if frame.empty:
        return None

    figure, note = None, ""
    if (chart_data or {}).get("chart_type"):
        try:
            figure, note = generate_chart(df=frame, chart_outputs=chart_data)
        except Exception:  # noqa: BLE001 - a chart must never cost the answer
            logger.exception("evidence: chart generation failed for %r", label)

    return EvidenceView(
        label=label,
        columns=[str(c) for c in frame.columns],
        records=frame.to_dict("records"),
        figure=figure,
        note=(note or "").strip() if figure is None else "",
    )


def build_views(specs: Sequence[Dict[str, Any]]) -> List[EvidenceView]:
    """Every view of a turn's evidence, in the order the turn produced it.

    Each spec is ``{"rows": [...], "chart_data": {...}, "lens": "premium"}`` —
    the shape both the analyst charts and the deterministic rails already store.
    """
    views: List[EvidenceView] = []
    for i, spec in enumerate(specs or []):
        chart_data = spec.get("chart_data") or {}
        view = build_view(
            spec.get("rows"),
            chart_data,
            label=label_for(spec.get("lens") or "", i, chart_data),
        )
        if view is not None:
            views.append(view)
    return views
