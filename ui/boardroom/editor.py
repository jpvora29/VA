"""Editor & library-picker modals for the editable Boardroom.

``build_editor_body(widget)`` produces a kind-aware form. Every input carries a
pattern id ``{"type": "bm-ef", "key": <dot.path>}``; the callbacks collect them all
on Save and hand the flat ``{key: value}`` dict to ``apply_editor``.

List-based widgets (KPIs, insights, timeline, opportunity radar, heatmap cells,
positioning carriers, comparison rows, battlecards…) are edited through *structured*
repeatable item cards — one dedicated control per field, with icon/tone pickers,
number inputs, and live **Add / Remove** row buttons — instead of free-form
``::``/comma text. The list contents are reconstructed purely from the submitted
field keys (``<path>.<i>.<field>``), so removing a row simply means its keys are
gone on the next collect. The modals are mounted once in the app shell and driven by
``ui.boardroom.callbacks``.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import dash_bootstrap_components as dbc
from dash import dcc, html

from ui.boardroom import catalog, icons, model, themes

SIZE_OPTS = [
    {"label": "Small", "value": "sm"},
    {"label": "Medium", "value": "md"},
    {"label": "Large", "value": "lg"},
    {"label": "Full width", "value": "full"},
]
CHART_TYPES = [
    {"label": "(keep)", "value": ""},
    {"label": "Bar", "value": "bar"},
    {"label": "Line", "value": "line"},
    {"label": "Area", "value": "area"},
    {"label": "Pie", "value": "pie"},
    {"label": "Scatter", "value": "scatter"},
]
SORT_OPTS = [
    {"label": "Default", "value": ""},
    {"label": "Ascending", "value": "asc"},
    {"label": "Descending", "value": "desc"},
]
CATEGORY_OPTS = [
    {"label": "Premium", "value": "premium"},
    {"label": "Rank", "value": "rank"},
    {"label": "Score", "value": "score"},
    {"label": "Product", "value": "product"},
    {"label": "Other", "value": "other"},
]
DIMENSION_OPTS = [
    {"label": "Product", "value": "product"},
    {"label": "Segment", "value": "segment"},
    {"label": "Industry", "value": "industry"},
    {"label": "Country", "value": "country"},
    {"label": "Other", "value": "other"},
]
SEVERITY_OPTS = [
    {"label": "High", "value": "High"},
    {"label": "Medium", "value": "Med"},
    {"label": "Low", "value": "Low"},
]


# ── repeatable-list specs: drive BOTH the structured form and the apply parser ──
#   path     — where the list lives inside the widget's ``data`` (dot-path, nestable)
#   singular — label for the item + the "Add …" button
#   key_field— if this field is blank the item is treated as empty and dropped
#   template — the blank item used when a new row is added
LIST_SPECS: Dict[str, Dict[str, Any]] = {
    "kpis": {
        "path": "kpis", "singular": "KPI", "key_field": "label",
        "template": {"label": "", "value": "", "delta": "", "tone": "neutral", "icon": "bi bi-graph-up"},
        "fields": [
            {"key": "label", "label": "Label", "type": "text"},
            {"key": "value", "label": "Value", "type": "text"},
            {"key": "delta", "label": "Delta", "type": "text"},
            {"key": "tone", "label": "Tone", "type": "tone"},
            {"key": "icon", "label": "Icon", "type": "icon"},
        ],
    },
    "insights": {
        "path": "insights", "singular": "Insight", "key_field": "headline",
        "template": {"headline": "", "detail": "", "tone": "neutral", "icon": "bi bi-lightbulb"},
        "fields": [
            {"key": "headline", "label": "Headline", "type": "text"},
            {"key": "detail", "label": "Detail", "type": "textarea"},
            {"key": "tone", "label": "Tone", "type": "tone"},
            {"key": "icon", "label": "Icon", "type": "icon"},
        ],
    },
    "timeline": {
        "path": "timeline", "singular": "Event", "key_field": "title",
        "template": {"period": "", "title": "", "detail": "", "category": "other", "tone": "neutral"},
        "fields": [
            {"key": "period", "label": "Period", "type": "text"},
            {"key": "title", "label": "Title", "type": "text"},
            {"key": "detail", "label": "Detail", "type": "textarea"},
            {"key": "category", "label": "Category", "type": "select", "options": CATEGORY_OPTS},
            {"key": "tone", "label": "Tone", "type": "tone"},
        ],
    },
    "opportunities": {
        "path": "opportunities", "singular": "Opportunity", "key_field": "area",
        "template": {"area": "", "dimension": "product", "carrier_level": "", "peer_level": "",
                     "gap_score": 50, "recommendation": "", "tone": "good"},
        "fields": [
            {"key": "area", "label": "Area", "type": "text"},
            {"key": "dimension", "label": "Dimension", "type": "select", "options": DIMENSION_OPTS},
            {"key": "gap_score", "label": "Gap score (0-100)", "type": "number"},
            {"key": "carrier_level", "label": "Carrier level", "type": "text"},
            {"key": "peer_level", "label": "Marsh / peer level", "type": "text"},
            {"key": "recommendation", "label": "Recommendation", "type": "text"},
            {"key": "tone", "label": "Tone", "type": "tone"},
        ],
    },
    "points": {
        "path": "positioning.points", "singular": "Carrier", "key_field": "label",
        "template": {"label": "", "premium_strength": 50, "broker_perception": 50,
                     "is_subject": False, "tone": "neutral"},
        "fields": [
            {"key": "label", "label": "Carrier", "type": "text"},
            {"key": "premium_strength", "label": "Premium strength (0-100)", "type": "number"},
            {"key": "broker_perception", "label": "Broker perception (0-100)", "type": "number"},
            {"key": "is_subject", "label": "Subject (carrier in focus)", "type": "bool"},
            {"key": "tone", "label": "Tone", "type": "tone"},
        ],
    },
    "cells": {
        "path": "opportunity_map.cells", "singular": "Cell", "key_field": "row",
        "template": {"row": "", "col": "", "intensity": 50, "tone": "neutral", "note": ""},
        "fields": [
            {"key": "row", "label": "Row (product)", "type": "text"},
            {"key": "col", "label": "Column (market)", "type": "text"},
            {"key": "intensity", "label": "Intensity (0-100)", "type": "number"},
            {"key": "tone", "label": "Tone", "type": "tone"},
            {"key": "note", "label": "Note", "type": "text"},
        ],
    },
    "metrics": {
        "path": "comparison.metrics", "singular": "Metric row", "key_field": "label",
        "template": {"label": "", "values": [], "tones": []},
        "fields": [
            {"key": "label", "label": "Metric", "type": "text"},
            {"key": "values", "label": "Values — one per subject (comma-separated)", "type": "csv"},
            {"key": "tones", "label": "Tones — optional (comma-separated)", "type": "csv"},
        ],
    },
    "battlecards": {
        "path": "battlecards", "singular": "Battlecard", "key_field": "carrier",
        "template": {"carrier": "", "peer_position": "", "strengths": [], "weaknesses": [],
                     "product_gaps": [], "broker_perception": ""},
        "fields": [
            {"key": "carrier", "label": "Carrier", "type": "text"},
            {"key": "peer_position", "label": "Peer position", "type": "text"},
            {"key": "strengths", "label": "Strengths (one per line)", "type": "lines"},
            {"key": "weaknesses", "label": "Weaknesses (one per line)", "type": "lines"},
            {"key": "product_gaps", "label": "Product gaps (one per line)", "type": "lines"},
            {"key": "broker_perception", "label": "Broker perception", "type": "text"},
        ],
    },
    "risks": {
        "path": "risks", "singular": "Risk", "key_field": "label",
        "template": {"label": "", "severity": "Med", "tone": "warn"},
        "fields": [
            {"key": "label", "label": "Risk", "type": "text"},
            {"key": "severity", "label": "Severity", "type": "select", "options": SEVERITY_OPTS},
            {"key": "tone", "label": "Tone", "type": "tone"},
        ],
    },
}


# ── per-kind editor config: which scalar fields + which repeatable lists ──
#   scalar field "type"s reuse the control vocabulary below; their "key" is the
#   data dot-path (or a special token like "commentary_points").
KIND_EDITORS: Dict[str, Dict[str, Any]] = {
    "kpi": {"scalars": [], "lists": ["kpis"]},
    "insights": {"scalars": [], "lists": ["insights"]},
    "timeline": {"scalars": [], "lists": ["timeline"]},
    "commentary": {
        "scalars": [
            {"key": "headline", "label": "Headline", "type": "text"},
            {"key": "commentary_points", "label": "Commentary points (one per line)", "type": "lines"},
        ],
        "lists": ["risks"],
    },
    "opportunity_radar": {"scalars": [], "lists": ["opportunities"]},
    "opportunity_map": {
        "scalars": [
            {"key": "opportunity_map.rows", "label": "Rows — products/segments (one per line)", "type": "lines"},
            {"key": "opportunity_map.cols", "label": "Columns — markets (one per line)", "type": "lines"},
            {"key": "opportunity_map.legend", "label": "Legend", "type": "text"},
        ],
        "lists": ["cells"],
    },
    "positioning": {
        "scalars": [{"key": "positioning.note", "label": "Note", "type": "text"}],
        "lists": ["points"],
    },
    "comparison": {
        "scalars": [
            {"key": "comparison.subjects", "label": "Subjects (one per line)", "type": "lines"},
            {"key": "comparison.highlight", "label": "Highlight subject index (0-based)", "type": "number"},
        ],
        "lists": ["metrics"],
    },
    "battlecards": {"scalars": [], "lists": ["battlecards"]},
}


def spec_by_path(path: str) -> Optional[Dict[str, Any]]:
    """Find the list spec whose data path matches (used by the add/remove callback)."""
    return next((s for s in LIST_SPECS.values() if s["path"] == path), None)


# ───────────────────────── id + control builders ─────────────────────────


def _ef(key: str):
    return {"type": "bm-ef", "key": key}


def _row(label: str, control):
    return html.Div([html.Label(label, className="bm-ef-label"), control], className="bm-ef-row")


def _control(ftype: str, key: str, value: Any, options: Optional[List[dict]] = None):
    if ftype == "textarea":
        return dcc.Textarea(id=_ef(key), value=value or "", className="bm-ef-textarea")
    if ftype == "lines":
        text = "\n".join(value) if isinstance(value, list) else (value or "")
        return dcc.Textarea(id=_ef(key), value=text, className="bm-ef-textarea")
    if ftype == "csv":
        text = ", ".join(str(x) for x in value) if isinstance(value, list) else (value or "")
        return dcc.Input(id=_ef(key), value=text, className="bm-ef-input")
    if ftype == "number":
        return dcc.Input(id=_ef(key), type="number",
                         value=value if value not in (None, "") else None,
                         className="bm-ef-input bm-ef-num")
    if ftype == "tone":
        return dcc.Dropdown(id=_ef(key), value=value or "neutral", options=icons.tone_options(),
                            clearable=False, className="bm-ef-select")
    if ftype == "icon":
        return dcc.Dropdown(id=_ef(key), value=value or "", options=icons.icon_options(),
                            clearable=False, className="bm-ef-select")
    if ftype == "select":
        default = options[0]["value"] if options else ""
        return dcc.Dropdown(id=_ef(key), value=value if value is not None else default,
                            options=options or [], clearable=False, className="bm-ef-select")
    # text (default)
    return dcc.Input(id=_ef(key), value=value or "", className="bm-ef-input")


def _field_row(field: Dict[str, Any], key: str, value: Any):
    if field["type"] == "bool":
        return html.Div(
            dbc.Switch(id=_ef(key), label=field["label"], value=bool(value)),
            className="bm-ef-row bm-ef-switch",
        )
    return _row(field["label"], _control(field["type"], key, value, field.get("options")))


# Thin wrappers kept for the always-present + generic-content fields.
def _text(key, label, value=""):
    return _row(label, _control("text", key, value))


def _textarea(key, label, value=""):
    return _row(label, _control("textarea", key, value))


def _select(key, label, value, options):
    return _row(label, _control("select", key, value, options))


def _checks(key, options, value):
    return html.Div(
        dcc.Checklist(id=_ef(key), options=options, value=value, className="bm-ef-checks"),
        className="bm-ef-row",
    )


def _note(text):
    return html.Div([html.I(className="bi bi-info-circle"), html.Span(text)], className="bm-ef-note")


def _section(title: str, children: List[Any]):
    return html.Div([html.Div(title, className="bm-ef-section-title")] + children, className="bm-ef-section")


def _image_field(url: str = ""):
    """Image / logo picker: upload a local file (stored inline as a data URI) or
    paste a URL. The collected ``url`` input is what ``apply_editor`` reads, so an
    upload simply writes its base64 contents into that field."""
    has = bool((url or "").strip())
    return html.Div(
        [
            html.Label("Image / logo", className="bm-ef-label"),
            dcc.Upload(
                id="bm-img-upload",
                children=html.Div(
                    [
                        html.I(className="bi bi-upload"),
                        html.Span("Drag & drop or click to upload from your device"),
                        html.Small("PNG, JPG, SVG or GIF", className="bm-img-upload-hint"),
                    ],
                    className="bm-img-upload-inner",
                ),
                accept="image/*",
                multiple=False,
                className="bm-img-upload",
            ),
            html.Div("— or paste an image URL —", className="bm-ef-subnote"),
            dcc.Input(
                id=_ef("url"), value=url, debounce=False, className="bm-ef-input",
                placeholder="https://… (or upload a file above)",
            ),
            html.Img(
                id="bm-img-preview", src=url, className="bm-img-preview",
                style={} if has else {"display": "none"},
            ),
        ],
        className="bm-ef-row",
    )


# ───────────────────────── repeatable item sections ─────────────────────────


def _item_card(spec: Dict[str, Any], i: int, item: Dict[str, Any]):
    head = html.Div(
        [
            html.Span(f"{spec['singular']} {i + 1}", className="bm-ef-item-badge"),
            html.Button(
                html.I(className="bi bi-trash"),
                id={"type": "bm-ef-del", "list": spec["path"], "i": i},
                n_clicks=0, className="bm-ef-item-del", title="Remove",
            ),
        ],
        className="bm-ef-item-head",
    )
    body = [
        _field_row(f, f"{spec['path']}.{i}.{f['key']}", item.get(f["key"]))
        for f in spec["fields"]
    ]
    return html.Div([head, html.Div(body, className="bm-ef-grid")], className="bm-ef-item")


def _repeat_section(spec: Dict[str, Any], items: List[Dict[str, Any]]):
    cards = [_item_card(spec, i, it or {}) for i, it in enumerate(items)]
    if not cards:
        cards = [html.Div(f"No {spec['singular'].lower()}s yet — add one below.", className="bm-ef-empty")]
    add_btn = html.Button(
        [html.I(className="bi bi-plus-lg"), f"Add {spec['singular'].lower()}"],
        id={"type": "bm-ef-add", "list": spec["path"]}, n_clicks=0, className="bm-ef-add",
    )
    return html.Div([html.Div(cards, className="bm-ef-items"), add_btn], className="bm-ef-repeat")


# ── dot-path helpers (dash-free) ──


def _get_nested(data: Dict[str, Any], dotpath: str, default=None):
    cur: Any = data
    for part in dotpath.split("."):
        if not isinstance(cur, dict) or part not in cur or cur[part] is None:
            return default
        cur = cur[part]
    return cur


def _set_nested(data: Dict[str, Any], dotpath: str, value: Any):
    parts = dotpath.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _commentary_points(data: Dict[str, Any]) -> List[str]:
    pts: List[str] = []
    for s in data.get("sections") or []:
        pts.extend(s.get("points") or [])
    return pts


# ── text<->structure helpers (generic library content) ──


def _table_to_text(data):
    cols = data.get("columns") or []
    rows = data.get("rows") or []
    lines = [", ".join(str(c) for c in cols)]
    for r in rows:
        lines.append(", ".join(str(c) for c in (r if isinstance(r, list) else [r])))
    return "\n".join(lines)


def _text_to_table(text):
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return {"columns": [], "rows": []}
    cols = [c.strip() for c in lines[0].split(",")]
    rows = [[c.strip() for c in ln.split(",")] for ln in lines[1:]]
    return {"columns": cols, "rows": rows}


def _kv_to_text(data):
    return "\n".join(f"{r[0]}: {r[1] if len(r) > 1 else ''}" for r in (data.get("rows") or []))


def _text_to_kv(text):
    rows = []
    for ln in (text or "").splitlines():
        if not ln.strip():
            continue
        k, _, v = ln.partition(":")
        rows.append([k.strip(), v.strip()])
    return {"rows": rows}


# ───────────────────────── form builder ─────────────────────────


def _generic_content_fields(content: str, widget: Dict[str, Any]) -> List[Any]:
    data = widget.get("data") or {}
    meta = widget.get("meta", {})
    out: List[Any] = []
    if content == "text":
        out.append(_textarea("text", "Content", data.get("text", "")))
    elif content == "list":
        out.append(_textarea("items", "Items (one per line)", "\n".join(data.get("items") or [])))
    elif content == "table":
        out.append(_textarea("table", "Table — first line = headers, cells comma-separated", _table_to_text(data)))
    elif content == "kv":
        out.append(_textarea("kv", "Rows — 'key: value' per line", _kv_to_text(data)))
    elif content == "quad":
        for i, q in enumerate((data.get("q") or [])[:4]):
            out.append(_textarea(f"quad.{i}", f"{q.get('title', 'Quadrant')} (one per line)", "\n".join(q.get("items") or [])))
    elif content == "image":
        out.append(_image_field(data.get("url", "")))
        out.append(_text("caption", "Caption", data.get("caption", "")))
    elif content == "section_title":
        out.append(_text("text", "Title text", data.get("text", "")))
    elif content == "quote":
        out.append(_textarea("text", "Quote", data.get("text", "")))
        out.append(_text("attribution", "Attribution", data.get("attribution", "")))
    elif content == "callout":
        out.append(_textarea("text", "Message", data.get("text", "")))
        out.append(_select("tone", "Tone", data.get("tone", "neutral"), icons.tone_options()))
    elif content == "chart":
        out.append(_select("chart_type", "Chart type", meta.get("chart_type") or "", CHART_TYPES))
        out.append(_select("sort", "Sort", meta.get("sort") or "", SORT_OPTS))
    else:
        out.append(_note("Structural widget: edit title, colour, width and visibility here. "
                         "Duplicate it to annotate freely."))
    return out


def build_editor_body(widget: Dict[str, Any]):
    kind = widget["kind"]
    data = widget.get("data") or {}
    meta = widget.get("meta", {})
    m = catalog.meta_of(kind)

    fields: List[Any] = [
        html.Div([html.I(className=m.get("icon", "bi bi-square")), html.Span(m.get("label", kind))],
                 className="bm-ef-kind"),
        _text("title", "Title", widget.get("title", "")),
    ]

    content_children: List[Any] = []
    if kind in KIND_EDITORS:
        cfg = KIND_EDITORS[kind]
        for f in cfg["scalars"]:
            if f["key"] == "commentary_points":
                content_children.append(_field_row(f, "commentary_points", _commentary_points(data)))
            else:
                content_children.append(_field_row(f, f["key"], _get_nested(data, f["key"])))
        for lk in cfg["lists"]:
            spec = LIST_SPECS[lk]
            items = _get_nested(data, spec["path"], []) or []
            content_children.append(html.Div(f"{spec['singular']}s", className="bm-ef-sublabel"))
            content_children.append(_repeat_section(spec, items))
    else:
        content_children.extend(_generic_content_fields(catalog.content_of(kind), widget))

    fields.append(_section("Content", content_children))

    vis = []
    if meta.get("visible_board", True):
        vis.append("visible_board")
    if meta.get("visible_export", True):
        vis.append("visible_export")
    appearance = [
        _select("theme", "Colour theme", meta.get("theme", "default"), themes.theme_options()),
        _select("size", "Width", meta.get("size", "md"), SIZE_OPTS),
        _checks(
            "visibility",
            [{"label": "Show on Boardroom", "value": "visible_board"},
             {"label": "Include in PowerPoint", "value": "visible_export"}],
            vis,
        ),
        _text("reason", "Reason for change (audit)", ""),
    ]
    fields.append(_section("Appearance & governance", appearance))
    return fields


# ───────────────────────── apply ─────────────────────────


def _coerce(ftype: str, val: Any):
    if ftype == "number":
        if val in (None, ""):
            return 0
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return 0
    if ftype == "bool":
        return bool(val)
    if ftype == "lines":
        return [ln.strip() for ln in (val or "").splitlines() if ln.strip()]
    if ftype == "csv":
        return [c.strip() for c in (val or "").split(",") if c.strip()]
    return val if val is not None else ""


def _parse_list(values: Dict[str, Any], spec: Dict[str, Any], keep_empty: bool = False) -> List[Dict[str, Any]]:
    """Rebuild a list from flat ``<path>.<i>.<field>`` keys. Length follows the
    submitted keys (so removed rows just disappear). Blank items are dropped on Save
    but preserved during live editing (``keep_empty``) so in-progress rows survive."""
    prefix = spec["path"] + "."
    by_index: Dict[int, Dict[str, Any]] = {}
    for key, val in values.items():
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix):].split(".")
        if len(rest) != 2 or not rest[0].isdigit():
            continue
        by_index.setdefault(int(rest[0]), {})[rest[1]] = val

    ftypes = {f["key"]: f["type"] for f in spec["fields"]}
    key_field = spec.get("key_field", spec["fields"][0]["key"])
    items: List[Dict[str, Any]] = []
    for i in sorted(by_index):
        raw = by_index[i]
        item = copy.deepcopy(spec["template"])
        for fk, v in raw.items():
            if fk in ftypes:
                item[fk] = _coerce(ftypes[fk], v)
        if not keep_empty and not str(item.get(key_field, "")).strip():
            continue  # blank row → drop on Save
        items.append(item)
    return items


def _apply_generic(content: str, data: Dict[str, Any], meta: Dict[str, Any], values: Dict[str, Any]):
    if content == "text" and "text" in values:
        data["text"] = values["text"]
    elif content == "list" and "items" in values:
        data["items"] = _coerce("lines", values["items"])
    elif content == "table" and "table" in values:
        data.update(_text_to_table(values["table"]))
    elif content == "kv" and "kv" in values:
        data.update(_text_to_kv(values["kv"]))
    elif content == "quad":
        for i in range(4):
            k = f"quad.{i}"
            if k in values:
                qs = data.setdefault("q", [])
                while len(qs) <= i:
                    qs.append({"title": f"Quadrant {len(qs)+1}", "items": []})
                qs[i]["items"] = _coerce("lines", values[k])
    elif content == "image":
        if "url" in values:
            data["url"] = values["url"]
        if "caption" in values:
            data["caption"] = values["caption"]
    elif content == "section_title" and "text" in values:
        data["text"] = values["text"]
    elif content == "quote":
        if "text" in values:
            data["text"] = values["text"]
        if "attribution" in values:
            data["attribution"] = values["attribution"]
    elif content == "callout":
        if "text" in values:
            data["text"] = values["text"]
        if "tone" in values:
            data["tone"] = values["tone"]
    elif content == "chart":
        meta["chart_type"] = values.get("chart_type") or None
        meta["sort"] = values.get("sort") or None


def _materialize(widget: Dict[str, Any], values: Dict[str, Any], keep_empty: bool = False) -> None:
    """Write collected {key: value} edits into a widget in place (no provenance).
    Shared by ``apply_editor`` (on Save, ``keep_empty=False``) and the live
    add/remove-row callback (``keep_empty=True`` to preserve in-progress rows)."""
    kind = widget["kind"]
    data = widget.setdefault("data", {})
    meta = widget.setdefault("meta", {})

    if "title" in values:
        widget["title"] = values["title"]

    if kind in KIND_EDITORS:
        cfg = KIND_EDITORS[kind]
        for f in cfg["scalars"]:
            key = f["key"]
            if key == "commentary_points":
                if "commentary_points" in values:
                    pts = _coerce("lines", values["commentary_points"])
                    data["sections"] = [{"heading": "Commentary", "points": pts}] if pts else []
                continue
            if key in values:
                _set_nested(data, key, _coerce(f["type"], values[key]))
        for lk in cfg["lists"]:
            spec = LIST_SPECS[lk]
            _set_nested(data, spec["path"], _parse_list(values, spec, keep_empty=keep_empty))
    else:
        _apply_generic(catalog.content_of(kind), data, meta, values)

    if "theme" in values:
        meta["theme"] = values["theme"]
    if "size" in values:
        meta["size"] = values["size"]
    if "visibility" in values:
        vis = values["visibility"] or []
        meta["visible_board"] = "visible_board" in vis
        meta["visible_export"] = "visible_export" in vis


def apply_editor(widget: Dict[str, Any], values: Dict[str, Any], user_id: str | None) -> None:
    """Apply collected edits to a widget (in place, with provenance + audit entry)."""
    _materialize(widget, values)
    reason = (values.get("reason") or "").strip()
    changes = {k: v for k, v in values.items() if k != "reason"}
    model.record_edit(widget, changes=changes, user_id=user_id, reason=reason)


# ───────────────────────── modal shells (mounted once) ─────────────────────────


def editor_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle([html.I(className="bi bi-sliders bm-modal-icon"), "Edit widget"])),
            dbc.ModalBody(html.Div(id="bm-editor-body"), className="bm-editor-body-wrap"),
            dbc.ModalFooter(
                [
                    dbc.Button("Reset to generated", id="bm-editor-reset", className="custom-peers-cancel-btn"),
                    dbc.Button("Cancel", id="bm-editor-cancel", className="custom-peers-cancel-btn"),
                    dbc.Button("Save", id="bm-editor-save", className="custom-peers-apply-btn"),
                ]
            ),
        ],
        id="bm-editor-modal",
        is_open=False,
        size="lg",
        centered=True,
        scrollable=True,
        className="custom-peers-modal bm-editor-modal",
    )


def library_modal():
    cats = catalog.library_by_category()
    sections = []
    for cat in catalog.CATEGORIES:
        if not cats.get(cat):
            continue
        sections.append(html.Div(cat, className="bm-lib-cat"))
        sections.append(
            html.Div(
                [
                    html.Button(
                        [html.I(className=spec["icon"]), html.Span(spec["label"])],
                        id={"type": "bm-lib-pick", "kind": spec["kind"]},
                        n_clicks=0,
                        className="bm-lib-item",
                    )
                    for spec in cats[cat]
                ],
                className="bm-lib-grid",
            )
        )
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle([html.I(className="bi bi-grid-1x2 bm-modal-icon"), "Add a widget"])),
            dbc.ModalBody(sections),
        ],
        id="bm-library-modal",
        is_open=False,
        size="lg",
        centered=True,
        scrollable=True,
        className="custom-peers-modal bm-library-modal",
    )


def info_modal():
    """Reused for 'view source evidence' and 'revision history'."""
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(html.Span(id="bm-info-title"))),
            dbc.ModalBody(html.Div(id="bm-info-body")),
        ],
        id="bm-info-modal",
        is_open=False,
        size="lg",
        centered=True,
        scrollable=True,
        className="custom-peers-modal bm-info-modal",
    )


def all_modals():
    return html.Div([editor_modal(), library_modal(), info_modal()])
