"""The Boardroom Canvas — a real composition surface.

A page is a set of widget instances positioned on a 12-col × 8-row grid. Each
widget renders as an absolutely-positioned card the user can **select, drag,
resize, duplicate and delete**, and new widgets can be **added** from the palette.
Pointer interactions (move/resize/select) are handled by ``assets/studio_canvas.js``
which writes the resulting action to a hidden input; Dash commits it to the shared
document (``studio.page.document``) so the change feeds the export too.

This module is pure rendering; the live callbacks live in ``studio.authoring_app``.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from dash import dcc, html

from studio.page import document as D
from studio.page import render

# Palette: label → (icon, widget kind). The first row are governed primitives;
# the second are advanced widgets (placeholders until data-bound — shown honestly).
PALETTE = [
    ("bi-type-h1", "Headline", "headline"),
    ("bi-text-paragraph", "Text", "text"),
    ("bi-123", "KPI card", "kpi"),
    ("bi-distribute-horizontal", "KPI band", "kpiband"),
    ("bi-bar-chart-line", "Chart", "chart"),
    ("bi-table", "Table", "table"),
    ("bi-flag", "Recommendation", "reco"),
    ("bi-bullseye", "Opportunity matrix", "matrix"),
    ("bi-grid-3x3", "Portfolio heatmap", "heatmap"),
    ("bi-radar", "Risk radar", "radar"),
    ("bi-pie-chart", "Radial performance", "radial"),
    ("bi-bar-chart-steps", "Variance bridge", "bridge"),
    ("bi-calendar-range", "Action timeline", "timeline"),
    ("bi-chat-left-quote", "Executive callout", "callout"),
    ("bi-list-check", "Action tracker", "actions"),
    ("bi-dash-lg", "Divider", "divider"),
]
_KIND_ICON = {k: icon for icon, _lbl, k in PALETTE}
_PLACEHOLDER_KINDS = set()

COMPONENT_CATEGORIES = (
    "All",
    "Financial",
    "Customer",
    "Growth",
    "Risk",
    "Operations",
    "Market",
)

COMPONENT_TABS = (
    ("all", "All", ""),
    ("recommended", "Recommended", ""),
    ("mine", "My components", ""),
    ("governed", "Governed", "bi-patch-check"),
    ("recent", "Recently used", "bi-clock-history"),
)

# Each browser card maps to an existing governed widget kind. This keeps the
# visual library, editable canvas, and PowerPoint export on the same document.
COMPONENT_LIBRARY = (
    {
        "icon": "bi-bar-chart-steps",
        "name": "Variance bridge",
        "kind": "bridge",
        "category": "Financial",
        "caption": "Analyze drivers of change",
        "recommended": True,
        "governed": True,
        "recent": True,
    },
    {
        "icon": "bi-graph-up",
        "name": "Premium trend",
        "kind": "chart",
        "category": "Financial",
        "caption": "Track performance over time",
        "recommended": True,
        "governed": True,
        "recent": True,
    },
    {
        "icon": "bi-grid-3x3",
        "name": "Portfolio heatmap",
        "kind": "heatmap",
        "category": "Risk",
        "caption": "Heatmap by risk and return",
        "recommended": True,
        "governed": True,
    },
    {
        "icon": "bi-bullseye",
        "name": "Opportunity matrix",
        "kind": "matrix",
        "category": "Growth",
        "caption": "Prioritize opportunities",
        "recommended": True,
        "governed": True,
        "recent": True,
    },
    {
        "icon": "bi-radar",
        "name": "Risk radar",
        "kind": "radar",
        "category": "Risk",
        "caption": "Compare risk dimensions",
        "recommended": True,
        "governed": True,
    },
    {
        "icon": "bi-pie-chart",
        "name": "Pillar progress",
        "kind": "radial",
        "category": "Operations",
        "caption": "Track strategic progress",
        "governed": True,
    },
    {
        "icon": "bi-calendar-range",
        "name": "Action timeline",
        "kind": "timeline",
        "category": "Operations",
        "caption": "Plan initiatives over time",
        "recommended": True,
        "governed": True,
        "recent": True,
    },
    {
        "icon": "bi-table",
        "name": "Ranked table",
        "kind": "table",
        "category": "Market",
        "caption": "Rank accounts and segments",
        "recommended": True,
        "governed": True,
    },
    {
        "icon": "bi-distribute-horizontal",
        "name": "KPI scorecard",
        "kind": "kpiband",
        "category": "Financial",
        "caption": "Summarize QBR performance",
        "recommended": True,
        "governed": True,
    },
    {
        "icon": "bi-123",
        "name": "KPI with sparkline",
        "kind": "kpi",
        "category": "Customer",
        "caption": "Show a metric and trend",
        "governed": True,
    },
    {
        "icon": "bi-list-check",
        "name": "Decision tracker",
        "kind": "actions",
        "category": "Operations",
        "caption": "Track owners and due dates",
        "recommended": True,
        "governed": True,
        "mine": True,
    },
    {
        "icon": "bi-chat-left-quote",
        "name": "Executive callout",
        "kind": "callout",
        "category": "Customer",
        "caption": "Frame the boardroom takeaway",
        "governed": True,
        "mine": True,
    },
    {
        "icon": "bi-flag",
        "name": "Recommendation",
        "kind": "reco",
        "category": "Growth",
        "caption": "State the decision required",
        "governed": True,
        "mine": True,
    },
    {
        "icon": "bi-text-paragraph",
        "name": "Commentary",
        "kind": "text",
        "category": "Customer",
        "caption": "Explain what changed and why",
        "governed": True,
        "mine": True,
    },
    {
        "icon": "bi-type-h1",
        "name": "Action title",
        "kind": "headline",
        "category": "Market",
        "caption": "Lead with the QBR conclusion",
        "governed": True,
    },
    {
        "icon": "bi-dash-lg",
        "name": "Section divider",
        "kind": "divider",
        "category": "Market",
        "caption": "Structure the page narrative",
        "governed": True,
    },
)


def _pct(n: int, total: int) -> str:
    return f"{n / total * 100:.4f}%"


# ── per-kind widget content ──────────────────────────────────────────────────


def _headline(p: Mapping[str, Any], hero: bool) -> Any:
    eyebrow = p.get("eyebrow", "")
    cls = "qs-cv-headline" + (" hero" if hero or p.get("hero") else "")
    return html.Div(
        [
            html.Div(eyebrow, className="qs-cv-eyebrow") if eyebrow else None,
            html.Div(p.get("text", ""), className="qs-cv-title"),
            html.Div(p.get("subtitle", ""), className="qs-cv-sub") if p.get("subtitle") else None,
        ],
        className=cls,
    )


def _text(p: Mapping[str, Any]) -> Any:
    if p.get("swot"):
        s = p["swot"]
        quads = [("Strengths", s.get("strengths", []), "good"), ("Weaknesses", s.get("weaknesses", []), "danger"),
                 ("Opportunities", s.get("opportunities", []), "blue"), ("Threats", s.get("threats", []), "warn")]
        return html.Div(
            [html.Div([html.Div(t, className=f"qs-cv-swot-h {tone}"),
                       html.Ul([html.Li(b) for b in items[:4]], className="qs-cv-swot-l")], className="qs-cv-swot-q")
             for t, items, tone in quads],
            className="qs-cv-swot",
        )
    items = []
    for pt in list(p.get("points", [])):
        tone = pt.get("tone", "neutral")
        label = (pt.get("label") or "").strip()
        items.append(html.Div([
            html.Span(className=f"qs-cv-dot {tone}"),
            html.Span([html.B(label + " ") if label else None, pt.get("text", "")]),
        ], className="qs-cv-point"))
    return html.Div(
        [html.Div(p.get("heading", ""), className="qs-cv-h") if p.get("heading") else None,
         html.Div(items, className="qs-cv-points")],
        className="qs-cv-text",
    )


def _kpiband(p: Mapping[str, Any]) -> Any:
    cells = []
    for k in list(p.get("items", []))[:6]:
        tone = k.get("tone", "neutral")
        cells.append(html.Div([
            html.Div(str(k.get("label", "")).upper(), className="qs-cv-kpi-l"),
            html.Div(str(k.get("value", "")), className="qs-cv-kpi-v"),
            html.Div(k.get("delta", "") or "", className=f"qs-cv-kpi-d {tone}"),
            html.Div(
                render.line_chart(
                    k.get("trend_labels", []),
                    k.get("trend_values", []),
                    height=42,
                    compact=True,
                ),
                className="qs-cv-kpi-spark",
            )
            if k.get("trend_values")
            else None,
        ], className="qs-cv-kpi"))
    return html.Div(cells, className="qs-cv-kpiband")


def _chart(p: Mapping[str, Any]) -> Any:
    labels, values = list(p.get("labels", [])), list(p.get("values", []))
    if not values:
        return _empty("Bind data to this chart")
    kind = p.get("chart", "bar")
    fig = (render.donut(labels, values, height=180) if kind == "donut"
           else render.waterfall(labels, values, height=180) if kind == "waterfall"
           else render.line_chart(labels, values, height=180) if kind == "line"
           else render.bar_chart(labels, values, height=180))
    tag = html.Span("sample", className="qs-cv-sample") if p.get("placeholder") else None
    title = (
        html.Div(p.get("title", ""), className="qs-cv-chart-title")
        if p.get("title")
        else None
    )
    return html.Div([tag, title, fig], className="qs-cv-chart")


def _table(p: Mapping[str, Any]) -> Any:
    rows, cols = list(p.get("rows", [])), list(p.get("columns", []))
    if not rows or not cols:
        return _empty("Bind data to this table")
    numeric_max = {
        col["key"]: max(
            [float(row.get(col["key"]) or 0) for row in rows if isinstance(row.get(col["key"]), (int, float))]
            or [1]
        )
        for col in cols
        if col.get("bar")
    }
    head = html.Thead(html.Tr([html.Th(col["label"]) for col in cols]))
    body = []
    for row in rows:
        cells = []
        for col in cols:
            value = row.get(col["key"], "")
            if col.get("bar") and isinstance(value, (int, float)):
                width = max(3, float(value) / numeric_max[col["key"]] * 100)
                content = html.Div(
                    [
                        html.Div(className="qs-cell-bar", style={"width": f"{width:.1f}%"}),
                        html.Span(f"{value:,.0f}", className="qs-cell-value"),
                    ],
                    className="qs-cell-bar-wrap",
                )
            elif col.get("status"):
                tone = str(value).lower().replace(" ", "-")
                content = html.Span(
                    [html.Span(className=f"qs-status-dot {tone}"), str(value)],
                    className="qs-table-status",
                )
            else:
                content = value
            cells.append(html.Td(content, className=col.get("align", "left")))
        body.append(html.Tr(cells))
    return html.Div(
        html.Table([head, html.Tbody(body)], className="qs-qbr-table"),
        className="qs-cv-tablewrap",
    )


def _advanced_graph(p: Mapping[str, Any], kind: str) -> Any:
    title = html.Div(p.get("title", ""), className="qs-cv-chart-title") if p.get("title") else None
    if kind == "matrix":
        graph = render.scatter_bubbles(p.get("points", []), height=220)
    elif kind == "heatmap":
        graph = render.heatmap(p.get("rows", []), p.get("columns", []), p.get("values", []), height=220)
    elif kind == "radar":
        graph = render.radar_chart(p.get("labels", []), p.get("values", []), height=220)
    elif kind == "radial":
        graph = render.radial_chart(p.get("labels", []), p.get("values", []), height=220)
    elif kind == "bridge":
        graph = render.waterfall(
            p.get("labels", []),
            p.get("values", []),
            height=220,
            total_label=p.get("total_label", "Total"),
        )
    else:
        graph = render.gantt_chart(p.get("tasks", []), height=220)
    return html.Div(
        [title, html.Div(graph, className="qs-cv-advanced-plot")],
        className=f"qs-cv-advanced qs-cv-{kind}",
    )


def _callout(p: Mapping[str, Any]) -> Any:
    return html.Div(
        [
            html.Div(p.get("label", "EXECUTIVE TAKEAWAY"), className="qs-callout-label"),
            html.Div(p.get("title", ""), className="qs-callout-title"),
            html.Div(p.get("body", ""), className="qs-callout-body"),
        ],
        className=f"qs-cv-callout tone-{p.get('tone', 'blue')}",
    )


def _actions(p: Mapping[str, Any]) -> Any:
    rows = []
    for item in p.get("items", []):
        status = str(item.get("status", "planned")).lower().replace(" ", "-")
        rows.append(
            html.Div(
                [
                    html.Span(className=f"qs-status-dot {status}"),
                    html.Span(item.get("action", ""), className="qs-action-text"),
                    html.Span(item.get("owner", ""), className="qs-action-owner"),
                    html.Span(item.get("due", ""), className="qs-action-due"),
                ],
                className="qs-action-row",
            )
        )
    return html.Div(
        [html.Div(p.get("title", "Priority actions"), className="qs-cv-h"), *rows],
        className="qs-cv-actions",
    )


def _reco(p: Mapping[str, Any]) -> Any:
    meta = [x for x in (p.get("owner"), p.get("due"),
                        f"{p.get('confidence')} confidence" if p.get("confidence") else None) if x]
    return html.Div([
        html.Div([html.I(className="bi bi-flag-fill"), html.Span("RECOMMENDATION", className="qs-cv-reco-l"),
                  html.Span(p.get("text", ""), className="qs-cv-reco-t")], className="qs-cv-reco-main"),
        html.Div("  ·  ".join(meta), className="qs-cv-reco-meta") if meta else None,
    ], className="qs-cv-reco")


def _placeholder(kind: str, p: Mapping[str, Any]) -> Any:
    return html.Div([
        html.I(className=f"bi {_KIND_ICON.get(kind, 'bi-grid')}"),
        html.Div(p.get("label", D.WIDGET_DEFAULTS.get(kind, {}).get("label", kind)), className="qs-cv-ph-name"),
        html.Div("Advanced widget — data binding coming", className="qs-cv-ph-note"),
    ], className="qs-cv-placeholder")


def _divider(p: Mapping[str, Any]) -> Any:
    return html.Div(html.Div(p.get("text", ""), className="qs-cv-div-label"), className="qs-cv-divider")


def _empty(msg: str) -> Any:
    return html.Div([html.I(className="bi bi-plus-square-dashed"), msg], className="qs-cv-empty")


def _content(w: Mapping[str, Any]) -> Any:
    kind, p = w["kind"], w.get("props", {})
    if kind == "headline":
        return _headline(p, p.get("hero", False))
    if kind == "text":
        return _text(p)
    if kind in ("kpiband", "kpi"):
        return _kpiband(p)
    if kind == "chart":
        return _chart(p)
    if kind == "table":
        return _table(p)
    if kind == "reco":
        return _reco(p)
    if kind in {"matrix", "heatmap", "radar", "radial", "bridge", "timeline"}:
        return _advanced_graph(p, kind)
    if kind == "callout":
        return _callout(p)
    if kind == "actions":
        return _actions(p)
    if kind == "divider":
        return _divider(p)
    if kind == "image":
        return _empty("Image placeholder")
    return _empty(kind)


# ── widget card + surface ─────────────────────────────────────────────────────

_HANDLES = ["nw", "ne", "sw", "se", "e", "s"]


def _widget_card(w: Mapping[str, Any], selected: bool, *, interactive: bool = True) -> html.Div:
    props = w.get("props", {}) or {}
    style = {
        "left": _pct(w["x"], D.GRID_COLS), "top": _pct(w["y"], D.GRID_ROWS),
        "width": _pct(w["w"], D.GRID_COLS), "height": _pct(w["h"], D.GRID_ROWS),
    }
    style_classes = []
    if props.get("background_color"):
        style["backgroundColor"] = props["background_color"]
        style_classes.append("qs-cv-bg-custom")
    if props.get("font_family"):
        style["--qs-widget-font-family"] = props["font_family"]
        style_classes.append("qs-cv-font-custom")
    if props.get("font_size"):
        style["--qs-widget-font-size"] = f"{int(props['font_size'])}px"
        style_classes.append("qs-cv-size-custom")
    if props.get("font_color"):
        style["--qs-widget-font-color"] = props["font_color"]
        style_classes.append("qs-cv-color-custom")
    for role, role_style in (props.get("text_styles") or {}).items():
        if role_style.get("font_family"):
            style[f"--qs-{role}-font-family"] = role_style["font_family"]
        if role_style.get("font_size"):
            style[f"--qs-{role}-font-size"] = f"{int(role_style['font_size'])}px"
        if role_style.get("font_color"):
            style[f"--qs-{role}-font-color"] = role_style["font_color"]
        style_classes.append(f"qs-cv-role-{role}")
    children = [html.Div(_content(w), className="qs-cv-body")]
    if interactive:
        children.insert(
            0,
            html.Div(
                [
                    html.I(className=f"bi {_KIND_ICON.get(w['kind'], 'bi-app')}"),
                    html.Span(
                        D.WIDGET_DEFAULTS.get(w["kind"], {}).get("label", w["kind"]),
                        className="qs-cv-tag-name",
                    ),
                ],
                className="qs-cv-tag",
            ),
        )
    if selected and interactive:
        children += [html.Div(className=f"qs-cv-handle {h}", **{"data-h": h}) for h in _HANDLES]
    attrs = (
        {
            "data-wid": w["id"],
            "data-x": w["x"],
            "data-y": w["y"],
            "data-w": w["w"],
            "data-h": w["h"],
        }
        if interactive
        else {}
    )
    return html.Div(
        children,
        className=(
            "qs-cv-widget"
            + (" selected" if selected else "")
            + ("" if interactive else " qs-cv-preview-widget")
            + (f" {' '.join(style_classes)}" if style_classes else "")
        ),
        style=style,
        **attrs,
    )


def _surface_class(base: str, layout: str, accent: str) -> str:
    suffix = f" layout-{layout}" if layout else ""
    suffix += f" accent-{accent}" if accent else ""
    return base + suffix


def canvas_surface(
    widgets: List[Mapping[str, Any]],
    selected_wid: Optional[str],
    *,
    layout: str = "",
    accent: str = "",
    page_style: Optional[Mapping[str, Any]] = None,
) -> html.Div:
    """The editable 16:9 grid with all widget cards (driven by studio_canvas.js)."""
    cards = [_widget_card(w, w["id"] == selected_wid) for w in widgets]
    return html.Div(
        [
            html.Div(cards, className="qs-cv-layer", id="qs-cv-layer"),
        ],
        className=_surface_class("qs-cv-surface", layout, accent),
        style={"backgroundColor": (page_style or {}).get("background_color")}
        if (page_style or {}).get("background_color")
        else None,
        id="qs-cv-surface",
        **{"data-cols": D.GRID_COLS, "data-rows": D.GRID_ROWS},
    )


def thumbnail_surface(
    widgets: List[Mapping[str, Any]],
    *,
    layout: str = "",
    accent: str = "",
    page_style: Optional[Mapping[str, Any]] = None,
) -> html.Div:
    """Read-only miniature of the real canvas without duplicate DOM ids."""
    return html.Div(
        [_widget_card(w, False, interactive=False) for w in widgets],
        className=_surface_class("qs-pg-preview-surface", layout, accent),
        style={"backgroundColor": (page_style or {}).get("background_color")}
        if (page_style or {}).get("background_color")
        else None,
    )


def _legacy_palette() -> html.Div:
    """Component library — each item ADDS a real widget to the current page."""
    cards = [
        html.Button(
            [html.I(className=f"bi {icon}"), html.Span(label, className="qs-comp-name")],
            id={"type": "qs-addw", "kind": kind},
            className="qs-comp-card" + (" adv" if kind in _PLACEHOLDER_KINDS else ""),
        )
        for icon, label, kind in PALETTE
    ]
    return html.Div(
        [
            html.Div([html.I(className="bi bi-grid-1x2"), "Component library",
                      html.Span("click to add", className="qs-comp-hint")], className="qs-comp-title"),
            html.Div(cards, className="qs-comp-grid"),
        ],
        className="qs-comp-lib",
    )


def _library_components(
    category: str = "all",
    tab: str = "all",
    search: str = "",
) -> List[Mapping[str, Any]]:
    """Return the visible library cards for the active browser controls."""
    category_key = str(category or "all").strip().lower()
    tab_key = str(tab or "all").strip().lower()
    query = str(search or "").strip().lower()
    visible: List[Mapping[str, Any]] = []
    for item in COMPONENT_LIBRARY:
        if category_key != "all" and item["category"].lower() != category_key:
            continue
        if tab_key != "all" and not item.get(tab_key, False):
            continue
        haystack = " ".join(
            (item["name"], item["caption"], item["category"], item["kind"])
        ).lower()
        if query and query not in haystack:
            continue
        visible.append(item)
    return visible


def _library_preview(item: Mapping[str, Any]) -> html.Div:
    """Render a compact version of the real governed widget, not a placeholder."""
    widget = {
        "kind": item["kind"],
        "props": D._starter_props(item["kind"], []),
    }
    return html.Div(
        html.Div(_content(widget), className="qs-lib-preview-content"),
        className=f"qs-lib-preview qs-lib-preview-{item['kind']}",
    )


def palette(
    *,
    category: str = "all",
    tab: str = "all",
    view: str = "grid",
    search: str = "",
    collapsed: bool = False,
) -> html.Div:
    """Screenshot-aligned component browser backed by real add-widget actions."""
    category_key = str(category or "all").lower()
    tab_key = str(tab or "all").lower()
    view_key = "list" if str(view or "").lower() == "list" else "grid"
    items = _library_components(category_key, tab_key, search)
    cards = [
        html.Div(
            [
                html.Div(
                    [
                        html.Span(item["name"], className="qs-lib-card-name"),
                        html.Span(item["category"], className="qs-lib-card-category"),
                    ],
                    className="qs-lib-card-head",
                ),
                _library_preview(item),
                html.Div(
                    [
                        html.Span(item["caption"], className="qs-lib-caption"),
                        html.I(
                            className="bi bi-patch-check-fill qs-lib-governed",
                            title="Governed component",
                        )
                        if item.get("governed")
                        else html.I(className=f"bi {item['icon']} qs-lib-card-icon"),
                    ],
                    className="qs-lib-card-foot",
                ),
            ],
            id={"type": "qs-addw", "kind": item["kind"]},
            n_clicks=0,
            role="button",
            tabIndex=0,
            title=f"Add {item['name']}",
            className="qs-lib-card",
        )
        for item in items
    ]
    categories = [
        html.Button(
            [
                html.Span(name),
                html.I(className="bi bi-chevron-right") if name != "All" else None,
            ],
            id={"type": "qs-libcat", "category": name.lower()},
            className="qs-lib-category" + (
                " active" if name.lower() == category_key else ""
            ),
        )
        for name in COMPONENT_CATEGORIES
    ]
    tabs = [
        html.Button(
            [
                html.I(className=f"bi {icon}") if icon else None,
                label,
            ],
            id={"type": "qs-libtab", "tab": key},
            className="qs-lib-tab" + (" active" if key == tab_key else ""),
        )
        for key, label, icon in COMPONENT_TABS
    ]
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [html.I(className="bi bi-grid-1x2"), "Component library"],
                        className="qs-comp-title",
                    ),
                    html.Div(tabs, className="qs-lib-tabs"),
                    html.Div(
                        [
                            html.Button(
                                [html.I(className="bi bi-grid"), "Grid view"],
                                id={"type": "qs-libview", "view": "grid"},
                                className="qs-lib-view-btn"
                                + (" active" if view_key == "grid" else ""),
                            ),
                            html.Button(
                                [html.I(className="bi bi-list"), "List view"],
                                id={"type": "qs-libview", "view": "list"},
                                className="qs-lib-view-btn"
                                + (" active" if view_key == "list" else ""),
                            ),
                        ],
                        className="qs-lib-view",
                    ),
                ],
                className="qs-lib-header",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            dcc.Input(
                                id="qs-lib-search",
                                value=search or "",
                                type="search",
                                debounce=True,
                                placeholder="Search components...",
                                className="qs-lib-search",
                            ),
                            html.Div("Categories", className="qs-lib-category-title"),
                            html.Div(categories, className="qs-lib-categories"),
                        ],
                        className="qs-lib-sidebar",
                    ),
                    html.Div(
                        cards
                        if cards
                        else html.Div(
                            [
                                html.I(className="bi bi-search"),
                                html.Span("No components match these filters"),
                            ],
                            className="qs-lib-empty",
                        ),
                        className=f"qs-comp-grid qs-lib-{view_key}",
                    ),
                ],
                className="qs-lib-body",
            ),
        ],
        className="qs-comp-lib" + (" is-collapsed" if collapsed else ""),
    )
