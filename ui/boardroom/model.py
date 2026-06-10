"""Editable Boardroom document model.

The whole editable document is plain JSON-serialisable dicts (no dataclasses) so it
round-trips cleanly through a Dash `dcc.Store` and persists with the conversation.
This module is the single source of truth for those shapes + the helpers that
construct and mutate them. Rendering and callbacks never hand-roll the shapes.

Provenance / integrity (see the product spec):
  * Every widget keeps an immutable ``generated`` snapshot of its original
    AI-produced data alongside the live ``data`` the user may edit. "Reset to
    generated" simply copies ``generated`` back over ``data``.
  * ``edited`` flips True on the first user override and drives the "Edited" badge.
  * ``history`` accumulates an audit trail entry per save ({at, by, reason, changes}).
  * User-created widgets have ``origin == "user"`` and ``generated == None`` (there is
    no AI evidence to protect), so they are freely deletable.
"""
from __future__ import annotations

import copy
import time
import uuid
from typing import Any, Dict, List, Optional

# ── Governed grid with fine-grained control ──
# Presets (sm/md/lg/full) remain the quick widths, but a widget may carry an
# explicit ``span`` (1-12 columns) and ``height_px`` (None = auto) in its meta
# for pixel-level restructuring. ``widget_span``/``widget_height`` are the only
# readers — rendering and PPT export both go through them so the on-screen
# layout and the exported deck always agree.
SIZES = ("sm", "md", "lg", "full")
SIZE_SPAN = {"sm": 3, "md": 6, "lg": 9, "full": 12}  # out of a 12-col grid
GRID_COLUMNS = 12

MIN_HEIGHT_PX = 120
MAX_HEIGHT_PX = 1000
HEIGHT_STEP_PX = 40


def widget_span(widget: Dict[str, Any]) -> int:
    """Effective column span: explicit ``span`` wins, else the size preset."""
    meta = widget.get("meta") or {}
    span = meta.get("span")
    if isinstance(span, int) and 1 <= span <= GRID_COLUMNS:
        return span
    return SIZE_SPAN.get(meta.get("size", "md"), 6)


def widget_height(widget: Dict[str, Any]) -> Optional[int]:
    """Explicit pixel height, or None for content-driven (auto) height."""
    h = (widget.get("meta") or {}).get("height_px")
    return h if isinstance(h, int) and h > 0 else None


def set_widget_span(widget: Dict[str, Any], span: int) -> None:
    """Set an explicit span (clamped 1-12) and sync ``size`` to the nearest
    preset so the S/M/L/Full buttons highlight sensibly."""
    span = max(1, min(GRID_COLUMNS, int(span)))
    meta = widget.setdefault("meta", {})
    meta["span"] = span
    meta["size"] = min(SIZE_SPAN, key=lambda s: abs(SIZE_SPAN[s] - span))


def nudge_widget_height(widget: Dict[str, Any], delta_px: int) -> None:
    """Grow/shrink a widget's fixed height by ``delta_px`` (clamped). Starting
    from auto, the first nudge anchors at a sensible base height."""
    meta = widget.setdefault("meta", {})
    current = meta.get("height_px")
    base = current if isinstance(current, int) and current > 0 else 280
    meta["height_px"] = max(MIN_HEIGHT_PX, min(MAX_HEIGHT_PX, base + delta_px))


def clear_widget_height(widget: Dict[str, Any]) -> None:
    """Back to content-driven (auto) height."""
    widget.setdefault("meta", {})["height_px"] = None


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ───────────────────────────── Widgets ──────────────────────────────


def make_widget(
    kind: str,
    data: Dict[str, Any] | None = None,
    *,
    origin: str = "generated",
    title: str = "",
    size: str = "md",
    chart_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a widget dict. `data` is the kind-specific payload (see catalog)."""
    data = data or {}
    return {
        "id": _uid("w"),
        "kind": kind,
        "origin": origin,
        "title": title,
        "data": copy.deepcopy(data),
        # Immutable evidence snapshot for generated widgets; None for user widgets.
        "generated": copy.deepcopy(data) if origin == "generated" else None,
        "meta": {
            "theme": "default",
            "size": size if size in SIZES else "md",
            "span": None,       # explicit 1-12 column span; None = follow size preset
            "height_px": None,  # fixed pixel height; None = auto (content-driven)
            "chart_type": chart_type,
            "sort": None,
            "visible_board": True,
            "visible_export": True,
            "locked": False,
            "edited": False,
        },
        "history": [],
    }


def record_edit(
    widget: Dict[str, Any],
    *,
    changes: Dict[str, Any],
    user_id: Optional[str],
    reason: str = "",
) -> None:
    """Mark a widget edited and append an audit entry (mutates in place)."""
    widget["meta"]["edited"] = True
    widget["history"].append(
        {
            "at": now_ts(),
            "by": user_id,
            "reason": reason or "",
            "changes": changes,
            "source": "user_override",
        }
    )


def reset_widget(widget: Dict[str, Any]) -> bool:
    """Restore a generated widget's data to its immutable snapshot. Returns True
    if anything changed. User-created widgets (no snapshot) are left untouched."""
    snap = widget.get("generated")
    if snap is None:
        return False
    widget["data"] = copy.deepcopy(snap)
    widget["title"] = widget.get("title", "")
    widget["meta"]["edited"] = False
    widget["history"].append(
        {"at": now_ts(), "by": None, "reason": "reset to generated", "changes": {}, "source": "reset"}
    )
    return True


# ───────────────────────────── Pages ──────────────────────────────


def make_page(
    title: str,
    widgets: List[Dict[str, Any]] | None = None,
    *,
    icon: str = "bi bi-file-earmark",
    template: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": _uid("p"),
        "title": title,
        "icon": icon,
        "template": template,
        "widgets": widgets or [],
        "locked": False,
        "visible_export": True,
        "notes": "",
    }


# ───────────────────────────── Document ──────────────────────────────


def make_document(
    *, title: str = "Boardroom", subtitle: str = "", pages: List[Dict[str, Any]] | None = None
) -> Dict[str, Any]:
    return {
        "id": _uid("doc"),
        "title": title,
        "subtitle": subtitle,
        "theme": "default",
        "pages": pages or [],
        "version": 1,
    }


# ───────────────────────── Lookup / mutation helpers ─────────────────────


def find_page(doc: Dict[str, Any], page_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in doc.get("pages", []) if p.get("id") == page_id), None)


def find_widget(doc: Dict[str, Any], widget_id: str):
    """Return (page, widget) or (None, None)."""
    for page in doc.get("pages", []):
        for w in page.get("widgets", []):
            if w.get("id") == widget_id:
                return page, w
    return None, None


def move_widget(doc: Dict[str, Any], widget_id: str, delta: int) -> bool:
    page, w = find_widget(doc, widget_id)
    if not page:
        return False
    ws = page["widgets"]
    i = ws.index(w)
    j = max(0, min(len(ws) - 1, i + delta))
    if i == j:
        return False
    ws.insert(j, ws.pop(i))
    return True


def move_widget_before(
    doc: Dict[str, Any], src_wid: str, dst_wid: str, before: bool = True
) -> bool:
    """Drag-and-drop reorder: place ``src`` before/after ``dst``. Works across
    pages (the widget moves to the destination's page). Returns True on change."""
    p1, w1 = find_widget(doc, src_wid)
    p2, w2 = find_widget(doc, dst_wid)
    if not p1 or not p2 or w1 is None or w2 is None or w1 is w2:
        return False
    p1["widgets"].remove(w1)
    j = p2["widgets"].index(w2) + (0 if before else 1)
    p2["widgets"].insert(j, w1)
    return True


def duplicate_widget(doc: Dict[str, Any], widget_id: str) -> Optional[str]:
    page, w = find_widget(doc, widget_id)
    if not page:
        return None
    clone = copy.deepcopy(w)
    clone["id"] = _uid("w")
    clone["origin"] = "user"  # a duplicate is a user artifact, freely editable/deletable
    clone["generated"] = None
    clone["title"] = (w.get("title") or "") + " (copy)"
    page["widgets"].insert(page["widgets"].index(w) + 1, clone)
    return clone["id"]


def delete_widget(doc: Dict[str, Any], widget_id: str) -> bool:
    """Delete a *user-created* widget. Generated widgets can only be hidden, never
    deleted (their evidence must stay in the document)."""
    page, w = find_widget(doc, widget_id)
    if not page or w.get("origin") != "user":
        return False
    page["widgets"].remove(w)
    return True


def move_page(doc: Dict[str, Any], page_id: str, delta: int) -> bool:
    pages = doc.get("pages", [])
    p = find_page(doc, page_id)
    if not p:
        return False
    i = pages.index(p)
    j = max(0, min(len(pages) - 1, i + delta))
    if i == j:
        return False
    pages.insert(j, pages.pop(i))
    return True


def delete_page(doc: Dict[str, Any], page_id: str) -> bool:
    pages = doc.get("pages", [])
    p = find_page(doc, page_id)
    if not p or p.get("locked") or len(pages) <= 1:
        return False
    pages.remove(p)
    return True


def duplicate_page(doc: Dict[str, Any], page_id: str) -> Optional[str]:
    p = find_page(doc, page_id)
    if not p:
        return None
    clone = copy.deepcopy(p)
    clone["id"] = _uid("p")
    clone["title"] = (p.get("title") or "Page") + " (copy)"
    clone["locked"] = False
    # Fresh ids for all widgets so they edit independently of the source page.
    for w in clone.get("widgets", []):
        w["id"] = _uid("w")
    doc["pages"].insert(doc["pages"].index(p) + 1, clone)
    return clone["id"]
