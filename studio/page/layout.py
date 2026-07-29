"""The Studio page shell — top bar, form rail, results canvas.

Pure layout. The live Dash callbacks (later step) populate the dropdown options
and the results canvas; this module defines the gorgeous, static structure and the
component ids those callbacks will target.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Sequence

import dash_bootstrap_components as dbc
from dash import dcc, html

# The analysis pages, in nav order (Overall → Product → Country → Market → Rank →
# Peer). Country drills into product/industry/market/rank for each country.
PAGES: List[Mapping[str, str]] = [
    {"id": "overall", "label": "Overall", "icon": "bi-grid-1x2"},
    {"id": "product", "label": "Product", "icon": "bi-box-seam"},
    {"id": "country", "label": "Country", "icon": "bi-globe2"},
    {"id": "market", "label": "Market", "icon": "bi-pie-chart"},
    {"id": "rank", "label": "Rank", "icon": "bi-trophy"},
    {"id": "peer", "label": "Peer", "icon": "bi-people"},
]

# Every categorical column offered as a filter (GPR scope). Survey scope swaps in
# its own set at callback time; shown here is the premium vocabulary.
GPR_FILTERS: List[Mapping[str, Any]] = [
    {"id": "region", "label": "Region", "ph": "All"},
    {"id": "country", "label": "Country", "ph": "All", "multi": True},
    {"id": "carrier", "label": "Carrier", "ph": "Select"},
    {"id": "year", "label": "Year", "ph": "Latest", "multi": True},
    {"id": "product_line", "label": "Product Line", "ph": "All", "multi": True},
    {"id": "business_line", "label": "Business Line", "ph": "All", "multi": True},
    {"id": "cover_line", "label": "Cover Line", "ph": "All", "multi": True},
    {"id": "industry", "label": "Industry", "ph": "All", "multi": True},
    {"id": "sub_industry", "label": "Sub-Industry", "ph": "All"},
    {"id": "client_segment", "label": "Client Segment", "ph": "All"},
]

# Dimensions a user can break results down by (group-by).
BREAKDOWNS: List[Mapping[str, str]] = [
    {"label": "Industry", "value": "SIC_Major_Class"},
    {"label": "Product Line", "value": "Product_Line"},
    {"label": "Business Line", "value": "Business_Line"},
    {"label": "Cover Line", "value": "Cover_Line"},
    {"label": "Client Segment", "value": "Client_Segment"},
    {"label": "Country", "value": "Country"},
    {"label": "Region", "value": "Region"},
]


def _report_type() -> html.Div:
    # Executive summary was removed as a report choice — Full QBR is the one
    # deliverable. The control stays a RadioItems so every callback reading
    # ``studio-report-type`` keeps working unchanged.
    return html.Div(
        [
            html.Div("REPORT", className="studio-field-label"),
            dcc.RadioItems(
                id="studio-report-type",
                options=[{"label": "Full QBR", "value": "qbr"}],
                value="qbr",
                className="studio-report-radio",
                inputClassName="studio-report-input",
                labelClassName="studio-report-label",
            ),
        ],
        className="studio-field",
    )


def _scope_toggle() -> html.Div:
    return html.Div(
        [
            html.Div("DATA SCOPE", className="studio-field-label"),
            html.Div(
                [
                    html.Button(
                        [html.I(className="bi bi-cash-stack"), "Premium"],
                        className="studio-scope-chip active",
                        id="studio-scope-gpr",
                    ),
                    html.Button(
                        [html.I(className="bi bi-clipboard-data"), "Survey"],
                        className="studio-scope-chip",
                        id="studio-scope-survey",
                    ),
                ],
                className="studio-scope-row",
            ),
        ],
        className="studio-field",
    )


def _filter_grid(
    options: Mapping[str, Any] | None = None, values: Mapping[str, Any] | None = None
) -> html.Div:
    options = options or {}
    values = values or {}
    cells = [
        html.Div(
            [
                html.Div(f["label"], className="studio-field-label sm"),
                dcc.Dropdown(
                    id={"type": "studio-filter", "col": f["id"]},
                    options=options.get(f["id"], []),
                    value=values.get(f["id"]),
                    placeholder=f["ph"],
                    multi=f.get("multi", False),
                    className="studio-dd sm",
                ),
            ],
            className="studio-field",
        )
        for f in GPR_FILTERS
    ]
    return html.Div(
        [
            html.Div("FILTERS", className="studio-field-label"),
            dcc.Loading(
                html.Div(cells, className="studio-filter-grid"),
                type="dot",
                color="#1f5fbf",
                className="studio-loading",
            ),
        ],
        className="studio-field",
    )


def _breakdown() -> html.Div:
    return html.Div(
        [
            html.Div("BREAK DOWN BY", className="studio-field-label"),
            dcc.Dropdown(
                id="studio-breakdown",
                options=[{"label": b["label"], "value": b["value"]} for b in BREAKDOWNS],
                value=["Product_Line", "SIC_Major_Class"],
                multi=True,
                placeholder="Choose dimensions",
                className="studio-dd sm",
            ),
        ],
        className="studio-field",
    )


def _analyses(groups: Sequence[Mapping[str, Any]]) -> html.Div:
    blocks = []
    for g in groups:
        items = [
            dbc.Checkbox(
                id={"type": "studio-cut", "name": c["name"]},
                label=c["label"],
                value=c.get("default", False),
                class_name="studio-check",
            )
            for c in g["cuts"]
        ]
        blocks.append(
            html.Div(
                [
                    html.Div(g["label"], className="studio-analyses-group"),
                    html.Div(g.get("note", ""), className="studio-analyses-note")
                    if g.get("note")
                    else None,
                    html.Div(items, className="studio-analyses-items"),
                ]
            )
        )
    return html.Div(
        [html.Div("ANALYSES", className="studio-field-label"), *blocks],
        className="studio-field",
    )


def _peers_panel() -> html.Div:
    """Peer-set chooser, used when 'Peer average comparison' is ticked.

    Existing peers come from the Peers table for the chosen carrier; if none exist
    the message tells the user to pick custom peers."""
    return html.Div(
        [
            html.Div("PEER SET", className="studio-field-label"),
            html.Div(
                "Used when “Peer average comparison” is ticked.",
                className="studio-analyses-note",
            ),
            dcc.RadioItems(
                id="studio-peer-mode",
                options=[
                    {"label": "Existing peers", "value": "existing"},
                    {"label": "Custom peers", "value": "custom"},
                ],
                value="existing",
                className="studio-report-radio",
                inputClassName="studio-report-input",
                labelClassName="studio-report-label",
            ),
            html.Div(id="studio-peer-msg", className="studio-peer-msg"),
            dcc.Dropdown(
                id="studio-peer-custom",
                options=[],
                value=[],
                multi=True,
                placeholder="Select custom peers",
                className="studio-dd sm",
            ),
        ],
        className="studio-field",
    )


def form_rail(
    cut_groups: Sequence[Mapping[str, Any]],
    *,
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
) -> html.Aside:
    return html.Aside(
        [
            html.Div(
                [
                    html.Div(
                        [html.I(className="bi bi-sliders2"), "Build your view"],
                        className="studio-rail-title",
                    ),
                    html.P(
                        "Pick scope, filters and breakdowns. Everything is computed deterministically.",
                        className="studio-rail-sub",
                    ),
                ],
                className="studio-rail-head",
            ),
            _report_type(),
            _scope_toggle(),
            _filter_grid(filter_options, filter_values),
            _breakdown(),
            _analyses(cut_groups),
            _peers_panel(),
            html.Button(
                [html.I(className="bi bi-stars"), "Generate analysis"],
                id="studio-generate",
                className="studio-generate-btn",
            ),
        ],
        className="studio-rail",
    )


def results_rail(active: str = "overall") -> html.Div:
    pills = [
        html.Button(
            [html.I(className=f"bi {p['icon']}"), p["label"]],
            className=f"studio-page-pill{' active' if p['id'] == active else ''}",
            id={"type": "studio-page", "page": p["id"]},
        )
        for p in PAGES
    ]
    return html.Div(pills, className="studio-page-rail")


def topbar() -> html.Header:
    return html.Header(
        [
            html.Div(
                [
                    html.Div("M", className="studio-logo-mark"),
                    html.Div(
                        [
                            html.Div("ICG Virtual Analyst", className="studio-brand-main"),
                            html.Div("Boardroom Studio", className="studio-brand-sub"),
                        ]
                    ),
                ],
                className="studio-brand",
            ),
            html.Div(
                [
                    html.Span("Strictly Private & Confidential", className="studio-confidential"),
                    html.Div("JV", className="studio-avatar"),
                ],
                className="studio-topbar-right",
            ),
        ],
        className="studio-topbar",
    )


def footer() -> html.Div:
    return html.Div(
        [
            html.Span("Source — GPR, Carrier Survey"),
            html.Span("•", className="studio-foot-dot"),
            html.Span("Marsh ICG — Strictly Private & Confidential"),
            html.Span("•", className="studio-foot-dot"),
            html.Span("Figures computed deterministically; commentary verified against source facts."),
        ],
        className="studio-footer",
    )


def studio_shell(
    content: Any,
    *,
    cut_groups: Sequence[Mapping[str, Any]],
    active: str = "overall",
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
    page_rail: bool = True,
    show_footer: bool = True,
) -> html.Div:
    main_children: list[Any] = []
    if page_rail:
        main_children.append(results_rail(active))
    main_children.append(
        dcc.Loading(
            html.Div(content, id="studio-canvas"),
            type="default",
            color="#1f5fbf",
            className="studio-loading studio-canvas-loading",
        )
    )
    if show_footer:
        main_children.append(footer())
    return html.Div(
        [
            # Fires once after first paint so the shell appears instantly and the
            # expensive filter-option scans run lazily (with a spinner), never at import.
            dcc.Interval(id="studio-boot", interval=120, max_intervals=1),
            topbar(),
            html.Div(
                [
                    form_rail(cut_groups, filter_options=filter_options, filter_values=filter_values),
                    html.Main(main_children, className="studio-main"),
                ],
                className="studio-body",
            ),
        ],
        className="studio-root",
    )
