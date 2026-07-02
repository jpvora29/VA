"""The Widget Inspector — the right-hand panel that edits the selected widget.

Builds every inspector surface: the tabbed panel, the color picker, per-role
typography editors, widget appearance, the setup/data/rules tab bodies, and the
"select a widget" hint. Each control's id feeds a document-editing app callback.
"""
from __future__ import annotations

import json
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from dash import dcc, html

from studio.deck.model import DeckSpec, SlideSpec
from studio.page import canvas as CV
from studio.page import document as D

from studio.page.authoring.constants import STANDARD_COLORS, THEME_COLORS
from studio.page.authoring.derive import _edited, _prov_badge


def _inspector_tabs(active: str) -> html.Div:
    tabs = ["Setup", "Data", "Style", "Rules", "Evidence"]
    return html.Div(
        [
            html.Button(
                t,
                id={"type": "qs-insp-tab", "tab": t.lower()},
                className="qs-insp-tab" + (" active" if t.lower() == active else ""),
            )
            for t in tabs
        ],
        className="qs-insp-tabs",
    )


def _kv(label: str, value: Any) -> html.Div:
    return html.Div(
        [html.Span(label, className="qs-kv-k"), html.Span(value if value not in (None, "") else "—", className="qs-kv-v")],
        className="qs-kv",
    )


def _chart_control(slide: SlideSpec, idx: int) -> Any:
    """Real, persisted widget config: switch the chart type for a chart slide.

    Feeds ``document.set_config`` → ``materialize`` → both the on-screen slide and
    the PowerPoint export, so the choice is a true document change, not decoration.
    """
    chart_block = next((b for b in slide.blocks if b.kind == "chart"), None)
    if chart_block is None:
        return None
    return html.Div(
        [
            html.Div("CHART TYPE", className="qs-kv-k", style={"marginTop": "12px"}),
            dcc.RadioItems(
                id={"type": "qs-chart", "idx": idx},
                options=[
                    {"label": "Bar", "value": "bar"},
                    {"label": "Donut", "value": "donut"},
                    {"label": "Waterfall", "value": "waterfall"},
                ],
                value=getattr(chart_block, "chart", "bar"),
                className="qs-chart-radio",
                inputClassName="qs-chart-input",
                labelClassName="qs-chart-label",
            ),
        ]
    )


def _inspector_panel(slide: SlideSpec, idx: int, tab: str, deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> html.Div:
    meta = dict(deck.meta or {})
    block = slide.blocks[0] if slide.blocks else None
    body: Any
    if tab == "data":
        rows = [
            _kv("Dataset", "GPR — Gross Premium"),
            _kv("Carrier", meta.get("carrier")),
            _kv("Market", meta.get("country")),
            _kv("Period", meta.get("year")),
            _kv("Visual", getattr(block, "chart", None) or (block.kind if block else "—")),
            _kv("Comparison", "vs prior FY"),
            _kv("Refresh", "Live · deterministic"),
        ]
        body = html.Div(rows, className="qs-kv-list")
    elif tab == "style":
        body = html.Div(
            [
                _kv("Treatment", "Approved navy/blue"),
                _kv("Number format", "USD, 1 decimal"),
                _kv("Accent", slide.accent.title()),
                html.Div(
                    [html.Span(className=f"qs-swatch {c}") for c in ("blue", "teal", "navy", "green", "amber")],
                    className="qs-swatch-row",
                ),
                _chart_control(slide, idx)
                or html.Div("This widget has no configurable chart.", className="qs-ev-src", style={"marginTop": "12px"}),
            ],
            className="qs-kv-list",
        )
    elif tab == "rules":
        body = html.Div(
            [
                _kv("Inclusion", "Material movement"),
                _kv("Min sample", "Governed threshold"),
                _kv("Missing data", "Disclosed, never invented"),
                _kv("Confidentiality", "Strictly Private & Confidential"),
                _kv("Narrative source", "Rules verified"),
                _kv("Export", "Native chart where supported"),
            ],
            className="qs-kv-list",
        )
    elif tab == "evidence":
        if slide.evidence:
            chips = [
                html.Div(
                    [
                        html.Span(e.get("label", ""), className="qs-ev-k"),
                        html.Span(e.get("value", ""), className="qs-ev-v"),
                        html.Span(e.get("detail", ""), className="qs-ev-d") if e.get("detail") else None,
                    ],
                    className="qs-ev-chip",
                )
                for e in slide.evidence
            ]
            ev = html.Div(chips, className="qs-ev-list")
        else:
            ev = html.Div(
                [html.I(className="bi bi-exclamation-triangle"), "No evidence linked to this slide."],
                className="qs-ev-empty",
            )
        body = html.Div(
            [
                html.Div("State: Verified · deterministic" if slide.evidence else "State: Missing", className="qs-ev-state"),
                ev,
                html.Div("SOURCES", className="qs-kv-k", style={"marginTop": "12px"}),
                html.Div("  ·  ".join(slide.sources) if slide.sources else "GPR, Carrier Survey", className="qs-ev-src"),
            ]
        )
    else:  # setup
        edited = _edited(doc, idx, "title")
        body = html.Div(
            [
                html.Div("ACTION TITLE", className="qs-kv-k"),
                dcc.Textarea(
                    id={"type": "qs-edit", "field": "title", "idx": idx},
                    value=slide.title,
                    className="qs-insp-edit",
                ),
                html.Div(
                    [
                        _prov_badge(edited),
                        html.Button(
                            "Reset", id={"type": "qs-reset", "field": "title", "idx": idx}, className="qs-reset-link"
                        )
                        if edited
                        else None,
                    ],
                    className="qs-prov-row",
                ),
                html.Div(
                    [
                        _kv("Layout", slide.layout.title()),
                        _kv("Widget", block.kind if block else "—"),
                        _kv("Question", slide.question),
                        _kv("Owner", slide.owner),
                        _kv("Due", slide.due_date),
                    ],
                    className="qs-kv-list",
                    style={"marginTop": "10px"},
                ),
            ]
        )
    return html.Div(
        [
            html.Div([html.I(className="bi bi-sliders"), "Widget inspector"], className="qs-panel-title"),
            _inspector_tabs(tab),
            html.Div(body, className="qs-insp-body"),
        ],
        className="qs-inspector",
    )


def _inspector_section(title: str, children: Sequence[Any], icon: str = "") -> html.Div:
    return html.Div(
        [
            html.Div(
                [html.I(className=f"bi {icon}") if icon else None, html.Span(title)],
                className="qs-wsection-title",
            ),
            html.Div(list(children), className="qs-wsection-body"),
        ],
        className="qs-wsection",
    )


def _color_picker(
    *,
    scope: str,
    owner: str,
    prop: str,
    value: str,
) -> html.Div:
    def swatches(colors: Sequence[Tuple[str, str]]) -> html.Div:
        return html.Div(
            [
                html.Button(
                    title=label,
                    className="qs-color-swatch"
                    + (" active" if color.upper() == value.upper() else ""),
                    style={"backgroundColor": color},
                    id={
                        "type": "qs-color-swatch",
                        "scope": scope,
                        "owner": owner,
                        "prop": prop,
                        "value": color,
                    },
                    **{"aria-label": label},
                )
                for color, label in colors
            ],
            className="qs-color-swatches",
        )

    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        className="qs-current-color",
                        style={"backgroundColor": value},
                    ),
                    html.Span(value.upper(), className="qs-current-color-code"),
                ],
                className="qs-current-color-row",
            ),
            html.Div("Theme colors", className="qs-color-group-label"),
            swatches(THEME_COLORS),
            html.Div("Standard colors", className="qs-color-group-label"),
            swatches(STANDARD_COLORS),
            html.Div("Custom color", className="qs-color-group-label"),
            dcc.Input(
                id={
                    "type": "qs-color-custom",
                    "scope": scope,
                    "owner": owner,
                    "prop": prop,
                },
                type="text",
                value=value.upper(),
                debounce=True,
                placeholder="#RRGGBB",
                className="qs-color-hex-input",
            ),
        ],
        className="qs-color-picker",
    )


def _slide_appearance(doc: Mapping[str, Any], sid: str) -> html.Div:
    style = D.effective_page_style(doc, sid)
    return _inspector_section(
        "Slide appearance",
        [
            html.Label("Background color", className="qs-control-label"),
            _color_picker(
                scope="page",
                owner=sid,
                prop="background_color",
                value=style["background_color"],
            ),
        ],
        icon="bi-easel2",
    )


def _text_role_editor(
    doc: Mapping[str, Any], sid: str, wid: str, role: str, label: str
) -> html.Div:
    style = D.effective_text_style(doc, sid, wid, role)
    return html.Details(
        [
            html.Summary(
                [
                    html.Span(label),
                    html.Span(
                        f"{style['font_family']} · {style['font_size']} pt",
                        className="qs-type-summary-meta",
                    ),
                ],
                className="qs-type-summary",
            ),
            html.Div(
                [
                    html.Label("Font family", className="qs-control-label"),
                    dcc.Dropdown(
                        id={
                            "type": "qs-tstyle",
                            "wid": wid,
                            "role": role,
                            "prop": "font_family",
                        },
                        options=[
                            {"label": name, "value": name} for name in D.FONT_FAMILIES
                        ],
                        value=style["font_family"],
                        clearable=False,
                        className="qs-style-dropdown",
                    ),
                    html.Label("Font size", className="qs-control-label"),
                    dcc.Input(
                        id={
                            "type": "qs-tstyle",
                            "wid": wid,
                            "role": role,
                            "prop": "font_size",
                        },
                        type="number",
                        min=6,
                        max=72,
                        step=1,
                        value=style["font_size"],
                        debounce=True,
                        className="qs-number-input",
                    ),
                    html.Label("Font color", className="qs-control-label"),
                    _color_picker(
                        scope="text",
                        owner=f"{wid}::{role}",
                        prop="font_color",
                        value=style["font_color"],
                    ),
                ],
                className="qs-type-role-body",
            ),
        ],
        className="qs-type-role",
        open=role in {"title", "heading", "value", "body", "label"},
    )


def _widget_appearance(
    doc: Mapping[str, Any], sid: str, wid: str, kind: str
) -> List[html.Div]:
    roles = D.widget_text_roles(kind)
    typography = _inspector_section(
        "Text styles",
        [
            *[
                _text_role_editor(doc, sid, wid, role, label)
                for role, label in roles
            ],
            html.Div(
                "Each text role is styled independently and exports with the same typography.",
                className="qs-control-help",
            ),
        ]
        if roles
        else [
            html.Div(
                "This widget has no editable text roles.",
                className="qs-ev-src",
            )
        ],
        icon="bi-fonts",
    )
    style = D.effective_widget_style(doc, sid, wid)
    appearance = _inspector_section(
        "Widget appearance",
        [
            html.Label("Background color", className="qs-control-label"),
            _color_picker(
                scope="widget",
                owner=wid,
                prop="background_color",
                value=style["background_color"],
            ),
        ],
        icon="bi-palette2",
    )
    return [typography, appearance]


def _legacy_widget_inspector(doc: Mapping[str, Any], sid: str, wid: str) -> html.Div:
    """Inspector bound to the SELECTED widget — edit its content + geometry."""
    w = D.get_widget(doc, sid, wid)
    if not w:
        return _select_hint(doc, sid)
    kind, p = w["kind"], w.get("props", {})
    fields: List[Any] = []

    def text_field(label, prop, value, area=False):
        comp = (dcc.Textarea if area else dcc.Input)
        return html.Div(
            [
                html.Div(label, className="qs-kv-k"),
                comp(id={"type": "qs-wprop", "wid": wid, "prop": prop}, value=value or "",
                     className="qs-insp-edit" if area else "qs-wprop-input", **({} if area else {"type": "text"})),
            ],
            style={"marginBottom": "10px"},
        )

    if kind == "headline":
        fields.append(text_field("TEXT", "text", p.get("text", ""), area=True))
        fields.append(text_field("EYEBROW", "eyebrow", p.get("eyebrow", "")))
        fields.append(text_field("SUBTITLE", "subtitle", p.get("subtitle", ""), area=True))
    elif kind == "divider":
        fields.append(text_field("TEXT", "text", p.get("text", ""), area=True))
    elif kind == "reco":
        fields.append(text_field("RECOMMENDATION", "text", p.get("text", ""), area=True))
        fields.append(text_field("OWNER", "owner", p.get("owner", "")))
        fields.append(text_field("DUE", "due", p.get("due", "")))
        fields.append(text_field("CONFIDENCE", "confidence", p.get("confidence", "")))
    elif kind == "text":
        fields.append(text_field("HEADING", "heading", p.get("heading", "")))
        if p.get("swot"):
            fields.append(
                html.Div(
                    "SWOT quadrant editing remains governed by its structured data.",
                    className="qs-ev-src",
                )
            )
        else:
            fields.append(
                text_field(
                    "COMMENTARY POINTS",
                    "points_text",
                    D.commentary_to_text(p.get("points", [])),
                    area=True,
                )
            )
            fields.append(
                html.Div(
                    "One point per line. Optional format: [warn] Label: commentary.",
                    className="qs-control-help",
                )
            )
    elif kind == "chart":
        fields.append(html.Div("CHART TYPE", className="qs-kv-k"))
        fields.append(dcc.RadioItems(
            id={"type": "qs-wchart", "wid": wid},
            options=[{"label": "Bar", "value": "bar"}, {"label": "Donut", "value": "donut"}, {"label": "Waterfall", "value": "waterfall"}],
            value=p.get("chart", "bar"), className="qs-chart-radio", inputClassName="qs-chart-input", labelClassName="qs-chart-label",
        ))
    elif kind in CV._PLACEHOLDER_KINDS:
        fields.append(html.Div("Advanced widget. Data binding + native PPT rendering are the next milestone.",
                               className="qs-ev-empty"))

    geo = html.Div(
        [_kv("Column", f"{w['x']+1}–{w['x']+w['w']} of 12"), _kv("Row", f"{w['y']+1}–{w['y']+w['h']} of 8"),
         _kv("Size", f"{w['w']}×{w['h']} cells")],
        className="qs-kv-list", style={"marginTop": "8px"},
    )
    content_section = _inspector_section("Content", fields, icon="bi-pencil-square")
    scroll_content = [content_section, *_widget_appearance(doc, sid, wid, kind), _slide_appearance(doc, sid), geo]
    return html.Div(
        [
            html.Div([html.I(className="bi bi-bounding-box-circles"), "Widget inspector"], className="qs-panel-title"),
            html.Div(
                [html.Span(D.WIDGET_DEFAULTS.get(kind, {}).get("label", kind), className="qs-wsel-kind"),
                 html.Div([
                     html.Button([html.I(className="bi bi-files")], id={"type": "qs-wop", "op": "duplicate", "wid": wid}, className="qs-wop-btn", title="Duplicate"),
                     html.Button([html.I(className="bi bi-trash3")], id={"type": "qs-wop", "op": "delete", "wid": wid}, className="qs-wop-btn danger", title="Delete"),
                 ], className="qs-wsel-ops")],
                className="qs-wsel-head",
            ),
            html.Div(scroll_content, className="qs-inspector-scroll"),
            html.P("Drag the widget to move it; drag a corner to resize. Changes save to the document and export.",
                   className="qs-analyst-foot"),
        ],
        className="qs-inspector qs-inspector-full",
    )


def _widget_tabs(kind: str, active: str) -> Tuple[html.Div, str]:
    tabs = [("setup", "Setup")]
    if kind in {
        "text", "chart", "table", "kpi", "kpiband", "reco", "matrix",
        "heatmap", "radar", "radial", "bridge", "timeline", "callout", "actions",
    }:
        tabs.append(("data", "Data"))
    tabs.extend([("style", "Style"), ("rules", "Rules")])
    active = active if active in {key for key, _ in tabs} else "setup"
    return (
        html.Div(
            [
                html.Button(
                    label,
                    id={"type": "qs-insp-tab", "tab": key},
                    className="qs-insp-tab" + (" active" if key == active else ""),
                )
                for key, label in tabs
            ],
            className="qs-insp-tabs qs-widget-tabs",
        ),
        active,
    )


def _widget_setup_body(w: Mapping[str, Any]) -> html.Div:
    kind, wid, p = w["kind"], w["id"], w.get("props", {})

    def text_field(label, prop, value, area=False):
        comp = dcc.Textarea if area else dcc.Input
        return html.Div(
            [
                html.Div(label, className="qs-kv-k"),
                comp(
                    id={"type": "qs-wprop", "wid": wid, "prop": prop},
                    value=value or "",
                    className="qs-insp-edit" if area else "qs-wprop-input",
                    **({} if area else {"type": "text"}),
                ),
            ],
            className="qs-inspector-field",
        )

    fields: List[Any] = []
    if kind == "headline":
        fields.extend(
            [
                text_field("TEXT", "text", p.get("text"), area=True),
                text_field("EYEBROW", "eyebrow", p.get("eyebrow")),
                text_field("SUBTITLE", "subtitle", p.get("subtitle"), area=True),
            ]
        )
    elif kind == "divider":
        fields.append(text_field("TEXT", "text", p.get("text"), area=True))
    elif kind == "reco":
        fields.extend(
            [
                text_field("RECOMMENDATION", "text", p.get("text"), area=True),
                text_field("OWNER", "owner", p.get("owner")),
                text_field("DUE", "due", p.get("due")),
                text_field("CONFIDENCE", "confidence", p.get("confidence")),
            ]
        )
    elif kind == "text":
        fields.append(text_field("HEADING", "heading", p.get("heading")))
        if p.get("swot"):
            fields.append(
                html.Div(
                    "SWOT quadrant editing remains governed by structured data.",
                    className="qs-ev-src",
                )
            )
        else:
            fields.extend(
                [
                    text_field(
                        "COMMENTARY POINTS",
                        "points_text",
                        D.commentary_to_text(p.get("points", [])),
                        area=True,
                    ),
                    html.Div(
                        "One point per line. Optional: [warn] Label: commentary.",
                        className="qs-control-help",
                    ),
                ]
            )
    elif kind in {"chart", "matrix", "heatmap", "radar", "radial", "bridge", "timeline", "actions"}:
        fields.append(text_field("TITLE", "title", p.get("title")))
    elif kind == "callout":
        fields.extend(
            [
                text_field("LABEL", "label", p.get("label")),
                text_field("HEADLINE", "title", p.get("title"), area=True),
                text_field("BODY", "body", p.get("body"), area=True),
            ]
        )
    elif kind in CV._PLACEHOLDER_KINDS:
        fields.append(
            html.Div(
                "Advanced widget. Configure data and presentation in their dedicated tabs.",
                className="qs-ev-empty",
            )
        )
    return html.Div(
        [
            _inspector_section("Content", fields, icon="bi-pencil-square"),
            _inspector_section(
                "Dimensions",
                [
                    _kv("Column", f"{w['x'] + 1}–{w['x'] + w['w']} of 12"),
                    _kv("Row", f"{w['y'] + 1}–{w['y'] + w['h']} of 8"),
                    _kv("Size", f"{w['w']}×{w['h']} cells"),
                ],
                icon="bi-bounding-box",
            ),
        ]
    )


def _widget_data_body(w: Mapping[str, Any]) -> html.Div:
    kind, wid, p = w["kind"], w["id"], w.get("props", {})
    rows: List[Any] = []
    if kind == "chart":
        rows.extend(
            [
                html.Div("CHART TYPE", className="qs-kv-k"),
                dcc.RadioItems(
                    id={"type": "qs-wchart", "wid": wid},
                    options=[
                        {"label": "Bar", "value": "bar"},
                        {"label": "Line", "value": "line"},
                        {"label": "Donut", "value": "donut"},
                        {"label": "Waterfall", "value": "waterfall"},
                    ],
                    value=p.get("chart", "bar"),
                    className="qs-chart-radio",
                    inputClassName="qs-chart-input",
                    labelClassName="qs-chart-label",
                ),
                _kv("Categories", len(p.get("labels", []))),
                _kv("Values", len(p.get("values", []))),
            ]
        )
    elif kind == "table":
        rows.extend([_kv("Columns", len(p.get("columns", []))), _kv("Rows", len(p.get("rows", [])))])
    elif kind in {"kpi", "kpiband"}:
        rows.extend([_kv("Metrics", len(p.get("items", []))), _kv("Source", "Verified deck facts")])
    elif kind == "text":
        rows.extend(
            [
                _kv("Commentary points", len(p.get("points", []))),
                _kv("Tone markers", "good · warn · danger · neutral"),
            ]
        )
    elif kind == "reco":
        rows.extend([_kv("Owner", p.get("owner")), _kv("Due", p.get("due")), _kv("Confidence", p.get("confidence"))])
    elif kind in {"matrix", "heatmap", "radar", "radial", "bridge", "timeline", "callout", "actions"}:
        rows.append(_kv("Widget", D.WIDGET_DEFAULTS.get(kind, {}).get("label", kind)))
    if kind in {
        "chart", "table", "kpi", "kpiband", "matrix", "heatmap", "radar",
        "radial", "bridge", "timeline", "callout", "actions",
    }:
        rows.extend(
            [
                html.Div("EDIT WIDGET DATA", className="qs-kv-k", style={"marginTop": "12px"}),
                dcc.Textarea(
                    id={"type": "qs-wprop", "wid": wid, "prop": "data_json"},
                    value=json.dumps(p, indent=2),
                    className="qs-insp-edit qs-data-json",
                ),
                html.Div(
                    "JSON changes apply on blur. Keep labels and values aligned.",
                    className="qs-control-help",
                ),
            ]
        )
    rows.append(_kv("Binding", "Shared Studio document"))
    return _inspector_section("Data", rows, icon="bi-database")


def _widget_rules_body() -> html.Div:
    return html.Div(
        [
            _inspector_section(
                "Governance rules",
                [
                    _kv("Snap guides", "Enabled · hidden"),
                    _kv("Overflow", "Clip within widget bounds"),
                    _kv("Missing data", "Disclose; never invent"),
                    _kv("Export", "Native PowerPoint objects"),
                    _kv("Typography", "Role styles preserved"),
                ],
                icon="bi-shield-check",
            ),
            _inspector_section(
                "Responsive behavior",
                [
                    html.Div(
                        "Geometry stays on the governed grid; text reflows inside its widget.",
                        className="qs-ev-src",
                    )
                ],
                icon="bi-aspect-ratio",
            ),
        ]
    )


def _widget_inspector(
    doc: Mapping[str, Any],
    sid: str,
    wid: str,
    active_tab: str = "setup",
    collapsed: bool = False,
) -> html.Div:
    w = D.get_widget(doc, sid, wid)
    if not w:
        return _select_hint(doc, sid, collapsed)
    kind = w["kind"]
    tabs, active_tab = _widget_tabs(kind, active_tab)
    if active_tab == "style":
        body = html.Div(
            [*_widget_appearance(doc, sid, wid, kind), _slide_appearance(doc, sid)]
        )
    elif active_tab == "rules":
        body = _widget_rules_body()
    elif active_tab == "data":
        body = _widget_data_body(w)
    else:
        body = _widget_setup_body(w)
    return html.Div(
        [
            _panel_toggle("inspector", collapsed),
            html.Div(
                [html.I(className="bi bi-bounding-box-circles"), "Widget inspector"],
                className="qs-panel-title",
            ),
            html.Div(
                [
                    html.Span(
                        D.WIDGET_DEFAULTS.get(kind, {}).get("label", kind),
                        className="qs-wsel-kind",
                    ),
                    html.Div(
                        [
                            html.Button(
                                html.I(className="bi bi-files"),
                                id={"type": "qs-wop", "op": "duplicate", "wid": wid},
                                className="qs-wop-btn",
                                title="Duplicate",
                            ),
                            html.Button(
                                html.I(className="bi bi-trash3"),
                                id={"type": "qs-wop", "op": "delete", "wid": wid},
                                className="qs-wop-btn danger",
                                title="Delete",
                            ),
                        ],
                        className="qs-wsel-ops",
                    ),
                ],
                className="qs-wsel-head",
            ),
            tabs,
            html.Div(body, className="qs-inspector-scroll"),
            html.P(
                "Drag to move; drag a handle to resize. Changes save and export.",
                className="qs-analyst-foot",
            ),
        ],
        className="qs-inspector qs-inspector-full",
    )


def _select_hint(
    doc: Optional[Mapping[str, Any]] = None,
    sid: Optional[str] = None,
    collapsed: bool = False,
) -> html.Div:
    children: List[Any] = [
        html.Div(
            [
                html.I(className="bi bi-hand-index qs-empty-icon"),
                html.Div("Select a widget", className="qs-empty-title"),
                html.P(
                    "Click any block on the canvas to edit content and appearance. "
                    "Drag to move, drag a corner to resize.",
                    className="qs-empty-sub",
                ),
            ],
            className="qs-wsel-empty",
        )
    ]
    if doc and sid:
        children.append(_slide_appearance(doc, sid))
    return html.Div(
        [
            _panel_toggle("inspector", collapsed),
            html.Div([html.I(className="bi bi-cursor"), "Widget inspector"], className="qs-panel-title"),
            html.Div(children, className="qs-inspector-scroll"),
        ],
        className="qs-inspector qs-inspector-full",
    )


def _panel_toggle(panel: str, collapsed: bool) -> html.Button:
    """Small persistent rail control used by the inspector and component library."""
    is_inspector = panel == "inspector"
    if is_inspector:
        icon = "bi-chevron-left" if collapsed else "bi-chevron-right"
        label = "Expand widget inspector" if collapsed else "Collapse widget inspector"
    else:
        icon = "bi-chevron-up" if collapsed else "bi-chevron-down"
        label = "Expand component library" if collapsed else "Collapse component library"
    return html.Button(
        html.I(className=f"bi {icon}"),
        id={"type": "qs-panel-toggle", "panel": panel},
        className=f"qs-panel-collapse qs-{panel}-collapse",
        title=label,
        **{
            "aria-label": label,
            "aria-expanded": str(not collapsed).lower(),
        },
    )
