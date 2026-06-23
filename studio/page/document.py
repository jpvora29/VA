"""The shared, editable QBR document — one source of truth for browser AND PPT.

The previous prototype re-derived a ``DeckSpec`` on every render and applied edits
only cosmetically in the view layer, so the export rebuilt independently and
"parity" was vacuous. This module fixes that:

  generate once → ``new_document(deck)`` snapshots the *generated layer*
  user edits / page ops → mutate the *overlay* (edits, order, hidden, config)
  ``materialize(doc)`` → the exact ``DeckSpec`` both the screen and ``export_deck``
                         consume — so a slide you edited exports edited.

The document is a plain JSON-able dict so it lives in a persisted ``dcc.Store``
(survives refresh) and round-trips losslessly through the typed ``DeckSpec``.

Layers
------
- ``slides``  : ``{slide_id: slide_dict}`` — the immutable generated snapshot.
- ``order``   : ``[slide_id, …]`` — display & export order (reorder/add/delete).
- ``hidden``  : ``[slide_id]``   — hidden from export (still visible in authoring).
- ``edits``   : ``{slide_id: {field: value}}`` — text overrides; generated value
                is preserved in ``slides`` so reset is always possible.
- ``config``  : ``{slide_id: {chart: "bar|donut|waterfall"}}`` — widget config.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from studio.deck.model import (
    BulletsBlock,
    CalloutBlock,
    CardsBlock,
    ChartBlock,
    CommentaryBlock,
    DeckSpec,
    HeatmapBlock,
    KpiBlock,
    MatrixBlock,
    RadarBlock,
    SlideSpec,
    SwotBlock,
    TableBlock,
    TimelineBlock,
)

# Text fields a user may override (kept in lock-step with the inspector/analyst UI).
EDITABLE_FIELDS = (
    "title", "subtitle", "eyebrow", "question",
    "implication", "recommendation", "owner", "due_date",
)
# Block kinds the PowerPoint exporter can render natively (drives the real parity
# check — a deck is PPT-faithful only if every block is in this set).
EXPORT_SUPPORTED_BLOCKS = frozenset(
    {"kpis", "chart", "table", "commentary", "cards", "swot", "bullets", "callout",
     "matrix", "heatmap", "radar", "timeline"}
)


# ── block <-> dict (typed Block round-trips through JSON) ─────────────────────

_BLOCK_FROM = {
    "kpis": lambda d: KpiBlock(d.get("items", [])),
    "chart": lambda d: ChartBlock(d.get("chart", "bar"), d.get("labels", []), d.get("values", []), d.get("title", "")),
    "table": lambda d: TableBlock(d.get("columns", []), d.get("rows", []), d.get("hidden", 0), d.get("title", "")),
    "commentary": lambda d: CommentaryBlock(d.get("headline", ""), d.get("points", []), d.get("actions", [])),
    "bullets": lambda d: BulletsBlock(d.get("items", []), d.get("title", "")),
    "callout": lambda d: CalloutBlock(d.get("text", ""), d.get("tone", "neutral")),
    "swot": lambda d: SwotBlock(d.get("strengths", []), d.get("weaknesses", []), d.get("opportunities", []), d.get("threats", [])),
    "cards": lambda d: CardsBlock(d.get("cards", [])),
    "matrix": lambda d: MatrixBlock(d.get("points", []), d.get("title", "")),
    "heatmap": lambda d: HeatmapBlock(d.get("rows", []), d.get("columns", []), d.get("values", []), d.get("title", "")),
    "radar": lambda d: RadarBlock(d.get("labels", []), d.get("values", []), d.get("title", "")),
    "timeline": lambda d: TimelineBlock(d.get("tasks", []), d.get("title", "")),
}


def _block_to_dict(b: Any) -> Dict[str, Any]:
    """Serialize a typed Block to a JSON-able dict (all fields, keyed by ``kind``)."""
    out: Dict[str, Any] = {"kind": b.kind}
    for f in ("items", "chart", "labels", "values", "title", "columns", "rows",
              "hidden", "headline", "points", "actions", "text", "tone",
              "strengths", "weaknesses", "opportunities", "threats", "cards", "tasks"):
        if hasattr(b, f):
            out[f] = _plain(getattr(b, f))
    return out


def _block_from_dict(d: Mapping[str, Any]) -> Any:
    return _BLOCK_FROM[d["kind"]](d)


def _plain(value: Any) -> Any:
    """Coerce tuples/mappings to plain JSON types (numpy-safe via str fallback)."""
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# ── slide <-> dict ────────────────────────────────────────────────────────────

_SLIDE_SCALARS = (
    "layout", "title", "subtitle", "eyebrow", "accent",
    "question", "implication", "recommendation", "owner", "due_date", "confidence",
)


def slide_to_dict(s: SlideSpec) -> Dict[str, Any]:
    return {
        **{f: getattr(s, f) for f in _SLIDE_SCALARS},
        "takeaways": _plain(s.takeaways),
        "blocks": [_block_to_dict(b) for b in s.blocks],
        "evidence": _plain(s.evidence),
        "sources": _plain(s.sources),
        "meta": _plain(s.meta),
    }


def slide_from_dict(d: Mapping[str, Any]) -> SlideSpec:
    return SlideSpec(
        **{f: d.get(f, "") for f in _SLIDE_SCALARS},
        takeaways=tuple(d.get("takeaways", [])),
        blocks=tuple(_block_from_dict(b) for b in d.get("blocks", [])),
        evidence=tuple(d.get("evidence", [])),
        sources=tuple(d.get("sources", [])),
        meta=dict(d.get("meta", {})),
    )


# ── document construction ─────────────────────────────────────────────────────


def new_document(deck: DeckSpec) -> Dict[str, Any]:
    """Snapshot a freshly generated deck into an editable document.

    Each slide gets a stable id (``s1``, ``s2``, …) so reorder/delete/duplicate
    operate on identity, not on shifting positions.
    """
    slides: Dict[str, Any] = {}
    order: List[str] = []
    for i, s in enumerate(deck.slides, start=1):
        sid = f"s{i}"
        slides[sid] = slide_to_dict(s)
        order.append(sid)
    return {
        "meta": _plain(deck.meta),
        "slides": slides,
        "order": order,
        "hidden": [],
        "edits": {},
        "config": {},
        "seq": len(order),  # next-id counter for duplicates/inserts
    }


# ── materialize: the overlay applied to the generated layer → a DeckSpec ──────


def _apply(slide: SlideSpec, edits: Mapping[str, Any], config: Mapping[str, Any]) -> SlideSpec:
    changes: Dict[str, Any] = {
        f: edits[f] for f in EDITABLE_FIELDS if edits.get(f) not in (None, "")
    }
    chart = config.get("chart")
    if chart:
        changes["blocks"] = tuple(
            ChartBlock(chart, b.labels, b.values, b.title) if b.kind == "chart" else b
            for b in slide.blocks
        )
    return replace(slide, **changes) if changes else slide


def materialize_slide(doc: Mapping[str, Any], sid: str) -> SlideSpec:
    """One slide as a ``SlideSpec`` with its text edits + chart config applied."""
    sd = doc.get("slides", {}).get(sid, {})
    return _apply(slide_from_dict(sd), doc.get("edits", {}).get(sid, {}), doc.get("config", {}).get(sid, {}))


def materialize(doc: Optional[Mapping[str, Any]], *, for_export: bool = False) -> Optional[DeckSpec]:
    """Build the concrete ``DeckSpec`` from the document.

    The SAME function feeds the on-screen renderer and ``export_deck`` — so what
    you see is what exports. For export, hidden slides are dropped; in authoring
    they stay visible (greyed) so they can be restored.
    """
    if not doc or not doc.get("order"):
        return None
    hidden = set(doc.get("hidden", []))
    edits = doc.get("edits", {})
    config = doc.get("config", {})
    slides = []
    for sid in doc["order"]:
        if for_export and sid in hidden:
            continue
        sd = doc["slides"].get(sid)
        if not sd:
            continue
        slides.append(_apply(slide_from_dict(sd), edits.get(sid, {}), config.get(sid, {})))
    return DeckSpec(slides=tuple(slides), meta=dict(doc.get("meta", {})))


# ── position helpers (the view uses positions; ids are the source of truth) ───


def sid_at(doc: Mapping[str, Any], pos: int) -> Optional[str]:
    order = doc.get("order", [])
    return order[pos] if 0 <= pos < len(order) else None


def generated_value(doc: Mapping[str, Any], sid: str, field: str) -> str:
    return str((doc.get("slides", {}).get(sid, {}) or {}).get(field, "") or "")


def is_edited(doc: Mapping[str, Any], sid: str, field: str) -> bool:
    return field in (doc.get("edits", {}).get(sid, {}) or {})


def chart_kind(doc: Mapping[str, Any], sid: str) -> Optional[str]:
    """Current chart type for a slide (config override, else the generated one)."""
    cfg = doc.get("config", {}).get(sid, {})
    if cfg.get("chart"):
        return cfg["chart"]
    sd = doc.get("slides", {}).get(sid, {})
    for b in sd.get("blocks", []):
        if b.get("kind") == "chart":
            return b.get("chart", "bar")
    return None


# ── mutations (return a NEW doc; callers store the result) ────────────────────


def _clone(doc: Mapping[str, Any]) -> Dict[str, Any]:
    import copy

    return copy.deepcopy(dict(doc))


def set_edit(doc, sid: str, field: str, value: Optional[str]) -> Dict[str, Any]:
    """Apply or clear a text override; clearing (==generated or empty) drops it so
    the field reverts to its generated, evidence-backed value."""
    doc = _clone(doc)
    edits = doc.setdefault("edits", {})
    cur = edits.setdefault(sid, {})
    generated = generated_value(doc, sid, field)
    if value is None or value.strip() in ("", generated.strip()):
        cur.pop(field, None)
    else:
        cur[field] = value
    if not cur:
        edits.pop(sid, None)
    return doc


def reset_edit(doc, sid: str, field: str) -> Dict[str, Any]:
    doc = _clone(doc)
    cur = doc.get("edits", {}).get(sid)
    if cur:
        cur.pop(field, None)
        if not cur:
            doc["edits"].pop(sid, None)
    return doc


def set_config(doc, sid: str, key: str, value: Any) -> Dict[str, Any]:
    doc = _clone(doc)
    doc.setdefault("config", {}).setdefault(sid, {})[key] = value
    return doc


def move(doc, pos: int, direction: int) -> Tuple[Dict[str, Any], int]:
    """Reorder the slide at ``pos`` by ``direction`` (-1 up / +1 down)."""
    doc = _clone(doc)
    order = doc["order"]
    j = pos + direction
    if 0 <= pos < len(order) and 0 <= j < len(order):
        order[pos], order[j] = order[j], order[pos]
        return doc, j
    return doc, pos


def toggle_hidden(doc, pos: int) -> Dict[str, Any]:
    doc = _clone(doc)
    sid = sid_at(doc, pos)
    if sid is None:
        return doc
    hidden = doc.setdefault("hidden", [])
    if sid in hidden:
        hidden.remove(sid)
    else:
        hidden.append(sid)
    return doc


def delete(doc, pos: int) -> Tuple[Dict[str, Any], int]:
    """Remove a slide from the deck (generated snapshot kept; just unlinked)."""
    doc = _clone(doc)
    sid = sid_at(doc, pos)
    if sid is None:
        return doc, pos
    doc["order"].pop(pos)
    if sid in doc.get("hidden", []):
        doc["hidden"].remove(sid)
    doc.get("edits", {}).pop(sid, None)
    doc.get("config", {}).pop(sid, None)
    doc.get("page_style", {}).pop(sid, None)
    return doc, max(0, min(pos, len(doc["order"]) - 1))


def duplicate(doc, pos: int) -> Tuple[Dict[str, Any], int]:
    """Duplicate the slide at ``pos`` (new id, generated snapshot + its edits)."""
    doc = _clone(doc)
    sid = sid_at(doc, pos)
    if sid is None:
        return doc, pos
    doc["seq"] = int(doc.get("seq", len(doc["order"]))) + 1
    nid = f"s{doc['seq']}"
    import copy

    doc["slides"][nid] = copy.deepcopy(doc["slides"][sid])
    if sid in doc.get("edits", {}):
        doc["edits"][nid] = copy.deepcopy(doc["edits"][sid])
    if sid in doc.get("config", {}):
        doc["config"][nid] = copy.deepcopy(doc["config"][sid])
    if sid in doc.get("layouts", {}):
        doc.setdefault("layouts", {})[nid] = copy.deepcopy(doc["layouts"][sid])
    if sid in doc.get("page_style", {}):
        doc.setdefault("page_style", {})[nid] = copy.deepcopy(doc["page_style"][sid])
    doc["order"].insert(pos + 1, nid)
    return doc, pos + 1


# ── canvas widget/grid model ──────────────────────────────────────────────────
#
# A page is a set of widget instances positioned on a 12-col × ``GRID_ROWS``-row
# grid. Generated slides are *decomposed* into widgets on first view so the
# Boardroom Canvas can select / move / resize / add / delete each one directly.
# A page's widget layout is canonical once present in ``doc["layouts"][sid]``:
# the canvas edits it and the PPT export honours its geometry.

GRID_COLS = 12
GRID_ROWS = 8

# Default sizes (w, h in grid cells) when a widget is added from the palette.
WIDGET_DEFAULTS = {
    "headline": {"w": 12, "h": 1, "label": "Headline"},
    "kpiband": {"w": 12, "h": 2, "label": "KPI band"},
    "kpi": {"w": 3, "h": 2, "label": "KPI card"},
    "chart": {"w": 6, "h": 4, "label": "Chart"},
    "table": {"w": 6, "h": 4, "label": "Table"},
    "text": {"w": 4, "h": 3, "label": "Text"},
    "reco": {"w": 12, "h": 1, "label": "Recommendation"},
    "matrix": {"w": 6, "h": 4, "label": "Opportunity matrix"},
    "heatmap": {"w": 6, "h": 4, "label": "Portfolio heatmap"},
    "radar": {"w": 5, "h": 4, "label": "Risk radar"},
    "radial": {"w": 5, "h": 4, "label": "Radial performance"},
    "bridge": {"w": 6, "h": 4, "label": "Variance bridge"},
    "timeline": {"w": 7, "h": 4, "label": "Action timeline"},
    "callout": {"w": 5, "h": 2, "label": "Executive callout"},
    "actions": {"w": 6, "h": 3, "label": "Action tracker"},
    "divider": {"w": 12, "h": 1, "label": "Divider"},
    "image": {"w": 3, "h": 3, "label": "Image"},
}

FONT_FAMILIES = ("Inter", "Aptos", "Arial", "Calibri", "Georgia", "Times New Roman")
WIDGET_STYLE_KEYS = frozenset(
    {"font_family", "font_size", "font_color", "background_color"}
)
PAGE_STYLE_KEYS = frozenset({"background_color"})
TEXT_ROLES = {
    "headline": (("eyebrow", "Eyebrow"), ("title", "Title"), ("subtitle", "Subtitle")),
    "text": (("heading", "Heading"), ("label", "Point label"), ("body", "Body text")),
    "kpiband": (("label", "KPI label"), ("value", "KPI value"), ("delta", "KPI delta")),
    "kpi": (("label", "KPI label"), ("value", "KPI value"), ("delta", "KPI delta")),
    "reco": (("label", "Label"), ("body", "Recommendation"), ("meta", "Metadata")),
    "divider": (("label", "Divider text"),),
    "chart": (("title", "Chart title"),),
    "table": (("header", "Table header"), ("body", "Table body")),
    "matrix": (("title", "Title"),),
    "heatmap": (("title", "Title"),),
    "radar": (("title", "Title"),),
    "radial": (("title", "Title"),),
    "bridge": (("title", "Title"),),
    "timeline": (("title", "Title"),),
    "callout": (("label", "Label"), ("title", "Headline"), ("body", "Body")),
    "actions": (("header", "Header"), ("body", "Action text"), ("meta", "Owner / due")),
}


def _w(wid, kind, x, y, w, h, **props):
    return {"id": wid, "kind": kind, "x": x, "y": y, "w": w, "h": h, "props": props}


def decompose(slide: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Break a generated slide dict into positioned widget instances.

    The same content the polished renderer shows, but as individually editable
    blocks on the grid — this is what makes the canvas a real composition surface
    rather than a static preview."""
    layout = slide.get("layout", "insight")
    blocks = slide.get("blocks", [])
    by_kind = {b.get("kind"): b for b in blocks}
    ws: List[Dict[str, Any]] = []
    n = 0

    def nid():
        nonlocal n
        n += 1
        return f"w{n}"

    if layout in ("cover", "divider"):
        ws.append(_w(nid(), "headline", 0, 2, 12, 3,
                     text=slide.get("title", ""), eyebrow=slide.get("eyebrow", ""),
                     subtitle=slide.get("subtitle", ""), hero=True))
        return ws

    # action title across the top
    ws.append(_w(nid(), "headline", 0, 0, 12, 1,
                 text=slide.get("title", ""), eyebrow=slide.get("eyebrow", ""),
                 question=slide.get("question", "")))

    if layout == "exec":
        if "kpis" in by_kind:
            ws.append(_w(nid(), "kpiband", 0, 1, 12, 2, items=by_kind["kpis"].get("items", [])))
        ws.append(_w(nid(), "text", 0, 3, 6, 4, points=slide.get("takeaways", []), heading="What it means"))
        if "cards" in by_kind:
            ws.append(_w(
                nid(), "actions", 6, 3, 6, 4, title="Priority actions",
                items=[
                    {
                        "action": c.get("title", ""),
                        "owner": c.get("owner", "") or "QBR owner",
                        "due": c.get("due", "") or "Next quarter",
                        "status": {
                            "good": "on_track",
                            "warn": "at_risk",
                            "danger": "at_risk",
                        }.get(c.get("tone"), "planned"),
                    }
                    for c in by_kind["cards"].get("cards", [])
                ],
            ))
        return ws

    if layout == "swot" and "swot" in by_kind:
        ws.append(_w(nid(), "text", 0, 1, 12, 7, swot=by_kind["swot"], heading="SWOT"))
        return ws

    if layout == "initiatives" and "cards" in by_kind:
        ws.append(_w(
            nid(), "actions", 0, 1, 12, 7, title="Initiatives and owners",
            items=[
                {
                    "action": c.get("title", ""),
                    "owner": c.get("owner", "") or c.get("tag", ""),
                    "due": c.get("due", "") or "Next quarter",
                    "status": {
                        "good": "on_track",
                        "warn": "at_risk",
                        "danger": "at_risk",
                    }.get(c.get("tone"), "planned"),
                }
                for c in by_kind["cards"].get("cards", [])
            ],
        ))
        return ws

    # insight / decision / methodology / agenda: the DENSE composition — a stat band
    # (KPIs or evidence numbers) ▸ (rail | primary visual) ▸ full-width secondary
    # visual ▸ reco — so the editable canvas is as full as the polished render and
    # carries every block kind (incl. matrix/heatmap/radar/timeline), not just one.
    visuals = [b for b in blocks if b.get("kind") != "kpis"]
    stat_items = (by_kind["kpis"].get("items", []) if "kpis" in by_kind
                  else _stats_from_evidence(slide.get("evidence", [])))
    primary = visuals[0] if visuals else None
    secondary = visuals[1] if len(visuals) > 1 else None

    content_y = 1
    if stat_items:
        ws.append(_w(nid(), "kpiband", 0, 1, 12, 1, items=list(stat_items)[:4]))
        content_y = 2
    rail_h = (5 if secondary is not None else 7) - content_y + 1
    ws.append(_w(nid(), "text", 0, content_y, 5, rail_h, points=slide.get("takeaways", []), heading="Key takeaways"))
    if primary is not None:
        pw = _visual_widget(nid(), primary, 5, content_y, 7, rail_h)
        if pw:
            ws.append(pw)
    if secondary is not None:
        sy = content_y + rail_h
        sw = _visual_widget(nid(), secondary, 0, sy, 12, 7 - sy)
        if sw:
            ws.append(sw)
    if slide.get("recommendation"):
        ws.append(_w(nid(), "reco", 0, 7, 12, 1, text=slide.get("recommendation", ""),
                     owner=slide.get("owner", ""), due=slide.get("due_date", ""),
                     confidence=slide.get("confidence", "")))
    return ws


def _stats_from_evidence(evidence: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """A compact KPI band from a slide's evidence rows (mirrors deck/compose)."""
    out: List[Dict[str, Any]] = []
    for e in list(evidence)[:4]:
        label = str(e.get("label", "") or "").strip().rstrip(".")
        value = str(e.get("value", "") or "").strip()
        if label and value:
            out.append({"label": label, "value": value, "delta": str(e.get("detail", "") or "")})
    return out


def _visual_widget(wid: str, block: Mapping[str, Any], x: int, y: int, w: int, h: int) -> Optional[Dict[str, Any]]:
    """Map a deck visual block dict to a positioned canvas widget instance."""
    kind = block.get("kind")
    if kind == "chart":
        chart = block.get("chart", "bar")
        if chart == "waterfall":
            return _w(wid, "bridge", x, y, w, h, labels=block.get("labels", []), values=block.get("values", []), title=block.get("title", ""))
        return _w(wid, "chart", x, y, w, h, chart=chart, labels=block.get("labels", []), values=block.get("values", []), title=block.get("title", ""))
    if kind == "table":
        return _w(wid, "table", x, y, w, h, columns=block.get("columns", []), rows=block.get("rows", []), title=block.get("title", ""))
    if kind == "matrix":
        return _w(wid, "matrix", x, y, w, h, points=block.get("points", []), title=block.get("title", ""))
    if kind == "heatmap":
        return _w(wid, "heatmap", x, y, w, h, rows=block.get("rows", []), columns=block.get("columns", []), values=block.get("values", []), title=block.get("title", ""))
    if kind == "radar":
        return _w(wid, "radar", x, y, w, h, labels=block.get("labels", []), values=block.get("values", []), title=block.get("title", ""))
    if kind == "timeline":
        return _w(wid, "timeline", x, y, w, h, tasks=block.get("tasks", []), title=block.get("title", ""))
    return None


def page_widgets(doc: Mapping[str, Any], sid: str) -> List[Dict[str, Any]]:
    """The page's widgets — the stored canvas layout, else decomposed on the fly."""
    stored = (doc.get("layouts", {}) or {}).get(sid)
    if stored is not None:
        return stored
    sd = doc.get("slides", {}).get(sid, {})
    return decompose(sd) if sd else []


def has_custom_layout(doc: Mapping[str, Any], sid: str) -> bool:
    return sid in (doc.get("layouts", {}) or {})


def _ensure_layout(doc: Dict[str, Any], sid: str) -> List[Dict[str, Any]]:
    """Materialize the page's widget layout into the doc so it can be mutated."""
    layouts = doc.setdefault("layouts", {})
    if sid not in layouts:
        layouts[sid] = decompose(doc.get("slides", {}).get(sid, {}))
    return layouts[sid]


def _next_wid(widgets: List[Dict[str, Any]]) -> str:
    nums = [int(w["id"][1:]) for w in widgets if w.get("id", "").startswith("w") and w["id"][1:].isdigit()]
    return f"w{(max(nums) + 1) if nums else 1}"


def _clamp_geo(x, y, w, h):
    w = max(1, min(GRID_COLS, int(w)))
    h = max(1, min(GRID_ROWS, int(h)))
    x = max(0, min(GRID_COLS - w, int(x)))
    y = max(0, min(GRID_ROWS - h, int(y)))
    return x, y, w, h


def set_widget_geo(doc, sid: str, wid: str, x, y, w, h) -> Dict[str, Any]:
    doc = _clone(doc)
    widgets = _ensure_layout(doc, sid)
    x, y, w, h = _clamp_geo(x, y, w, h)
    for wg in widgets:
        if wg["id"] == wid:
            wg.update(x=x, y=y, w=w, h=h)
            break
    return doc


def add_widget(doc, sid: str, kind: str) -> Tuple[Dict[str, Any], str]:
    doc = _clone(doc)
    widgets = _ensure_layout(doc, sid)
    spec = WIDGET_DEFAULTS.get(kind, WIDGET_DEFAULTS["text"])
    wid = _next_wid(widgets)
    # place just below the lowest occupied row, clamped to the grid
    y = min(max((wg["y"] + wg["h"] for wg in widgets), default=0), GRID_ROWS - spec["h"])
    x, y, w, h = _clamp_geo(0, y, spec["w"], spec["h"])
    props = _starter_props(kind, widgets)
    widgets.append({"id": wid, "kind": kind, "x": x, "y": y, "w": w, "h": h, "props": props})
    return doc, wid


def _starter_props(kind: str, widgets: List[Dict[str, Any]]) -> Dict[str, Any]:
    if kind == "headline":
        return {"text": "New action title"}
    if kind == "text":
        return {"heading": "Text", "points": [{"text": "Add your point here."}]}
    if kind == "reco":
        return {"text": "State the decision required.", "owner": "", "due": "", "confidence": "medium"}
    if kind == "kpi":
        return {"items": [{"label": "Metric", "value": "—", "delta": "", "tone": "neutral"}]}
    if kind == "kpiband":
        return {"items": [{"label": "Metric", "value": "—"} for _ in range(4)]}
    if kind == "chart":
        # reuse a sibling chart's data if present, else a small placeholder
        for w in widgets:
            if w["kind"] == "chart" and w["props"].get("values"):
                return {"chart": "bar", "labels": list(w["props"]["labels"]), "values": list(w["props"]["values"]), "title": ""}
        return {"chart": "bar", "labels": ["A", "B", "C"], "values": [3, 5, 2], "title": "", "placeholder": True}
    if kind == "table":
        return {"columns": [{"key": "k", "label": "Item"}, {"key": "v", "label": "Value", "align": "right"}],
                "rows": [{"k": "Row 1", "v": "—"}], "placeholder": True}
    if kind in ("matrix", "heatmap", "radar", "bridge"):
        return {"label": WIDGET_DEFAULTS[kind]["label"]}
    if kind == "divider":
        return {"text": ""}
    return {}


def _starter_props(kind: str, widgets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """QBR-grade starter content for every canvas widget."""
    if kind == "headline":
        return {"text": "New action title"}
    if kind == "text":
        return {"heading": "What it means", "points": [
            {"label": "Performance.", "text": "Growth remains ahead of plan.", "tone": "good"},
            {"label": "Watch item.", "text": "Property retention needs intervention.", "tone": "warn"}]}
    if kind == "reco":
        return {"text": "Approve the next-quarter growth plan.", "owner": "QBR owner", "due": "30 Jun", "confidence": "high"}
    if kind == "kpi":
        return {"items": [{"label": "Renewal retention", "value": "92%", "delta": "+3.1 pts", "tone": "good",
                           "trend_labels": ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2"],
                           "trend_values": [86, 88, 89, 90, 91, 92]}]}
    if kind == "kpiband":
        return {"items": [
            {"label": "Gross written premium", "value": "S$180m", "delta": "+8.6%", "tone": "good",
             "trend_labels": ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2"], "trend_values": [132, 141, 149, 158, 169, 180]},
            {"label": "Renewal retention", "value": "92%", "delta": "+3.1 pts", "tone": "good",
             "trend_labels": ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2"], "trend_values": [86, 88, 89, 90, 91, 92]},
            {"label": "Combined ratio", "value": "96.4%", "delta": "-1.8 pts", "tone": "good",
             "trend_labels": ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2"], "trend_values": [101, 100, 99, 98, 97, 96.4]},
            {"label": "Whitespace", "value": "S$85m", "delta": "3 plays", "tone": "warn",
             "trend_labels": ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2"], "trend_values": [48, 55, 61, 70, 77, 85]}]}
    if kind == "chart":
        return {"chart": "line", "labels": ["Q1 25", "Q2 25", "Q3 25", "Q4 25", "Q1 26", "Q2 26"],
                "values": [132, 141, 149, 158, 169, 180], "title": "Premium trajectory"}
    if kind == "table":
        return {"columns": [
                    {"key": "opportunity", "label": "Opportunity"},
                    {"key": "premium", "label": "Incremental GWP", "align": "right", "bar": True},
                    {"key": "ease", "label": "Ease to win"},
                    {"key": "risk", "label": "Renewal risk", "status": True}],
                "rows": [
                    {"opportunity": "Marine cross-sell", "premium": 85, "ease": "High", "risk": "Low"},
                    {"opportunity": "Property whitespace", "premium": 75, "ease": "Medium", "risk": "Medium"},
                    {"opportunity": "Casualty repricing", "premium": 20, "ease": "High", "risk": "Low"}]}
    if kind == "matrix":
        return {"title": "Opportunity matrix", "points": [
            {"label": "Marine cross-sell", "x": 78, "y": 80, "size": 58, "value": 85},
            {"label": "Property whitespace", "x": 35, "y": 68, "size": 50, "value": 75},
            {"label": "Casualty repricing", "x": 72, "y": 28, "size": 38, "value": 20},
            {"label": "Cyber expansion", "x": 55, "y": 58, "size": 34, "value": 35}]}
    if kind == "heatmap":
        return {"title": "Portfolio quality by segment", "rows": ["Property", "Casualty", "Marine", "Cyber"],
                "columns": ["Growth", "Retention", "Loss ratio", "Whitespace"],
                "values": [[72, 91, 66, 78], [55, 88, 74, 52], [84, 94, 81, 90], [69, 86, 58, 82]]}
    if kind == "radar":
        return {"title": "Risk landscape", "labels": ["Pricing", "Claims", "Capacity", "Cyber", "Regulation", "Concentration"],
                "values": [72, 58, 45, 82, 61, 69]}
    if kind == "radial":
        return {"title": "Strategic pillar progress", "labels": ["Growth", "Retention", "Profitability", "Data", "Distribution"],
                "values": [86, 92, 74, 63, 79]}
    if kind == "bridge":
        return {"title": "Premium movement bridge", "labels": ["Renewals", "Rate", "New business", "Attrition", "FX"],
                "values": [18, 11, 15, -8, -3], "start": 147, "total_label": "Q2 premium"}
    if kind == "timeline":
        return {"title": "Next-quarter action tracker", "tasks": [
            {"task": "Marine broker campaign", "start": 0, "duration": 2.2, "owner": "Marcus", "status": "on_track"},
            {"task": "Property playbook", "start": 0.8, "duration": 2.4, "owner": "Elise", "status": "at_risk"},
            {"task": "Casualty pricing", "start": 1.5, "duration": 1.7, "owner": "Ravi", "status": "on_track"},
            {"task": "Data enrichment", "start": 2.3, "duration": 1.5, "owner": "Li Na", "status": "planned"}]}
    if kind == "callout":
        return {"label": "EXECUTIVE TAKEAWAY", "title": "Three growth plays can unlock S$180m",
                "body": "Marine cross-sell offers the strongest near-term upside while protecting renewal quality.",
                "tone": "blue"}
    if kind == "actions":
        return {"title": "Priority decisions", "items": [
            {"action": "Approve marine cross-sell campaign", "owner": "Marcus Tan", "due": "30 Jun", "status": "on_track"},
            {"action": "Resolve property appetite gaps", "owner": "Elise Wong", "due": "15 Jun", "status": "at_risk"},
            {"action": "Sign off casualty pricing actions", "owner": "Ravi Menon", "due": "30 Jun", "status": "on_track"}]}
    if kind == "divider":
        return {"text": ""}
    return {}


def delete_widget(doc, sid: str, wid: str) -> Dict[str, Any]:
    doc = _clone(doc)
    widgets = _ensure_layout(doc, sid)
    doc["layouts"][sid] = [w for w in widgets if w["id"] != wid]
    return doc


def duplicate_widget(doc, sid: str, wid: str) -> Tuple[Dict[str, Any], str]:
    doc = _clone(doc)
    widgets = _ensure_layout(doc, sid)
    src = next((w for w in widgets if w["id"] == wid), None)
    if not src:
        return doc, wid
    import copy

    new = copy.deepcopy(src)
    new["id"] = _next_wid(widgets)
    new["x"], new["y"], _, _ = _clamp_geo(src["x"] + 1, src["y"] + 1, src["w"], src["h"])
    widgets.append(new)
    return doc, new["id"]


def commentary_to_text(points: Any) -> str:
    """Serialize commentary points for the inspector's one-line-per-point editor."""
    lines: List[str] = []
    for point in points or []:
        if isinstance(point, str):
            text, label, tone = point, "", ""
        else:
            text = str(point.get("text", "") or "").strip()
            label = str(point.get("label", "") or "").strip().rstrip(".")
            tone = str(point.get("tone", "") or "").strip().lower()
        if not text:
            continue
        prefix = f"[{tone}] " if tone in {"good", "warn", "danger", "neutral"} else ""
        lines.append(prefix + (f"{label}: {text}" if label else text))
    return "\n".join(lines)


def commentary_from_text(value: Any) -> List[Dict[str, str]]:
    """Parse ``[tone] Label: text`` lines while keeping plain lines effortless."""
    points: List[Dict[str, str]] = []
    for raw in str(value or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        tone = "neutral"
        if line.startswith("[") and "]" in line:
            candidate, _, rest = line[1:].partition("]")
            if candidate.strip().lower() in {"good", "warn", "danger", "neutral"}:
                tone = candidate.strip().lower()
                line = rest.strip()
        label = ""
        text = line
        if ":" in line:
            candidate, rest = line.split(":", 1)
            if candidate.strip() and rest.strip():
                label, text = candidate.strip().rstrip(".") + ".", rest.strip()
        if text:
            points.append({"label": label, "text": text, "tone": tone})
    return points


def _normalise_hex(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text.upper()
        except ValueError:
            pass
    return fallback


def is_hex_color(value: Any) -> bool:
    text = str(value or "").strip()
    if len(text) != 7 or not text.startswith("#"):
        return False
    try:
        int(text[1:], 16)
    except ValueError:
        return False
    return True


def effective_widget_style(
    doc: Mapping[str, Any], sid: str, wid: str
) -> Dict[str, Any]:
    widget = get_widget(doc, sid, wid) or {}
    props = widget.get("props", {}) or {}
    slide = (doc.get("slides", {}).get(sid, {}) or {})
    dark = slide.get("layout") in ("cover", "divider")
    hero = bool(props.get("hero"))
    kind = widget.get("kind")
    defaults = {
        "font_family": "Inter",
        "font_size": 34 if hero else (15 if kind == "headline" else 11),
        "font_color": "#FFFFFF" if dark else "#1C2636",
        "background_color": "#000F47" if dark else ("#EEF3FF" if kind == "reco" else "#FFFFFF"),
    }
    return {
        "font_family": props.get("font_family") or defaults["font_family"],
        "font_size": int(props.get("font_size") or defaults["font_size"]),
        "font_color": _normalise_hex(props.get("font_color"), defaults["font_color"]),
        "background_color": _normalise_hex(
            props.get("background_color"), defaults["background_color"]
        ),
    }


def widget_text_roles(kind: str) -> Tuple[Tuple[str, str], ...]:
    return tuple(TEXT_ROLES.get(kind, ()))


def effective_text_style(
    doc: Mapping[str, Any], sid: str, wid: str, role: str
) -> Dict[str, Any]:
    widget = get_widget(doc, sid, wid) or {}
    props = widget.get("props", {}) or {}
    kind = str(widget.get("kind") or "")
    if role not in {key for key, _label in widget_text_roles(kind)}:
        return effective_widget_style(doc, sid, wid)
    base = effective_widget_style(doc, sid, wid)
    hero = bool(props.get("hero"))
    defaults = {
        "headline": {
            "eyebrow": (10, "#5CC8FF" if hero else "#0B4BFF"),
            "title": (34 if hero else 15, base["font_color"]),
            "subtitle": (14 if hero else 11, "#AAB4CC" if hero else "#5B6577"),
        },
        "text": {
            "heading": (9, "#8A94A6"),
            "label": (11, base["font_color"]),
            "body": (11, base["font_color"]),
        },
        "kpiband": {
            "label": (8, "#8A94A6"),
            "value": (18, "#000F47"),
            "delta": (10, "#5B6577"),
        },
        "kpi": {
            "label": (8, "#8A94A6"),
            "value": (18, "#000F47"),
            "delta": (10, "#5B6577"),
        },
        "reco": {
            "label": (9, "#0B4BFF"),
            "body": (11, "#000F47"),
            "meta": (9, "#5B6577"),
        },
        "divider": {"label": (10, base["font_color"])},
        "chart": {"title": (10, base["font_color"])},
        "table": {
            "header": (9, "#5B6577"),
            "body": (9, base["font_color"]),
        },
        "matrix": {"title": (10, "#000F47")},
        "heatmap": {"title": (10, "#000F47")},
        "radar": {"title": (10, "#000F47")},
        "radial": {"title": (10, "#000F47")},
        "bridge": {"title": (10, "#000F47")},
        "timeline": {"title": (10, "#000F47")},
        "callout": {
            "label": (9, "#0B4BFF"),
            "title": (16, "#000F47"),
            "body": (10, base["font_color"]),
        },
        "actions": {
            "header": (9, "#5B6577"),
            "body": (10, base["font_color"]),
            "meta": (9, "#5B6577"),
        },
    }
    default_size, default_color = defaults.get(kind, {}).get(
        role, (base["font_size"], base["font_color"])
    )
    stored = ((props.get("text_styles") or {}).get(role) or {})
    return {
        "font_family": stored.get("font_family") or base["font_family"],
        "font_size": max(6, min(72, int(stored.get("font_size") or default_size))),
        "font_color": _normalise_hex(stored.get("font_color"), default_color),
    }


def set_widget_text_style(
    doc, sid: str, wid: str, role: str, key: str, value: Any
) -> Dict[str, Any]:
    doc = _clone(doc)
    widgets = _ensure_layout(doc, sid)
    for widget in widgets:
        if widget["id"] != wid:
            continue
        valid_roles = {name for name, _label in widget_text_roles(widget["kind"])}
        if role not in valid_roles or key not in {"font_family", "font_size", "font_color"}:
            return doc
        style = widget.setdefault("props", {}).setdefault("text_styles", {}).setdefault(role, {})
        if key == "font_family":
            style[key] = value if value in FONT_FAMILIES else "Inter"
        elif key == "font_size":
            style[key] = max(6, min(72, int(value or 11)))
        else:
            style[key] = _normalise_hex(value, "#1C2636")
        break
    return doc


def set_widget_prop(doc, sid: str, wid: str, key: str, value: Any) -> Dict[str, Any]:
    doc = _clone(doc)
    widgets = _ensure_layout(doc, sid)
    for w in widgets:
        if w["id"] == wid:
            props = w.setdefault("props", {})
            if key == "points_text":
                props["points"] = commentary_from_text(value)
            elif key == "data_json":
                try:
                    parsed = json.loads(str(value or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    preserved = {
                        name: props.get(name)
                        for name in ("background_color", "text_styles")
                        if name in props
                    }
                    props.clear()
                    props.update(parsed)
                    props.update(preserved)
            elif key == "font_size":
                props[key] = max(6, min(72, int(value or 11)))
            elif key in {"font_color", "background_color"}:
                fallback = "#1C2636" if key == "font_color" else "#FFFFFF"
                props[key] = _normalise_hex(value, fallback)
            elif key == "font_family":
                props[key] = value if value in FONT_FAMILIES else "Inter"
            else:
                props[key] = value
            break
    return doc


def get_widget(doc: Mapping[str, Any], sid: str, wid: str) -> Optional[Dict[str, Any]]:
    return next((w for w in page_widgets(doc, sid) if w["id"] == wid), None)


def effective_page_style(doc: Mapping[str, Any], sid: str) -> Dict[str, str]:
    slide = (doc.get("slides", {}).get(sid, {}) or {})
    fallback = "#000F47" if slide.get("layout") in ("cover", "divider") else "#FFFFFF"
    stored = (doc.get("page_style", {}).get(sid, {}) or {})
    return {"background_color": _normalise_hex(stored.get("background_color"), fallback)}


def set_page_style(doc, sid: str, key: str, value: Any) -> Dict[str, Any]:
    doc = _clone(doc)
    if key not in PAGE_STYLE_KEYS or sid not in doc.get("slides", {}):
        return doc
    current = doc.setdefault("page_style", {}).setdefault(sid, {})
    current[key] = _normalise_hex(value, effective_page_style(doc, sid)[key])
    return doc


def add_blank_slide(doc, pos: int) -> Tuple[Dict[str, Any], int]:
    """Insert a new, empty governed page after ``pos`` (headline + a text block)."""
    doc = _clone(doc)
    doc["seq"] = int(doc.get("seq", len(doc.get("order", [])))) + 1
    sid = f"s{doc['seq']}"
    doc.setdefault("slides", {})[sid] = {
        "layout": "insight", "title": "New page", "subtitle": "", "eyebrow": "NEW PAGE",
        "accent": "blue", "question": "", "implication": "", "recommendation": "",
        "owner": "", "due_date": "", "confidence": "", "takeaways": [], "blocks": [],
        "evidence": [], "sources": [], "meta": {},
    }
    doc.setdefault("layouts", {})[sid] = [
        {"id": "w1", "kind": "headline", "x": 0, "y": 0, "w": 12, "h": 1, "props": {"text": "New action title"}},
        {"id": "w2", "kind": "text", "x": 0, "y": 1, "w": 6, "h": 5,
         "props": {"heading": "Key points", "points": [{"text": "Add your first point."}]}},
    ]
    order = doc.setdefault("order", [])
    insert_at = min(pos + 1, len(order))
    order.insert(insert_at, sid)
    return doc, insert_at


def add_divider_slide(doc, pos: int) -> Tuple[Dict[str, Any], int]:
    """Insert an editable section-divider page after ``pos``.

    Divider pages are first-class slides, not decorative rail labels: they remain
    in document order, render on the canvas, and export through the same layout
    path as every other page.
    """
    doc = _clone(doc)
    doc["seq"] = int(doc.get("seq", len(doc.get("order", [])))) + 1
    sid = f"s{doc['seq']}"
    section_no = 1 + sum(
        1
        for existing_sid in doc.get("order", [])
        if (doc.get("slides", {}).get(existing_sid, {}) or {}).get("layout") == "divider"
    )
    doc.setdefault("slides", {})[sid] = {
        "layout": "divider",
        "title": "New section",
        "subtitle": "",
        "eyebrow": f"SECTION {section_no:02d}",
        "accent": "blue",
        "question": "",
        "implication": "",
        "recommendation": "",
        "owner": "",
        "due_date": "",
        "confidence": "",
        "takeaways": [],
        "blocks": [],
        "evidence": [],
        "sources": [],
        "meta": {},
    }
    doc.setdefault("layouts", {})[sid] = [
        {
            "id": "w1",
            "kind": "headline",
            "x": 0,
            "y": 2,
            "w": 12,
            "h": 3,
            "props": {
                "text": "New section",
                "eyebrow": f"SECTION {section_no:02d}",
                "subtitle": "",
                "hero": True,
            },
        }
    ]
    order = doc.setdefault("order", [])
    insert_at = min(pos + 1, len(order))
    order.insert(insert_at, sid)
    return doc, insert_at
