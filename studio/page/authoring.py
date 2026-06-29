"""QBR Studio authoring shell — the story-led, evidence-governed workspace.

This renders the product direction from ``QBR_STUDIO_VISUAL_DESIGN_BLUEPRINT.md``:
a hybrid of **Storyroom** (deck-level narrative), **Boardroom Canvas** (page
composition + widget inspector) and a **Client-ready Review**, all wrapped around
the *same real* ``DeckSpec`` that ``studio.deck.build_deck`` computes from the DB
and that ``studio.export.ppt`` writes to PowerPoint. Browser and PPT are two
renderers of one document (blueprint §5).

Pure layout + deterministic derivations (chapters, story-item state, the
thesis→evidence→implication→decision spine). The live Dash callbacks in
``studio.authoring_app`` feed it a deck and the current view/overrides.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import dash_bootstrap_components as dbc
from dash import dcc, html

from studio.deck.model import DeckSpec, SlideSpec
from studio.page import canvas as CV
from studio.page import document as D
from studio.page import render
from studio.page.layout import (
    GPR_FILTERS,
    _breakdown,
    _filter_grid,
    _peers_panel,
    _report_type,
    _scope_toggle,
)
from studio.page.slide import render_slide

# ── global product modes (blueprint §"Global Product Modes", trimmed to the
#    three that drive real, working screens + Setup and Export) ────────────────
MODES: List[Mapping[str, str]] = [
    {"id": "setup", "label": "Setup", "icon": "bi-sliders2", "hint": "Scope & data"},
    {"id": "canvas", "label": "Canvas", "icon": "bi-grid-1x2", "hint": "Compose pages"},
    {"id": "review", "label": "Review", "icon": "bi-patch-check", "hint": "Client-ready"},
    {"id": "export", "label": "Export", "icon": "bi-filetype-pptx", "hint": "PowerPoint"},
]

THEME_COLORS: Tuple[Tuple[str, str], ...] = (
    ("#000F47", "Navy"),
    ("#0B4BFF", "Blue"),
    ("#00A8E0", "Cyan"),
    ("#007A78", "Teal"),
    ("#1F9D55", "Green"),
    ("#B9810A", "Amber"),
    ("#C53532", "Red"),
    ("#5B6577", "Slate"),
    ("#EEF3FF", "Blue tint"),
    ("#FFFFFF", "White"),
)
STANDARD_COLORS: Tuple[Tuple[str, str], ...] = (
    ("#000000", "Black"),
    ("#7F7F7F", "Gray"),
    ("#C00000", "Dark red"),
    ("#FF0000", "Red"),
    ("#FFC000", "Gold"),
    ("#FFFF00", "Yellow"),
    ("#92D050", "Light green"),
    ("#00B050", "Green"),
    ("#00B0F0", "Light blue"),
    ("#7030A0", "Purple"),
)

ZOOM_MIN = 40
ZOOM_MAX = 130
ZOOM_STEP = 5
ZOOM_FIT = 65

# Story-item states → (css token, human label). A subset of the blueprint's
# "Story Item States" that we can derive deterministically from slide content.
_STATUS_LABEL = {
    "approved": "Approved",
    "client-ready": "Client-ready",
    "needs-review": "Needs review",
    "needs-evidence": "Needs evidence",
    "draft": "Draft",
    "ready": "Ready",
    "appendix": "Appendix",
}


# ── deterministic derivations from the real deck ─────────────────────────────


def slide_status(slide: SlideSpec) -> Tuple[str, str]:
    """Map a slide to one visible story-item state (no score, just content rules)."""
    layout = slide.layout
    if layout in ("cover", "divider", "agenda"):
        return "ready", _STATUS_LABEL["ready"]
    if layout == "methodology":
        return "appendix", _STATUS_LABEL["appendix"]
    if layout == "exec":
        return "approved", _STATUS_LABEL["approved"]
    if layout in ("insight", "decision", "swot", "initiatives"):
        has_ev = bool(slide.evidence)
        has_reco = bool(slide.recommendation)
        if layout in ("insight", "decision") and not has_ev:
            return "needs-evidence", _STATUS_LABEL["needs-evidence"]
        if has_reco and slide.owner:
            return "approved", _STATUS_LABEL["approved"]
        if has_reco:
            return "needs-review", _STATUS_LABEL["needs-review"]
        return "draft", _STATUS_LABEL["draft"]
    return "draft", _STATUS_LABEL["draft"]


def chapters(deck: DeckSpec) -> List[Mapping[str, Any]]:
    """Group the flat slide list into chapters, split on ``divider`` slides.

    Each chapter carries its own header index (the divider, where present) and the
    indexed content slides beneath it — this is the Storyroom outline.
    """
    out: List[dict] = []
    cur: Optional[dict] = None
    for i, s in enumerate(deck.slides):
        if s.layout == "divider":
            cur = {"title": s.title, "eyebrow": s.eyebrow, "head_idx": i, "slides": []}
            out.append(cur)
            continue
        if cur is None:
            cur = {"title": "Opening", "eyebrow": "OVERVIEW", "head_idx": i, "slides": []}
            out.append(cur)
        cur["slides"].append((i, s))
    return out


def spine(slide: SlideSpec) -> Mapping[str, Any]:
    """The story spine for a content slide: thesis → evidence → implication → decision."""
    implication = slide.implication
    if not implication and slide.takeaways:
        implication = next((t.get("text", "") for t in slide.takeaways), "")
    return {
        "thesis": slide.title,
        "question": slide.question,
        "evidence": list(slide.evidence),
        "implication": implication,
        "decision": slide.recommendation,
        "owner": slide.owner,
        "due": slide.due_date,
        "confidence": slide.confidence,
    }


def deck_counts(deck: DeckSpec, doc: Optional[Mapping[str, Any]] = None) -> Mapping[str, int]:
    """Page-count summary for the top bar / pages mode (blueprint §"Page Count")."""
    statuses = [slide_status(s)[0] for s in deck.slides]
    return {
        "total": len(deck.slides),
        "appendix": sum(1 for s in statuses if s == "appendix"),
        "needs_review": sum(1 for s in statuses if s in ("needs-review", "needs-evidence")),
        "approved": sum(1 for s in statuses if s in ("approved", "client-ready")),
        "hidden": len(_hidden_ids(doc)),
    }


def _edited(doc: Optional[Mapping[str, Any]], idx: int, field: str) -> bool:
    """Whether the field at position ``idx`` carries a user override.

    The *display* value already comes from the materialized slide (edits applied),
    so the view only needs the provenance flag here — blueprint §3 "Everything
    Editable, Evidence Preserved": the generated value still lives in the document.
    """
    if not doc:
        return False
    sid = D.sid_at(doc, idx)
    return bool(sid and D.is_edited(doc, sid, field))


def _prov_badge(edited: bool) -> html.Span:
    return html.Span(
        [html.I(className="bi bi-pencil-fill"), "User edited"]
        if edited
        else [html.I(className="bi bi-shield-check"), "Rules verified"],
        className="qs-prov-badge" + (" edited" if edited else ""),
    )


def _hidden_ids(doc: Optional[Mapping[str, Any]]) -> set:
    return set((doc or {}).get("hidden", []))


def _is_hidden(doc: Optional[Mapping[str, Any]], idx: int) -> bool:
    sid = D.sid_at(doc, idx) if doc else None
    return bool(sid and sid in _hidden_ids(doc))


# ── left mode rail (the dark navigation spine) ───────────────────────────────


def mode_rail(active: str, counts: Mapping[str, int]) -> html.Aside:
    items = [
        html.Button(
            [
                html.I(className=f"bi {m['icon']}"),
                html.Span(m["label"], className="qs-mode-label"),
            ],
            id={"type": "qs-mode", "mode": m["id"]},
            className="qs-mode-btn" + (" active" if m["id"] == active else ""),
            title=m["hint"],
        )
        for m in MODES
    ]
    return html.Aside(
        [
            html.Div(
                [html.Div("Q", className="qs-mark"), html.Span("Studio", className="qs-mark-word")],
                className="qs-rail-brand",
            ),
            html.Div(items, className="qs-mode-list"),
            html.Div(
                [
                    html.Div(str(counts.get("total", 0)), className="qs-rail-count-num"),
                    html.Div("pages", className="qs-rail-count-lbl"),
                ],
                className="qs-rail-count",
            ),
        ],
        className="qs-mode-rail",
    )


# ── top bar ──────────────────────────────────────────────────────────────────


def top_bar(deck: DeckSpec, doc: Optional[Mapping[str, Any]] = None) -> html.Header:
    meta = dict(deck.meta or {})
    carrier = meta.get("carrier") or "Carrier"
    country = meta.get("country") or "Market"
    year = meta.get("year") or ""
    report = "Executive Summary" if meta.get("report") == "exec" else "QBR"
    counts = deck_counts(deck, doc)
    ready = counts["needs_review"] == 0 and counts["total"] > 0
    return html.Header(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f"{carrier} · {country}", className="qs-deck-name"),
                            html.Span(f"{year} · {report}", className="qs-deck-period"),
                        ],
                        className="qs-deck-id",
                    ),
                    html.Span(
                        [html.I(className="bi bi-cloud-check"), "Saved in browser"],
                        className="qs-autosave",
                        title="The editable document persists in local storage and survives a refresh.",
                    ),
                ],
                className="qs-top-left",
            ),
            html.Div(
                [
                    html.Span(
                        [
                            html.I(className=f"bi {'bi-patch-check-fill' if ready else 'bi-clock-history'}"),
                            "Client-ready" if ready else f"{counts['needs_review']} to review",
                        ],
                        className="qs-ready-badge" + (" ok" if ready else " warn"),
                    ),
                    html.Button([html.I(className="bi bi-easel"), "Present"], className="qs-btn-ghost"),
                    html.Button(
                        [html.I(className="bi bi-filetype-pptx"), "Export PPTX"],
                        id={"type": "qs-export", "loc": "top"},
                        className="qs-btn-primary",
                    ),
                ],
                className="qs-top-right",
            ),
        ],
        className="qs-topbar",
    )


# ── Setup mode (real build form, wired to the DB) ────────────────────────────


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
            _radio_field("MEETING LENGTH", "studio-meeting-length", [
                {"label": "Short · 15m", "value": "short"},
                {"label": "Standard · 30m", "value": "standard"},
                {"label": "Detailed · 60m", "value": "detailed"},
            ], "standard"),
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


def _template_control() -> html.Div:
    from studio.template_fill import registry

    templates = registry.list_templates() or [registry.active_template_path()]
    return html.Div(
        [
            html.Div("ACTIVE TEMPLATE", className="studio-field-label"),
            dcc.Dropdown(
                id="studio-template",
                options=[{"label": Path(t).name, "value": t} for t in templates],
                value=registry.active_template_path() if registry.active_template_path() in templates else templates[0],
                clearable=False,
                className="studio-dd",
            ),
            dcc.Upload(
                id="studio-template-upload",
                children=html.Div([html.I(className="bi bi-upload"), " Upload a .pptx template"]),
                accept=".pptx",
                className="qs-tf-upload",
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
                "Client, period and every cut — computed deterministically from the governed dataset.",
                html.Div([_scope_toggle(), _filter_grid(filter_options, filter_values)], className="qs-sec-stack"),
                span=True,
            ),
            _setup_section(
                "bi-diagram-3", "Report & breakdown",
                "Report type and the dimensions to break results down by.",
                html.Div([_report_type(), _breakdown()], className="qs-sec-grid cols-2"),
            ),
            _setup_section(
                "bi-file-earmark-slides", "Template",
                "The deck is generated by filling THIS .pptx; upload your own to use a different one.",
                _template_control(), span=True,
            ),
            _setup_section(
                "bi-easel2", "Audience & length",
                "Tunes which slides the AI selection keeps for the meeting.",
                _audience_length(),
            ),
            _setup_section(
                "bi-collection", "Deck sections",
                "The pages this template will produce — read straight from the .pptx above.",
                html.Div(template_sections_panel(), id="studio-template-sections"), span=True,
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


# ── Canvas mode (Boardroom Canvas + Widget Inspector) ────────────────────────


def _filmstrip(deck: DeckSpec, active_idx: int) -> html.Div:
    thumbs = [
        html.Button(
            [
                html.Span(str(i + 1), className="qs-thumb-num"),
                html.Span(s.title or s.eyebrow or s.layout, className="qs-thumb-label"),
                html.Span(className=f"qs-thumb-dot {slide_status(s)[0]}"),
            ],
            id={"type": "qs-goto", "idx": i, "src": "film"},
            className="qs-thumb" + (" active" if i == active_idx else ""),
        )
        for i, s in enumerate(deck.slides)
    ]
    return html.Div(thumbs, className="qs-filmstrip")


_COMPONENTS = [
    ("bi-bar-chart-line", "Premium trend"),
    ("bi-bar-chart-steps", "Variance bridge"),
    ("bi-grid-3x3", "Portfolio heatmap"),
    ("bi-bullseye", "Opportunity matrix"),
    ("bi-trophy", "Ranking table"),
    ("bi-people", "Peer benchmark"),
    ("bi-radar", "Risk radar"),
    ("bi-card-checklist", "Decision table"),
]


def _component_library() -> html.Div:
    cards = [
        html.Div(
            [html.I(className=f"bi {icon}"), html.Span(name, className="qs-comp-name")],
            className="qs-comp-card",
            draggable="true",
        )
        for icon, name in _COMPONENTS
    ]
    return html.Div(
        [
            html.Div([html.I(className="bi bi-grid-1x2"), "Component library"], className="qs-comp-title"),
            html.Div(cards, className="qs-comp-grid"),
        ],
        className="qs-comp-lib",
    )


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


def _page_toolbar(idx: int, total: int, hidden: bool) -> html.Div:
    """Context toolbar — real page operations on the active slide (blueprint §Page
    Actions). Each button mutates the shared document via ``qs-pageop``."""
    def op(o, icon, label, *, disabled=False, danger=False):
        return html.Button(
            [html.I(className=f"bi {icon}"), html.Span(label, className="qs-op-lbl")],
            id={"type": "qs-pageop", "op": o, "idx": idx},
            className="qs-op-btn" + (" danger" if danger else ""),
            disabled=disabled,
            title=label,
        )

    return html.Div(
        [
            op("up", "bi-arrow-up", "Move up", disabled=idx == 0),
            op("down", "bi-arrow-down", "Move down", disabled=idx >= total - 1),
            op("hide", "bi-eye" if hidden else "bi-eye-slash", "Show" if hidden else "Hide"),
            op("duplicate", "bi-files", "Duplicate"),
            op("delete", "bi-trash3", "Delete", danger=True),
        ],
        className="qs-op-bar",
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


def normalized_zoom(value: Any) -> int:
    try:
        zoom = int(value)
    except (TypeError, ValueError):
        zoom = ZOOM_FIT
    return max(ZOOM_MIN, min(ZOOM_MAX, zoom))


def adjusted_zoom(value: Any, operation: str) -> int:
    zoom = normalized_zoom(value)
    if operation == "in":
        return min(ZOOM_MAX, zoom + ZOOM_STEP)
    if operation == "out":
        return max(ZOOM_MIN, zoom - ZOOM_STEP)
    return ZOOM_FIT


def zoom_scale(value: Any) -> float:
    return round(normalized_zoom(value) / ZOOM_FIT, 4)


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


def _zoom_controls(zoom: int) -> html.Div:
    def control(operation: str, icon: str, label: str) -> html.Button:
        return html.Button(
            html.I(className=f"bi {icon}"),
            id={"type": "qs-zoom", "op": operation},
            className="qs-zoom-btn",
            title=label,
            **{"aria-label": label},
        )

    return html.Div(
        [
            html.I(className="bi bi-display qs-zoom-display"),
            control("out", "bi-dash-lg", "Zoom out"),
            html.Span(f"{zoom}%", className="qs-zoom-value"),
            control("in", "bi-plus-lg", "Zoom in"),
            control("fit", "bi-arrows-fullscreen", "Fit slide"),
        ],
        className="qs-zoom-controls",
    )


def canvas_body(
    deck: DeckSpec,
    active_idx: int,
    doc: Optional[Mapping[str, Any]],
    sel: Optional[str],
    zoom: Any = ZOOM_FIT,
    inspector_tab: str = "setup",
    library_category: str = "all",
    library_tab: str = "all",
    library_view: str = "grid",
    library_search: str = "",
    inspector_collapsed: bool = False,
    library_collapsed: bool = False,
    library_open: bool = False,
) -> html.Div:
    active_idx = max(0, min(active_idx, len(deck.slides) - 1))
    zoom = normalized_zoom(zoom)
    slide = deck.slides[active_idx]
    hidden = _is_hidden(doc, active_idx)
    sid = D.sid_at(doc, active_idx) if doc else None
    widgets = D.page_widgets(doc, sid) if (doc and sid) else []
    page_style = D.effective_page_style(doc, sid) if (doc and sid) else {}
    if sel and not any(w["id"] == sel for w in widgets):
        sel = None
    center = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f"Page {active_idx + 1} of {len(deck.slides)}", className="qs-canvas-meta"),
                            html.Span("Hidden from export", className="qs-hidden-tag") if hidden else None,
                            html.Span(f"{len(widgets)} widgets", className="qs-canvas-chip"),
                            html.Button(
                                [html.I(className="bi bi-plus-lg"), "Add component"],
                                id={"type": "qs-lib-toggle", "op": "open"},
                                className="qs-lib-open-btn",
                            ),
                        ],
                        className="qs-canvas-meta-wrap",
                    ),
                    _page_toolbar(active_idx, len(deck.slides), hidden),
                ],
                className="qs-canvas-bar",
            ),
            html.Div(
                [
                    html.Div("16:9", className="qs-aspect-cue"),
                    html.Div(
                        CV.canvas_surface(
                            widgets,
                            sel,
                            layout=slide.layout,
                            accent=slide.accent,
                            page_style=page_style,
                        ),
                        className="qs-slide-frame canvas"
                        + (" is-hidden" if hidden else ""),
                        style={"transform": f"scale({zoom_scale(zoom)})"},
                    ),
                ],
                className="qs-canvas-viewport",
            ),
            html.Div(
                [
                    _zoom_controls(zoom),
                    html.Span("Snap guides hidden", className="qs-grid-status"),
                ],
                className="qs-canvas-footer",
            ),
        ],
        className="qs-canvas-center",
    )
    left = _pages_panel(deck, active_idx, doc)
    right = (
        _widget_inspector(doc, sid, sel, inspector_tab, inspector_collapsed)
        if (sel and sid)
        else _select_hint(doc, sid, inspector_collapsed)
    )
    canvas_classes = ["qs-canvas"]
    if inspector_collapsed:
        canvas_classes.append("inspector-collapsed")
    if library_open:
        canvas_classes.append("library-open")
    children = [left, center, right]
    if library_open:
        children.append(
            _library_modal(library_category, library_tab, library_view, library_search)
        )
    return html.Div(children, className=" ".join(canvas_classes))


def _library_modal(category: str, tab: str, view: str, search: str) -> html.Div:
    """The component library as an on-demand popup, freeing the canvas for the QBR."""
    return html.Div(
        [
            html.Button(className="qs-lib-backdrop", id={"type": "qs-lib-toggle", "op": "close-bd"}),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [html.I(className="bi bi-grid-1x2"), "Add a component"],
                                className="qs-lib-modal-title",
                            ),
                            html.Button(
                                html.I(className="bi bi-x-lg"),
                                id={"type": "qs-lib-toggle", "op": "close"},
                                className="qs-lib-modal-close",
                            ),
                        ],
                        className="qs-lib-modal-head",
                    ),
                    CV.palette(category=category, tab=tab, view=view, search=search, collapsed=False),
                ],
                className="qs-lib-modal-card",
            ),
        ],
        id="qs-lib-modal",
        className="qs-lib-modal",
    )


def _divider_label(
    deck: DeckSpec,
    idx: int,
    doc: Optional[Mapping[str, Any]],
) -> str:
    """Use the live divider headline so rail labels follow canvas edits."""
    if doc:
        sid = D.sid_at(doc, idx)
        if sid:
            headline = next(
                (w for w in D.page_widgets(doc, sid) if w.get("kind") == "headline"),
                None,
            )
            if headline:
                text = str((headline.get("props") or {}).get("text") or "").strip()
                if text:
                    return text
    slide = deck.slides[idx]
    return slide.title or slide.eyebrow or "Section"


def _page_sections(
    deck: DeckSpec,
    doc: Optional[Mapping[str, Any]] = None,
) -> List[Mapping[str, Any]]:
    """Group page indices into numbered sections split on divider pages."""
    sections: List[dict] = []
    cur: Optional[dict] = None
    for i, slide in enumerate(deck.slides):
        if slide.layout == "divider":
            cur = {"label": _divider_label(deck, i, doc), "idxs": [i]}
            sections.append(cur)
        else:
            if cur is None:
                cur = {"label": "Executive summary", "idxs": []}
                sections.append(cur)
            cur["idxs"].append(i)
    for number, section in enumerate(sections, start=1):
        section["number"] = number
    return sections


def _thumb_preview(deck: DeckSpec, idx: int, doc: Optional[Mapping[str, Any]]) -> html.Div:
    """A live read-only miniature of the page's actual canvas composition."""
    sid = D.sid_at(doc, idx) if doc else None
    widgets = D.page_widgets(doc, sid) if (doc and sid) else []
    slide = deck.slides[idx]
    page_style = D.effective_page_style(doc, sid) if (doc and sid) else {}
    return html.Div(
        CV.thumbnail_surface(
            widgets,
            layout=slide.layout,
            accent=slide.accent,
            page_style=page_style,
        ),
        className="qs-pg-thumb",
    )


def _pages_panel(deck: DeckSpec, active_idx: int, doc: Optional[Mapping[str, Any]]) -> html.Div:
    sections = _page_sections(deck, doc)
    section_groups: List[Any] = []
    for section in sections:
        page_cards: List[Any] = []
        for i in section["idxs"]:
            slide = deck.slides[i]
            hidden = _is_hidden(doc, i)
            display_title = (
                _divider_label(deck, i, doc)
                if slide.layout == "divider"
                else (slide.title or slide.eyebrow or slide.layout)
            )
            page_cards.append(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Span(str(i + 1), className="qs-pg-num"),
                                html.I(className="bi bi-eye-slash qs-pg-hidden")
                                if hidden
                                else html.Span(className=f"qs-thumb-dot {slide_status(slide)[0]}"),
                            ],
                            className="qs-pg-head",
                        ),
                        _thumb_preview(deck, i, doc),
                        html.Span(display_title, className="qs-pg-title"),
                    ],
                    id={"type": "qs-goto", "idx": i, "src": "pages"},
                    n_clicks=0,
                    role="button",
                    tabIndex=0,
                    title=f"Open page {i + 1}: {display_title}",
                    className=(
                        "qs-pg"
                        + (" active" if i == active_idx else "")
                        + (" hidden" if hidden else "")
                        + (" divider" if slide.layout == "divider" else "")
                    ),
                )
            )
        section_groups.append(
            html.Details(
                [
                    html.Summary(
                        [
                            html.I(className="bi bi-chevron-down qs-pg-section-chevron"),
                            html.Span(str(section["number"]), className="qs-pg-section-num"),
                            html.Span(section["label"], className="qs-pg-section-name"),
                            html.Span(str(len(page_cards)), className="qs-pg-section-count"),
                        ],
                        className="qs-pg-section",
                    ),
                    html.Div(page_cards, className="qs-pg-section-pages"),
                ],
                open=True,
                className="qs-pg-section-group",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [html.I(className="bi bi-collection"), "Pages"],
                                className="qs-panel-title",
                            ),
                            html.Div(
                                [
                                    html.Span(f"{len(deck.slides)} pages"),
                                    html.Span(f"{len(sections)} sections"),
                                ],
                                className="qs-pg-summary",
                            ),
                        ]
                    ),
                ],
                className="qs-pg-toolbar",
            ),
            html.Div(section_groups, className="qs-pg-list"),
            html.Div(
                [
                    html.Button(
                        [html.I(className="bi bi-file-earmark-plus"), "Add page"],
                        id={"type": "qs-pageop", "op": "add", "idx": active_idx},
                        className="qs-pg-footer-btn",
                    ),
                    html.Button(
                        [html.I(className="bi bi-folder-plus"), "Insert section"],
                        id={"type": "qs-pageop", "op": "section", "idx": active_idx},
                        className="qs-pg-footer-btn section",
                    ),
                ],
                className="qs-pg-footer",
            ),
        ],
        className="qs-pages-panel",
    )


# ── Review mode (Client-ready checklist) ─────────────────────────────────────


def _overflow_slides(deck: DeckSpec) -> List[int]:
    """Heuristic export-overflow flag: content that likely won't fit a 16:9 slide.

    Honest heuristic (not a true PPT layout measurement): too many rail points, an
    over-long action title, or a long table all risk clipping on export."""
    bad = []
    for i, s in enumerate(deck.slides):
        if s.layout not in ("insight", "decision", "exec", "swot", "initiatives"):
            continue
        too_many_points = len(s.takeaways) > 5
        long_title = len(s.title or "") > 120
        long_table = any(b.kind == "table" and len(getattr(b, "rows", [])) > 14 for b in s.blocks)
        if too_many_points or long_title or long_table:
            bad.append(i + 1)
    return bad


def _unsupported_blocks(deck: DeckSpec) -> List[str]:
    """Block kinds present in the deck that the PPT exporter cannot render natively."""
    kinds = {b.kind for s in deck.slides for b in s.blocks}
    return sorted(kinds - D.EXPORT_SUPPORTED_BLOCKS)


def _checks(deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> List[Tuple[str, bool, str]]:
    """Client-ready checklist computed from the *materialized* deck — so it reflects
    user edits, reordering and hidden pages, and never hard-codes a pass."""
    slides = deck.slides
    content = [s for s in slides if s.layout in ("insight", "decision", "exec")]
    with_ev = [s for s in content if s.evidence]
    sourced = [s for s in content if s.sources or s.evidence]
    decisions = [s for s in content if s.recommendation]
    owned = [s for s in decisions if s.owner]
    titled = [s for s in content if len((s.title or "").strip()) > 25 and " " in (s.title or "")]
    has_cover = any(s.layout == "cover" for s in slides)
    has_agenda = any(s.layout == "agenda" for s in slides)
    has_method = any(s.layout == "methodology" for s in slides)
    overflow = _overflow_slides(deck)
    unsupported = _unsupported_blocks(deck)

    return [
        ("Cover and agenda present", has_cover and has_agenda,
         f"Cover: {'yes' if has_cover else 'no'} · Agenda: {'yes' if has_agenda else 'no'}"),
        ("All main-deck claims have evidence", bool(content) and len(with_ev) == len(content),
         f"{len(with_ev)}/{len(content)} content slides carry linked facts"),
        ("Every content slide cites a source", bool(content) and len(sourced) == len(content),
         f"{len(sourced)}/{len(content)} slides expose source/evidence lineage"),
        ("Decisions have owners", len(decisions) == 0 or len(owned) == len(decisions),
         f"{len(owned)}/{len(decisions)} recommendations name an owner"),
        ("Action titles read as takeaways", bool(content) and len(titled) == len(content),
         f"{len(titled)}/{len(content)} titles are full sentences (heuristic)"),
        ("No likely export overflow", not overflow,
         "No clipping risk detected" if not overflow else f"Slides at risk: {', '.join(map(str, overflow))} (heuristic)"),
        ("Methodology / limitations included", has_method,
         "Appendix documents method and data gaps" if has_method else "No methodology slide in the deck"),
        ("Browser ↔ PPT parity", not unsupported,
         "Export renders this exact document — edits, order and hidden pages included"
         if not unsupported else f"Unsupported widget(s) for native export: {', '.join(unsupported)}"),
    ]


def review_body(deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> html.Div:
    checks = _checks(deck, doc)
    passed = sum(1 for _, ok, _ in checks if ok)
    ready = passed == len(checks)
    rows = [
        html.Div(
            [
                html.I(className=f"bi {'bi-check-circle-fill' if ok else 'bi-exclamation-circle'} qs-chk-icon {'ok' if ok else 'warn'}"),
                html.Div(
                    [html.Div(label, className="qs-chk-label"), html.Div(detail, className="qs-chk-detail")],
                ),
            ],
            className="qs-chk-row" + ("" if ok else " warn"),
        )
        for label, ok, detail in checks
    ]
    counts = deck_counts(deck, doc)
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [html.I(className="bi bi-patch-check"), "Client-ready review"],
                                className="qs-panel-title",
                            ),
                            html.Div(
                                f"{passed} of {len(checks)} checks passing",
                                className="qs-review-score" + (" ok" if ready else ""),
                            ),
                        ],
                        className="qs-review-head",
                    ),
                    html.Div(rows, className="qs-chk-list"),
                    html.Button(
                        [html.I(className=f"bi {'bi-patch-check-fill' if ready else 'bi-lock'}"),
                         "Mark client-ready" if ready else "Resolve issues to continue"],
                        className="qs-review-cta" + (" ok" if ready else ""),
                        disabled=not ready,
                    ),
                ],
                className="qs-review-card",
            ),
            html.Div(
                [
                    _stat_card("Pages (export)", counts["total"] - counts["hidden"], "bi-collection", "blue"),
                    _stat_card("Approved", counts["approved"], "bi-check2-circle", "green"),
                    _stat_card("Needs review", counts["needs_review"], "bi-clock-history", "amber"),
                    _stat_card("Hidden", counts["hidden"], "bi-eye-slash", "navy"),
                ],
                className="qs-review-stats",
            ),
        ],
        className="qs-review",
    )


def _stat_card(label: str, value: int, icon: str, accent: str) -> html.Div:
    return html.Div(
        [
            html.Div(html.I(className=f"bi {icon}"), className=f"qs-rstat-icon {accent}"),
            html.Div([html.Div(str(value), className="qs-rstat-num"), html.Div(label, className="qs-rstat-lbl")]),
        ],
        className="qs-rstat",
    )


# ── Export mode (preview + real download) ────────────────────────────────────


def export_body(deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> html.Div:
    hidden_n = len(_hidden_ids(doc))
    thumbs = []
    for i, s in enumerate(deck.slides):
        hidden = _is_hidden(doc, i)
        thumbs.append(
            html.Div(
                [
                    html.Div(html.Div(render_slide(s, i + 1, len(deck.slides)), className="qs-exp-scale"), className="qs-exp-thumb-frame"),
                    html.Div(
                        [
                            html.Span(str(i + 1), className="qs-exp-num"),
                            html.Span(s.title or s.eyebrow or s.layout, className="qs-exp-name"),
                            html.Span("Excluded", className="qs-exp-excl") if hidden else None,
                        ],
                        className="qs-exp-cap",
                    ),
                ],
                className="qs-exp-card" + (" excluded" if hidden else ""),
            )
        )
    note = (
        f"{len(deck.slides) - hidden_n} of {len(deck.slides)} pages export"
        + (f" · {hidden_n} hidden page(s) excluded" if hidden_n else "")
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className="bi bi-filetype-pptx"), "Export preview"], className="qs-panel-title"),
                    html.P(
                        "The PowerPoint is produced by materializing this exact document — your "
                        "edits, page order and hidden-page choices included. Nothing is regenerated.",
                        className="qs-exp-sub",
                    ),
                    html.Div(note, className="qs-exp-note"),
                    html.Button(
                        [html.I(className="bi bi-download"), "Download .pptx"],
                        id={"type": "qs-export", "loc": "preview"},
                        className="qs-generate-btn",
                    ),
                ],
                className="qs-exp-head",
            ),
            html.Div(thumbs, className="qs-exp-grid"),
        ],
        className="qs-export",
    )


# ── empty state + shell assembly ─────────────────────────────────────────────


def empty_canvas() -> html.Div:
    return html.Div(
        [
            html.I(className="bi bi-easel2 qs-empty-icon"),
            html.Div("No deck yet", className="qs-empty-title"),
            html.P(
                "Open Setup, choose a client and period, then Generate deck. "
                "The whole studio — narrative, canvas and review — is built from the result.",
                className="qs-empty-sub",
            ),
            html.Button(
                [html.I(className="bi bi-sliders2"), "Open Setup"],
                id="qs-empty-setup",
                className="qs-generate-btn",
            ),
        ],
        className="qs-empty",
    )


def body_for(
    mode: str,
    deck: Optional[DeckSpec],
    view: Mapping[str, Any],
    doc: Optional[Mapping[str, Any]],
    *,
    cut_groups: Sequence[Mapping[str, Any]],
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
    tdoc: Optional[Mapping[str, Any]] = None,
) -> Any:
    if mode == "setup":
        return setup_body(cut_groups, filter_options=filter_options, filter_values=filter_values)
    # Template-faithful bodies: when a template doc exists it IS the deliverable —
    # the canvas previews the filled template, Review validates it, Export fills it.
    if tdoc:
        from studio.page import template_preview as TP

        if mode == "canvas":
            return TP.template_preview_body(tdoc, view)
        if mode == "review":
            return TP.template_review_body(tdoc)
        if mode == "export":
            return TP.template_export_body(tdoc)
    if deck is None or not deck.slides:
        return empty_canvas()
    idx = int(view.get("idx", 0))
    if mode == "canvas":
        return canvas_body(
            deck,
            idx,
            doc,
            view.get("sel"),
            view.get("zoom", ZOOM_FIT),
            view.get("tab", "setup"),
            view.get("lib_category", "all"),
            view.get("lib_tab", "all"),
            view.get("lib_view", "grid"),
            view.get("lib_search", ""),
            bool(view.get("inspector_collapsed", False)),
            bool(view.get("library_collapsed", False)),
            bool(view.get("library_open", False)),
        )
    if mode == "review":
        return review_body(deck, doc)
    if mode == "export":
        return export_body(deck, doc)
    return canvas_body(deck, idx, doc, view.get("sel"), view.get("zoom", ZOOM_FIT))


def authoring_shell(
    deck: Optional[DeckSpec],
    *,
    doc: Optional[Mapping[str, Any]] = None,
    mode: str = "setup",
    view: Mapping[str, Any] | None = None,
    cut_groups: Sequence[Mapping[str, Any]],
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
    tdoc: Optional[Mapping[str, Any]] = None,
) -> html.Div:
    view = view or {"idx": 0, "tab": "setup"}
    counts = deck_counts(deck, doc) if deck else {"total": 0}
    if not deck and tdoc:
        counts = {"total": int(tdoc.get("n_slides", 0))}
    top = top_bar(deck, doc) if deck else _placeholder_topbar(enabled=bool(tdoc))
    body = body_for(
        mode, deck, view, doc,
        cut_groups=cut_groups, filter_options=filter_options, filter_values=filter_values,
        tdoc=tdoc,
    )
    return html.Div(
        [
            mode_rail(mode, counts),
            html.Div(
                [top, html.Div(body, id="qs-canvas", className="qs-canvas-host")],
                className="qs-shell-main",
            ),
        ],
        className=f"qs-root mode-{mode}",
    )


def _placeholder_topbar(enabled: bool = False) -> html.Header:
    return html.Header(
        [
            html.Div(
                [
                    html.Div(
                        [html.Span("New QBR deck", className="qs-deck-name"), html.Span("Not generated", className="qs-deck-period")],
                        className="qs-deck-id",
                    ),
                ],
                className="qs-top-left",
            ),
            html.Div(
                [html.Button([html.I(className="bi bi-filetype-pptx"), "Export PPTX"], id={"type": "qs-export", "loc": "top"}, className="qs-btn-primary", disabled=not enabled)],
                className="qs-top-right",
            ),
        ],
        className="qs-topbar",
    )
