"""Build an editable document from an AI `BoardroomDigest`, and add library widgets.

The digest's sections become *generated* widgets (origin='generated', with an
immutable evidence snapshot), laid out across the same Summary / Visuals /
Opportunities / Battlecards pages the read-only card used. Empty sections are
skipped. Charts are referenced by spec index so the live plotly figures (rebuilt
each render from the message's chart specs) can be slotted in.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from ui.boardroom import model
from ui.boardroom.catalog import LIBRARY_BY_KIND


def build_document_from_digest(digest: Dict[str, Any], n_charts: int = 0) -> Dict[str, Any]:
    digest = digest or {}

    def w(kind, data, size="md", title=""):
        return model.make_widget(kind, data, origin="generated", size=size, title=title)

    # ── Summary page ──
    summary: List[Dict[str, Any]] = []
    if digest.get("kpis"):
        summary.append(w("kpi", {"kpis": digest["kpis"]}, size="full"))
    if digest.get("insights"):
        summary.append(w("insights", {"insights": digest["insights"]}, size="full"))
    if digest.get("headline") or digest.get("commentary") or digest.get("risks"):
        summary.append(
            w(
                "commentary",
                {
                    "headline": digest.get("headline", ""),
                    "sections": digest.get("commentary", []),
                    "risks": digest.get("risks", []),
                },
                size="full",
            )
        )
    if digest.get("comparison"):
        summary.append(w("comparison", {"comparison": digest["comparison"]}, size="full"))

    # ── Visuals page ──
    visuals: List[Dict[str, Any]] = []
    for i in range(n_charts):
        visuals.append(w("charts", {"spec_index": i}, size="lg", title=f"Chart {i + 1}"))
    if digest.get("positioning"):
        visuals.append(w("positioning", {"positioning": digest["positioning"]}, size="lg"))
    if digest.get("opportunity_map"):
        visuals.append(w("opportunity_map", {"opportunity_map": digest["opportunity_map"]}, size="full"))

    # ── Opportunities page ──
    opportunities: List[Dict[str, Any]] = []
    if digest.get("opportunities"):
        opportunities.append(w("opportunity_radar", {"opportunities": digest["opportunities"]}, size="lg"))
    if digest.get("timeline"):
        opportunities.append(w("timeline", {"timeline": digest["timeline"]}, size="lg"))

    # ── Battlecards page ──
    battle: List[Dict[str, Any]] = []
    if digest.get("battlecards"):
        battle.append(w("battlecards", {"battlecards": digest["battlecards"]}, size="full"))

    pages: List[Dict[str, Any]] = []
    if summary:
        pages.append(model.make_page("Summary", summary, icon="bi bi-clipboard2-pulse"))
    if visuals:
        pages.append(model.make_page("Visuals", visuals, icon="bi bi-graph-up-arrow"))
    if opportunities:
        pages.append(model.make_page("Opportunities", opportunities, icon="bi bi-compass"))
    if battle:
        pages.append(model.make_page("Battlecards", battle, icon="bi bi-clipboard-data"))
    if not pages:
        pages.append(model.make_page("Summary", [], icon="bi bi-clipboard2-pulse"))

    return model.make_document(
        title=digest.get("title", "Boardroom"),
        subtitle=digest.get("subtitle", ""),
        pages=pages,
    )


def blank_page(doc: Dict[str, Any], *, template: str | None = None) -> str:
    """Add a blank (or template) page; return its id."""
    def _w(kind, size="md"):
        return model.make_widget(
            kind, copy.deepcopy(LIBRARY_BY_KIND[kind]["default_data"]), origin="user",
            size=size, title=LIBRARY_BY_KIND[kind]["label"],
        )

    widgets: List[Dict[str, Any]] = []
    title = "New page"
    if template == "exec_summary":
        title = "Executive summary"
        widgets = [_w("key_message", "full"), _w("commentary", "full")]
    elif template == "actions":
        title = "Actions & owners"
        widgets = [_w("action_tracker", "full")]
    page = model.make_page(title, widgets, icon="bi bi-file-earmark-plus", template=template)
    doc.setdefault("pages", []).append(page)
    return page["id"]


def add_library_widget(doc: Dict[str, Any], page_id: str, kind: str) -> str | None:
    """Append a user-library widget to a page; return its id."""
    spec = LIBRARY_BY_KIND.get(kind)
    page = model.find_page(doc, page_id)
    if not spec or not page:
        return None
    widget = model.make_widget(
        kind,
        copy.deepcopy(spec["default_data"]),
        origin="user",
        size=spec.get("size", "md"),
        title=spec["label"],
    )
    page["widgets"].append(widget)
    return widget["id"]
