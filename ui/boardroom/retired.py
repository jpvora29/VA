"""The retired score widgets, read as the evidence they carried — never as their score.

Opportunity radar, the opportunity heatmap and the 2x2 positioning matrix all put a
0-100 number the model made up at the centre of the widget: a "gap score" of 80, a
cell "intensity" of 70, a carrier at (40, 70). None of those numbers had a measure
behind it, so none of them could be checked. New digests stopped producing these
widgets (see ``core.agents.boardroom._WIDGET_SIGNATURES``), but saved boards still
hold them and must still open.

This module turns each one into plain rows of what it DID carry — the carrier's
premium, Marsh's premium, a note — and drops the score. Both the screen
(``widgets_generated``) and the slide (``ppt_export``) draw from these rows, so the
two can never disagree about what is shown.

Pure functions only: dict in, rows out.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

#: What a reader is told in place of the score.
RETIRED_NOTE = (
    "This widget used to rank items on a 0-100 score with no measure behind it. "
    "The score is no longer shown; only the figures it carried are."
)


@dataclass(frozen=True)
class EvidenceRow:
    """One item of a retired widget: its name, the figures it stated, and its note."""

    title: str
    facts: Tuple[Tuple[str, str], ...] = ()
    note: str = ""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _facts(*pairs: Tuple[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return tuple((label, _text(value)) for label, value in pairs if _text(value))


def radar_rows(data: Dict[str, Any]) -> List[EvidenceRow]:
    """Opportunity radar: each area with the two premium levels it quoted.

    Kept in the order the widget was saved in — sorting by the score would put
    the score back in charge of the page.
    """
    rows = []
    for item in (data or {}).get("opportunities") or []:
        if not isinstance(item, dict) or not _text(item.get("area")):
            continue
        rows.append(
            EvidenceRow(
                title=_text(item.get("area")),
                facts=_facts(
                    ("Dimension", _text(item.get("dimension")).title()),
                    ("Carrier", item.get("carrier_level")),
                    ("Marsh / peers", item.get("peer_level")),
                ),
                note=_text(item.get("recommendation")),
            )
        )
    return rows


def map_rows(data: Dict[str, Any]) -> List[EvidenceRow]:
    """Opportunity heatmap: one row per populated cell, named by its row and column.

    A cell's only figure was its intensity score, so what survives is where it
    was and the note written against it.
    """
    grid = (data or {}).get("opportunity_map") or {}
    rows = []
    for cell in grid.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        name = " · ".join(p for p in (_text(cell.get("row")), _text(cell.get("col"))) if p)
        if name:
            rows.append(EvidenceRow(title=name, note=_text(cell.get("note"))))
    return rows


def positioning_rows(data: Dict[str, Any]) -> List[EvidenceRow]:
    """Positioning matrix: who was compared. Both axes were scores, so no position is kept."""
    matrix = (data or {}).get("positioning") or {}
    return [
        EvidenceRow(
            title=_text(p.get("label")),
            facts=_facts(("Role", "Carrier in focus" if p.get("is_subject") else "")),
        )
        for p in matrix.get("points") or []
        if isinstance(p, dict) and _text(p.get("label"))
    ]


_ROWS: Dict[str, Callable[[Dict[str, Any]], List[EvidenceRow]]] = {
    "opportunity_radar": radar_rows,
    "opportunity_map": map_rows,
    "positioning": positioning_rows,
}

#: The widget kinds this module reads. Each also leaves the add-widget library.
RETIRED_KINDS = tuple(_ROWS)


def evidence_rows(kind: str, data: Dict[str, Any]) -> List[EvidenceRow]:
    """The evidence rows for a retired widget kind; [] for any other kind."""
    reader = _ROWS.get(kind)
    return reader(data or {}) if reader else []


def widget_note(kind: str, data: Dict[str, Any]) -> str:
    """The widget's own one-line note (heatmap legend, matrix read), if it had one.

    The heatmap's legend described the colour scale ("darker = higher priority"),
    which is gone with the score, so it is not repeated.
    """
    if kind == "positioning":
        return _text(((data or {}).get("positioning") or {}).get("note"))
    return ""


__all__ = ["EvidenceRow", "RETIRED_KINDS", "RETIRED_NOTE", "evidence_rows", "widget_note"]
