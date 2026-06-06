"""Editor & library-picker modals for the editable Boardroom.

`build_editor_body(widget)` produces a kind-aware form (every input carries a
pattern id ``{"type": "bm-ef", "key": <path>}``). `apply_editor(widget, values,
user_id)` writes those values back, preserving the immutable ``generated`` snapshot
and appending an audit entry. The modals themselves are mounted once in the app
shell and driven by the callbacks in ``ui.boardroom.callbacks``.
"""
from __future__ import annotations

from typing import Any, Dict, List

import dash_bootstrap_components as dbc
from dash import dcc, html

from ui.boardroom import catalog, model, themes

TONE_OPTS = [
    {"label": "Neutral", "value": "neutral"},
    {"label": "Good", "value": "good"},
    {"label": "Caution", "value": "warn"},
    {"label": "Adverse", "value": "danger"},
]
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


def _ef(key: str):
    return {"type": "bm-ef", "key": key}


def _row(label: str, control):
    return html.Div([html.Label(label, className="bm-ef-label"), control], className="bm-ef-row")


def _text(key, label, value=""):
    return _row(label, dcc.Input(id=_ef(key), value=value, debounce=False, className="bm-ef-input"))


def _textarea(key, label, value=""):
    return _row(label, dcc.Textarea(id=_ef(key), value=value, className="bm-ef-textarea"))


def _select(key, label, value, options):
    return _row(label, dcc.Dropdown(id=_ef(key), value=value, options=options, clearable=False, className="bm-ef-select"))


def _checks(key, options, value):
    return html.Div(
        dcc.Checklist(id=_ef(key), options=options, value=value, className="bm-ef-checks"),
        className="bm-ef-row",
    )


def _note(text):
    return html.Div([html.I(className="bi bi-info-circle"), html.Span(text)], className="bm-ef-note")


def _image_field(url: str = ""):
    """Image / logo picker: upload a local file (stored inline as a data URI) or
    paste a URL. The hidden-but-collected ``url`` input is what ``apply_editor``
    reads, so an upload simply writes its base64 contents into that field."""
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


# ── text<->structure helpers ──


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


def _commentary_to_text(data):
    out = []
    for s in data.get("sections") or []:
        for p in s.get("points") or []:
            out.append(p)
    return "\n".join(out)


# ── form builder ──


def build_editor_body(widget: Dict[str, Any]):
    kind = widget["kind"]
    content = catalog.content_of(kind)
    data = widget.get("data") or {}
    meta = widget.get("meta", {})
    fields: List[Any] = [
        html.Div(
            [html.I(className=catalog.meta_of(kind).get("icon", "bi bi-square")),
             html.Span(catalog.meta_of(kind).get("label", kind))],
            className="bm-ef-kind",
        ),
        _text("title", "Title", widget.get("title", "")),
    ]

    if content == "text":
        fields.append(_textarea("text", "Content", data.get("text", "")))
    elif content == "list":
        fields.append(_textarea("items", "Items (one per line)", "\n".join(data.get("items") or [])))
    elif content == "table":
        fields.append(_textarea("table", "Table — first line = headers, cells comma-separated", _table_to_text(data)))
    elif content == "kv":
        fields.append(_textarea("kv", "Rows — 'key: value' per line", _kv_to_text(data)))
    elif content == "quad":
        for i, q in enumerate((data.get("q") or [])[:4]):
            fields.append(_textarea(f"quad.{i}", f"{q.get('title', 'Quadrant')} (one per line)", "\n".join(q.get("items") or [])))
    elif content == "image":
        fields.append(_image_field(data.get("url", "")))
        fields.append(_text("caption", "Caption", data.get("caption", "")))
    elif content == "section_title":
        fields.append(_text("text", "Title text", data.get("text", "")))
    elif content == "quote":
        fields.append(_textarea("text", "Quote", data.get("text", "")))
        fields.append(_text("attribution", "Attribution", data.get("attribution", "")))
    elif content == "kpis":
        for i, k in enumerate(data.get("kpis") or []):
            fields.append(html.Div(
                [
                    _text(f"kpi.{i}.label", f"KPI {i+1} label", k.get("label", "")),
                    _text(f"kpi.{i}.value", "Value", k.get("value", "")),
                    _text(f"kpi.{i}.delta", "Delta", k.get("delta", "")),
                    _select(f"kpi.{i}.tone", "Tone", k.get("tone", "neutral"), TONE_OPTS),
                ],
                className="bm-ef-kpi",
            ))
    elif content == "callout":
        fields.append(_textarea("text", "Message", data.get("text", "")))
        fields.append(_select("tone", "Tone", data.get("tone", "neutral"), TONE_OPTS))
    elif content == "chart":
        fields.append(_select("chart_type", "Chart type", meta.get("chart_type") or "", CHART_TYPES))
        fields.append(_select("sort", "Sort", meta.get("sort") or "", SORT_OPTS))
    elif kind == "commentary":
        fields.append(_text("headline", "Headline", data.get("headline", "")))
        fields.append(_textarea("commentary_text", "Commentary — one point per line", _commentary_to_text(data)))
    elif kind == "insights":
        txt = "\n".join(
            f"{c.get('headline','')} :: {c.get('detail','')} :: {c.get('tone','neutral')}"
            for c in (data.get("insights") or [])
        )
        fields.append(_textarea("insights_text", "Insights — one per line: headline :: detail :: tone", txt))
    elif kind == "timeline":
        txt = "\n".join(
            f"{e.get('period','')} :: {e.get('title','')} :: {e.get('detail','')} :: {e.get('tone','neutral')}"
            for e in (data.get("timeline") or [])
        )
        fields.append(_textarea("timeline_text", "Timeline — one per line: period :: title :: detail :: tone", txt))
    else:
        fields.append(_note("Structural widget: edit title, colour, width and visibility here. "
                            "Per-item editing is coming soon — duplicate it to annotate freely."))

    # Common appearance + governance
    fields.append(html.Div(className="bm-ef-divider"))
    fields.append(_select("theme", "Colour theme", meta.get("theme", "default"), themes.theme_options()))
    fields.append(_select("size", "Width", meta.get("size", "md"), SIZE_OPTS))
    vis = []
    if meta.get("visible_board", True):
        vis.append("visible_board")
    if meta.get("visible_export", True):
        vis.append("visible_export")
    fields.append(_checks(
        "visibility",
        [{"label": "Show on Boardroom", "value": "visible_board"},
         {"label": "Include in PowerPoint", "value": "visible_export"}],
        vis,
    ))
    fields.append(_text("reason", "Reason for change (audit)", ""))
    return fields


# ── apply ──


def _set_path(data: Dict[str, Any], path: str, value):
    """Set kpi.<i>.<field> style paths inside data."""
    parts = path.split(".")
    if parts[0] == "kpi" and len(parts) == 3:
        idx = int(parts[1])
        kpis = data.setdefault("kpis", [])
        if 0 <= idx < len(kpis):
            kpis[idx][parts[2]] = value


def apply_editor(widget: Dict[str, Any], values: Dict[str, Any], user_id: str | None) -> None:
    """Apply collected {key: value} edits to a widget (in place, with provenance)."""
    kind = widget["kind"]
    content = catalog.content_of(kind)
    data = widget.setdefault("data", {})
    meta = widget.setdefault("meta", {})
    reason = (values.get("reason") or "").strip()
    changes: Dict[str, Any] = {}

    if "title" in values:
        widget["title"] = values["title"]

    if content == "text" and "text" in values:
        data["text"] = values["text"]
    elif content == "list" and "items" in values:
        data["items"] = [ln for ln in (values["items"] or "").splitlines() if ln.strip()]
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
                qs[i]["items"] = [ln for ln in (values[k] or "").splitlines() if ln.strip()]
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
    elif content == "kpis":
        for key, val in values.items():
            if key.startswith("kpi."):
                _set_path(data, key, val)
    elif content == "callout":
        if "text" in values:
            data["text"] = values["text"]
        if "tone" in values:
            data["tone"] = values["tone"]
    elif content == "chart":
        meta["chart_type"] = values.get("chart_type") or None
        meta["sort"] = values.get("sort") or None
    elif kind == "commentary":
        if "headline" in values:
            data["headline"] = values["headline"]
        if "commentary_text" in values:
            pts = [ln for ln in (values["commentary_text"] or "").splitlines() if ln.strip()]
            data["sections"] = [{"heading": "Commentary", "points": pts}] if pts else []
    elif kind == "insights":
        if "insights_text" in values:
            items = []
            for ln in (values["insights_text"] or "").splitlines():
                if not ln.strip():
                    continue
                p = [x.strip() for x in ln.split("::")]
                items.append({
                    "headline": p[0] if p else "",
                    "detail": p[1] if len(p) > 1 else "",
                    "tone": p[2] if len(p) > 2 else "neutral",
                    "icon": "bi bi-lightbulb",
                })
            data["insights"] = items
    elif kind == "timeline":
        if "timeline_text" in values:
            evts = []
            for ln in (values["timeline_text"] or "").splitlines():
                if not ln.strip():
                    continue
                p = [x.strip() for x in ln.split("::")]
                evts.append({
                    "period": p[0] if p else "",
                    "title": p[1] if len(p) > 1 else "",
                    "detail": p[2] if len(p) > 2 else "",
                    "tone": p[3] if len(p) > 3 else "neutral",
                    "category": "other",
                })
            data["timeline"] = evts

    if "theme" in values:
        meta["theme"] = values["theme"]
    if "size" in values:
        meta["size"] = values["size"]
    if "visibility" in values:
        vis = values["visibility"] or []
        meta["visible_board"] = "visible_board" in vis
        meta["visible_export"] = "visible_export" in vis

    changes = {k: v for k, v in values.items() if k not in ("reason",)}
    model.record_edit(widget, changes=changes, user_id=user_id, reason=reason)


# ── modal shells (mounted once) ──


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
