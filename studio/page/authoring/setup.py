"""Setup mode — the real build form, wired to the DB.

``setup_body`` composes the scope/filters, report, template, audience, sections,
peers and AI-assist sections plus the live scope-preview aside and Generate button.
The scope-preview cards and template-sections panel are refreshed by app callbacks.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Tuple

import dash_bootstrap_components as dbc
from dash import dcc, html

from studio.page.layout import (
    _filter_grid,
    _peers_panel,
    _report_type,
    _scope_toggle,
)


def _setup_section(icon: str, title: str, subtitle: str, children: Any, *, span: bool = False) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className=f"bi {icon}"), title], className="qs-sec-title"),
                    html.Div(subtitle, className="qs-sec-sub") if subtitle else None,
                ],
                className="qs-sec-head",
            ),
            html.Div(children, className="qs-sec-body"),
        ],
        className="qs-setup-section" + (" span" if span else ""),
    )


def _radio_field(label: str, cid: str, options: Sequence[Mapping[str, str]], value: str) -> html.Div:
    return html.Div(
        [
            html.Div(label, className="studio-field-label"),
            dcc.RadioItems(
                id=cid, options=list(options), value=value,
                className="studio-report-radio", inputClassName="studio-report-input",
                labelClassName="studio-report-label",
            ),
        ],
        className="studio-field",
    )


def _audience_length() -> html.Div:
    return html.Div(
        [
            _radio_field("AUDIENCE", "studio-audience", [
                {"label": "Executive", "value": "executive"},
                {"label": "Deal team", "value": "deal_team"},
                {"label": "Board", "value": "board"},
            ], "executive"),
            # Commentary voice — words, not meeting minutes. Passed to the deck when the
            # qualitative prose is written (studio.template_fill.commentary).
            _radio_field("COMMENTARY STYLE", "studio-commentary-style", [
                {"label": "Concise", "value": "concise"},
                {"label": "Balanced", "value": "balanced"},
                {"label": "Detailed", "value": "detailed"},
            ], "balanced"),
        ],
        className="qs-sec-grid cols-2",
    )


def _ai_control() -> html.Div:
    return html.Div(
        [
            dbc.Checkbox(
                id="studio-ai-toggle",
                label="AI-assisted narrative & layout",
                value=False,
                class_name="studio-check qs-ai-check",
            ),
            html.Div(
                "Sharper commentary and slide layout — every number is checked against the "
                "source facts, and it falls back to the deterministic deck when AI is unavailable.",
                className="qs-ai-note",
            ),
        ],
        className="qs-ai-field",
    )


def scope_preview_empty(message: str = "Pick a carrier to preview this scope.") -> html.Div:
    return html.Div(
        [html.I(className="bi bi-binoculars"), html.Span(message)],
        className="qs-preview-empty",
    )


def scope_preview_card(items: Sequence[Mapping[str, Any]]) -> html.Div:
    """Render the live scope-preview KPI tiles (computed by the app callback)."""
    if not items:
        return scope_preview_empty()
    tiles = [
        html.Div(
            [
                html.Div(str(it["label"]).upper(), className="qs-prev-label"),
                html.Div(str(it["value"]), className="qs-prev-value"),
                html.Div(it.get("sub", ""), className="qs-prev-sub") if it.get("sub") else None,
            ],
            className="qs-prev-tile",
        )
        for it in items
    ]
    return html.Div(tiles, className="qs-prev-grid")


def _scope_preview() -> html.Div:
    return html.Div(
        [
            html.Div([html.I(className="bi bi-eye"), "Scope preview"], className="qs-preview-head"),
            html.P("Live headline figures for the current filters.", className="qs-preview-note"),
            dcc.Loading(
                html.Div(scope_preview_empty(), id="studio-scope-preview"),
                type="dot", color="#1f5fbf", className="studio-loading",
            ),
        ],
        className="qs-scope-preview",
    )


# Assembly-scope choices (Setup "Scope" dropdown). Value = the axis set to assemble;
# "all" is the full deck (overall + product + country). Only axes with a registered
# template are offered.
_SCOPE_LABELS = {
    "all": "All — overall + product + country",
    "overall": "Overall only",
    "product": "Product pages",
    "country": "Country pages",
}


def _scope_options() -> list:
    """The scope choices, gated to the axes whose fixed template is registered."""
    from studio.template_fill.binding_map import available

    axes = set(available())
    opts = [{"label": _SCOPE_LABELS["all"], "value": "all"}]
    for axis in ("overall", "product", "country"):
        if axis in axes:
            opts.append({"label": _SCOPE_LABELS[axis], "value": axis})
    return opts


def _template_control() -> html.Div:
    """Assembly scope — which fixed sub-decks to build and merge.

    Templates are a fixed, author-made set (``overall`` / ``product`` / ``country``), split
    by axis and merged per selection. This dropdown picks how much of the deck to assemble:
    everything, or just the overall / product / country pages.
    """
    options = _scope_options()
    return html.Div(
        [
            html.Div("SCOPE", className="studio-field-label"),
            dcc.Dropdown(
                id="studio-template",
                options=options,
                value="all",
                clearable=False,
                className="studio-dd",
            ),
        ],
        className="studio-field",
    )


# Section type → (friendly label, icon, how it's handled) for the template preview.
_SECTION_META: Mapping[str, Tuple[str, str, str]] = {
    "summary": ("Executive summary", "bi-grid-1x2", ""),
    "highlights": ("Highlights", "bi-stars", "Commentary auto-written"),
    "trading_summary": ("Trading summary", "bi-chat-square-text", "Commentary auto-written"),
    "portfolio": ("Portfolio analysis", "bi-pie-chart", ""),
    "feedback": ("Feedback", "bi-clipboard-heart", "Qualitative — filled by hand"),
    "ranking": ("Portfolio & ranking", "bi-trophy", "Chart edited in PowerPoint"),
    "growth": ("Growth quadrant", "bi-bullseye", "Chart edited in PowerPoint"),
    "swot": ("SWOT", "bi-grid-3x3", "Commentary auto-written"),
    "country_divider": ("Country divider", "bi-signpost-split", ""),
    "breakdown": ("Carrier breakdown", "bi-table", "Per-product, per-country"),
    "carrier_title": ("Section title", "bi-bookmark", ""),
    "other": ("Other", "bi-file-earmark", ""),
}


def template_sections_panel(template_path: Optional[str] = None) -> html.Div:
    """The sections THIS template will produce — selection driven by the deck itself,
    not a static list. Grouped by section type in reading order, with page counts and
    a note on how each is filled (data, commentary, or manual chart)."""
    from studio.template_fill.registry import active_template_path, derive_manifest
    from studio.template_fill.sections import classify_sections

    path = template_path or active_template_path()
    try:
        template, _ = derive_manifest(path)
        secs = classify_sections(template)
    except Exception:  # noqa: BLE001 — a missing/odd template must not break Setup
        return html.Div(
            [html.I(className="bi bi-exclamation-circle"), " Pick a template to see its sections."],
            className="qs-preview-empty",
        )
    order: List[str] = []
    counts: dict = {}
    for idx in sorted(secs):
        key = secs[idx].value
        if key not in counts:
            order.append(key)
        counts[key] = counts.get(key, 0) + 1
    rows = []
    for key in order:
        label, icon, note = _SECTION_META.get(key, (key.title(), "bi-file-earmark", ""))
        n = counts[key]
        rows.append(
            html.Div(
                [
                    html.I(className=f"bi {icon} qs-tsec-icon"),
                    html.Div(
                        [
                            html.Div(label, className="qs-tsec-label"),
                            html.Div(note, className="qs-tsec-note") if note else None,
                        ],
                        className="qs-tsec-text",
                    ),
                    html.Span(f"{n} page{'s' if n > 1 else ''}", className="qs-tsec-count"),
                ],
                className="qs-tsec-row",
            )
        )
    total = len(secs)
    return html.Div(
        [
            html.Div(
                [html.Span(f"{total} pages", className="qs-tsec-total"),
                 html.Span(f"{len(order)} section types", className="qs-tsec-total alt")],
                className="qs-tsec-summary",
            ),
            html.Div(rows, className="qs-tsec-list"),
        ],
        className="qs-tsec",
    )


def setup_body(
    cut_groups: Sequence[Mapping[str, Any]],
    *,
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
) -> html.Div:
    sections = html.Div(
        [
            _setup_section(
                "bi-funnel", "Scope & filters",
                "Client, period and every cut — each list narrows to what the selection above it writes in.",
                html.Div([_scope_toggle(), _filter_grid(filter_options, filter_values)], className="qs-sec-stack"),
                span=True,
            ),
            _setup_section(
                "bi-diagram-3", "Report & scope",
                "Report type and how much of the deck to assemble.",
                html.Div([_report_type(), _template_control()], className="qs-sec-grid cols-2"),
            ),
            _setup_section(
                "bi-easel2", "Audience & commentary",
                "Audience tunes which slides the AI selection keeps; style sets the commentary voice.",
                _audience_length(),
            ),
            _setup_section(
                "bi-people", "Peers",
                "Confidential — aggregate benchmark only, never a named peer.",
                _peers_panel(),
            ),
            _setup_section(
                "bi-stars", "AI assist",
                "Optional, faithfulness-verified enhancement layer.",
                _ai_control(),
            ),
            _setup_section(
                "bi-collection", "Deck sections",
                "The pages this scope will produce — read straight from the fixed templates.",
                html.Div(template_sections_panel(), id="studio-template-sections"), span=True,
            ),
        ],
        className="qs-setup-sections",
    )
    aside = html.Div(
        [
            _scope_preview(),
            html.Button(
                [html.I(className="bi bi-stars"), "Generate deck"],
                id="studio-generate",
                className="qs-generate-btn",
            ),
        ],
        className="qs-setup-aside",
    )
    form = html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className="bi bi-database"), "Deck setup"], className="qs-setup-title"),
                    html.P(
                        "Choose the client, period and scope. Figures are computed "
                        "deterministically from the governed dataset — no LLM, no invented numbers.",
                        className="qs-setup-sub",
                    ),
                ],
                className="qs-setup-head",
            ),
            html.Div([sections, aside], className="qs-setup-layout"),
        ],
        className="qs-setup-card",
    )
    return html.Div(form, className="qs-setup-wrap")
