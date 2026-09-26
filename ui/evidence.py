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

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from core.answers import lenses
from logger import get_logger
from ui.chart_functions import generate_chart

logger = get_logger(__name__)

# How tall a chart is INSIDE an answer card, in pixels.
#
# It is set on the FIGURE, not only in CSS, because plotly draws at its own
# default height (450px) and a CSS box of a different size does not constrain it
# — the plot simply overflowed its container and painted over the panels below.
# The stylesheet gives `.gpt-message .gpt-chart-display` the same number; this is
# the one that actually decides, and the two must stay equal.
CHART_HEIGHT_PX = 360

# The tab name for each lens: a view the user is switching between needs a
# business name, not a state key. Defined in `core.answers.lenses` because the same
# source is named again in the calculation panel under this card, and the two
# must not disagree — a tab reading "Premium" over steps reading "the gpr fact
# data" is how that goes wrong.
LENS_LABELS = lenses.LABELS


@dataclass(frozen=True)
class EvidenceView:
    """One result set, ready to render: its rows, and its chart when it has one."""

    label: str
    columns: List[str]
    records: List[Dict[str, Any]]
    figure: Optional[Any] = None
    note: str = ""
    #: {column: kind} for a result set that KNOWS how its columns should read
    #: (see `core.analytics.positioning`). Empty for a result set that does not,
    #: and the table falls back to reading the values — which is a guess, and the
    #: reason a column is typed here when the producer can say so.
    column_kinds: Dict[str, str] = field(default_factory=dict)
    #: The unit money columns are already divided by ("M", "k", ""), so the table
    #: can print it in the cell instead of only in a note above it.
    unit: str = ""

    @property
    def has_chart(self) -> bool:
        return self.figure is not None


def label_for(lens: str, index: int, spec: Optional[Dict[str, Any]] = None) -> str:
    """The tab name for a view: its short name, its chart's title, else its lens.

    A planned chart carries both a `tab` ("Quarterly") and a `title` ("Quarterly
    premium, 2024 vs 2025 in Singapore"). The tab strip wants the first — a strip
    of full titles wraps to three lines and stops being a strip — while the chart
    itself keeps the title that says exactly what it shows.
    """
    tab = str((spec or {}).get("tab") or "").strip()
    if tab:
        return tab
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
    rows: Sequence[Any], chart_data: Optional[Dict[str, Any]], *, label: str,
    note: str = "", column_kinds: Optional[Dict[str, str]] = None, unit: str = "",
) -> Optional[EvidenceView]:
    """One view from one result set, or ``None`` when there is nothing to show.

    Charting is best-effort: a spec that cannot be drawn costs the chart, never
    the table. `chart_data` that is empty (or carries no `chart_type`) simply
    means no chart was designed for this result — the rows are still evidence.
    """
    frame = _frame(rows)
    if frame.empty:
        return None

    figure, note, fallback_note = None, "", note
    if (chart_data or {}).get("chart_type"):
        try:
            figure, note = generate_chart(df=frame, chart_outputs=chart_data)
            if figure is not None:
                # A horizontal ranking sizes itself to its row count; every other
                # chart takes the card's fixed height.
                height = figure.layout.height or CHART_HEIGHT_PX
                figure.update_layout(height=max(CHART_HEIGHT_PX, height), autosize=True)
        except Exception:  # noqa: BLE001 - a chart must never cost the answer
            logger.exception("evidence: chart generation failed for %r", label)

    return EvidenceView(
        label=label,
        columns=[str(c) for c in frame.columns],
        records=frame.to_dict("records"),
        figure=figure,
        note=(note or fallback_note or "").strip() if figure is None else "",
        column_kinds=dict(column_kinds or {}),
        unit=unit,
    )


#: Rendered views by the JSON of their specs. The transcript is re-rendered on
#: every store change (a new turn, an edit, a board tweak), and each render used
#: to rebuild EVERY past answer's Plotly figures from their rows — the cost of
#: opening a long conversation grew with its length. Specs are immutable once
#: committed, so their views can be reused. Small and bounded (LRU).
_VIEW_CACHE: "OrderedDict[str, List[EvidenceView]]" = OrderedDict()
_VIEW_CACHE_SIZE = 96
_VIEW_CACHE_LOCK = threading.Lock()


def _cache_key(specs: Sequence[Dict[str, Any]]) -> Optional[str]:
    try:
        return hashlib.sha1(
            json.dumps(list(specs or []), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError):
        return None


def build_views(specs: Sequence[Dict[str, Any]]) -> List[EvidenceView]:
    """Every view of a turn's evidence, cached by the specs that produced them."""
    key = _cache_key(specs)
    if key is not None:
        with _VIEW_CACHE_LOCK:
            hit = _VIEW_CACHE.get(key)
            if hit is not None:
                _VIEW_CACHE.move_to_end(key)
                return list(hit)
    views = _build_views(specs)
    if key is not None:
        with _VIEW_CACHE_LOCK:
            _VIEW_CACHE[key] = list(views)
            while len(_VIEW_CACHE) > _VIEW_CACHE_SIZE:
                _VIEW_CACHE.popitem(last=False)
    return views


def _build_views(specs: Sequence[Dict[str, Any]]) -> List[EvidenceView]:
    """Every view of a turn's evidence, in the order the turn produced it.

    Each spec is ``{"rows": [...], "chart_data": {...}, "lens": "premium"}`` —
    the shape both the analyst charts and the deterministic rails already store.
    """
    views: List[EvidenceView] = []
    for i, spec in enumerate(specs or []):
        chart_data = spec.get("chart_data") or {}
        # The short tab name lives on the SPEC, not inside `chart_data` (which is
        # the renderer's contract), so both are offered to the labeller.
        naming = {**chart_data, "tab": spec.get("tab", "")}
        view = build_view(
            spec.get("rows"),
            chart_data,
            label=label_for(spec.get("lens") or "", i, naming),
            note=spec.get("note", ""),
            column_kinds=spec.get("column_kinds") or {},
            unit=spec.get("unit") or "",
        )
        if view is not None:
            views.append(view)
    return views
