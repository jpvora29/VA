"""The Setup page, laid out as an editorial brief.

One calm column of decisions on the left — the brief, the market and period, the
benchmark — and on the right the deck taking shape: a cover that follows the choices, the
live headline figures, and the page list (with its hover previews). A sticky action bar
keeps the scope summary and Generate in view however far the form is scrolled.

Layout only. Every control keeps the id its callback already reads
(:mod:`studio.authoring.setup`), so moving a control on the page never moves its logic.
The cover, the "More filters" summary and the action-bar text are painted by small
callbacks registered in :mod:`studio.authoring.setup_summary`.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from dash import dcc, html

from studio.page.authoring import setup as S
from studio.page.layout import DROPDOWN_MAX_HEIGHT, GPR_FILTERS

# Every filter, together, in the order a QBR is briefed: who, where, when, then the slice.
SETUP_FILTERS = ("carrier", "country", "year", "quarter", "product_line", "region",
                 "business_line", "cover_line", "industry", "sub_industry", "client_segment")

# Sentence-case names for a reader; "Country" is the market the QBR is held for.
FILTER_LABELS = {
    "carrier": "Carrier", "country": "Market", "year": "Year", "quarter": "Quarter",
    "product_line": "Product line", "region": "Region", "business_line": "Business line",
    "cover_line": "Cover line", "industry": "Industry", "sub_industry": "Sub-industry",
    "client_segment": "Client segment",
}

_FILTERS = {f["id"]: f for f in GPR_FILTERS}


# ── small building blocks ────────────────────────────────────────────────────


def segmented(cid: str, options: Sequence[Mapping[str, str]], value: str, *,
              persist: bool = False) -> dcc.RadioItems:
    """A segmented control: the options side by side, the chosen one raised."""
    extra = {"persistence": True, "persistence_type": "local"} if persist else {}
    return dcc.RadioItems(id=cid, options=list(options), value=value, className="qs6-seg",
                          inputClassName="qs6-seg-input", labelClassName="qs6-seg-label",
                          **extra)


def brief_row(label: str, control: Any, *, tip_id: str = "", tip: str = "",
              below: Any = None) -> html.Div:
    """One line of the brief: a short label (with its ⓘ) and the control beside it."""
    return html.Div(
        [
            html.Div([html.Span(label), S.info_tip(tip_id, tip) if tip_id else None],
                     className="qs6-row-label"),
            html.Div([control, below], className="qs6-row-control"),
        ],
        className="qs6-row",
    )


def section(title: str, children: Any, *, tip_id: str = "", tip: str = "",
            aside: Any = None, class_name: str = "") -> html.Section:
    return html.Section(
        [
            html.Div([html.H2([title, S.info_tip(tip_id, tip) if tip_id else None],
                              className="qs6-h2"), aside],
                     className="qs6-sec-head"),
            html.Div(children, className="qs6-sec-body"),
        ],
        className="qs6-sec" + (f" {class_name}" if class_name else ""),
    )


def filter_dropdown(col: str, options: Mapping[str, Any], values: Mapping[str, Any]):
    """One filter, keeping the pattern id every cascade callback matches on."""
    spec = _FILTERS[col]
    return dcc.Dropdown(
        id={"type": "studio-filter", "col": col},
        options=options.get(col, []),
        value=values.get(col),
        placeholder=spec["ph"],
        multi=spec.get("multi", False),
        maxHeight=DROPDOWN_MAX_HEIGHT,
        className="qs6-dd",
    )


def filter_field(col: str, options: Mapping[str, Any], values: Mapping[str, Any]) -> html.Div:
    return html.Div(
        [html.Label(FILTER_LABELS.get(col, _FILTERS[col]["label"]), className="qs6-flabel"),
         filter_dropdown(col, options, values)],
        className="qs6-field",
    )


# ── the main column ──────────────────────────────────────────────────────────


def hero() -> html.Div:
    return html.Div(
        [
            html.Div("QBR Creator", className="qs6-eyebrow"),
            html.H1("A sharper QBR starts here.", className="qs6-h1"),
            html.P("Set your audience, data and scope to build a tailored deck. Every "
                   "figure traces to the governed data.", className="qs6-lede"),
        ],
        className="qs6-hero",
    )


def brief(dataset: Optional[Mapping[str, Any]]) -> html.Section:
    rows = [
        brief_row(
            "Audience",
            segmented("studio-audience", [
                {"label": "Carrier team", "value": "carrier_leadership"},
                {"label": "Regional", "value": "marsh_regional"},
            ], "carrier_leadership"),
            tip_id="qs-tip-audience",
            tip="Who is this deck for? Carrier team is the client-facing read — the "
                "carrier's own underwriting and distribution leads. Regional is the "
                "internal Marsh view, which may weigh placement and pipeline the carrier "
                "would not see.",
        ),
        brief_row(
            "Commentary",
            segmented("studio-commentary-style", [
                {"label": "Concise", "value": "concise"},
                {"label": "Balanced", "value": "balanced"},
                {"label": "Detailed", "value": "detailed"},
            ], "balanced"),
            tip_id="qs-tip-style",
            tip="How should the commentary read? Concise is one or two sentences per "
                "panel, Detailed explains the drivers behind every movement. Every number "
                "stays checked against the source facts either way.",
        ),
        brief_row(
            "Source",
            segmented("studio-data-source", [
                {"label": "GPR / Survey", "value": "governed"},
                {"label": "Custom data", "value": "custom"},
            ], S.data_source_of(dataset)),
            tip_id="qs-tip-source",
            tip="Where should the numbers come from? GPR / Survey is the governed "
                "warehouse — the premium book and the carrier survey book behind it. "
                "Custom data builds the same deck from a spreadsheet you upload and map on "
                "the Data page.",
            below=S.source_status(dataset),
        ),
        brief_row(
            "Data basis",
            segmented("studio-data-basis", list(S.DATA_BASIS_OPTIONS), S.DATA_BASIS_DEFAULT),
            tip_id="qs-tip-basis",
            tip="Which books should the deck draw on? GPR is the premium book alone — "
                "totals, growth, share of wallet and rank. GPR + Carrier Survey adds a "
                "Carrier Survey page to each country block and the overall survey-score tile, "
                "sourced from the survey book.",
        ),
    ]
    # Two across (Audience | Commentary, Source | Data basis), every control the same size.
    return section("The brief", html.Div(rows, className="qs6-brief-grid"),
                   tip_id="qs-tip-sec-shape",
                   tip="Answer these from the brief: who the commentary is pitched at, how "
                       "much prose each slide carries, and where the numbers come from.")


def market_and_period(options: Mapping[str, Any], values: Mapping[str, Any]) -> html.Section:
    """The slice of the book, and the timeline — one pane, as a QBR is briefed."""
    grid = html.Div([filter_field(c, options, values) for c in SETUP_FILTERS],
                    className="qs6-fgrid")
    timeline = html.Div(
        [
            html.Label(["Timeline",
                        S.info_tip("qs-tip-period-basis",
                                   "YTD: January to the chosen month, against the same months "
                                   "last year. R12M: the 12 months to the chosen month, against "
                                   "the 12 before. Survey pages keep the survey year.")],
                       className="qs6-flabel"),
            S._period_control(),
            html.Div(S.period_note("YTD · latest year"),
                     id="studio-period-note", className="qs6-period-note"),
        ],
        className="qs6-field qs6-timeline-field",
    )
    return section("Market & period", [grid, timeline], tip_id="qs-tip-sec-filters",
                   tip="The slice of the book the deck reports on. The lists cascade, so "
                       "each one only offers values that exist under the others. Market and "
                       "Year accept several values; several markets build several country "
                       "blocks — and several peer groups.")


def benchmark() -> html.Section:
    return section(
        "Benchmark", S._peers_panel(),
        tip_id="qs-tip-sec-peers",
        tip="Who the carrier is benchmarked against. Existing peers come from the governed "
            "Peers table, one group per market; custom peers are yours to pin, per market, "
            f"with at least {S.MIN_CUSTOM_PEERS} carriers each so the benchmark stays an "
            "aggregate. No peer is ever named in carrier-facing output.",
        aside=html.Span("Aggregate only", className="qs6-chip"),
    )


def survey() -> html.Div:
    return html.Div(
        section("Survey", S._survey_panel(), tip_id="qs-tip-sec-survey",
                tip="The survey book is a separate flow with its own carrier names and its "
                    "own peer groups. Shown only when the deck draws on it, so a survey "
                    "page never reports another carrier's scores."),
        id="studio-survey-section",
        style={"display": "none"},              # shown on the GPR + Survey basis
    )


# ── the aside: the deck taking shape ─────────────────────────────────────────


def cover_preview() -> html.Div:
    """A cover that follows the brief — carrier, period, market and line."""
    return html.Div(
        [
            html.Div([html.B("ICG"), html.Span("Virtual Analyst")], className="qs6-cover-brand"),
            html.Div("Choose a carrier", id="qs6-cover-carrier", className="qs6-cover-carrier"),
            html.Div("Quarterly Business Review", className="qs6-cover-title"),
            html.Div(className="qs6-cover-rule"),
            html.Div("—", id="qs6-cover-period", className="qs6-cover-period"),
            html.Div("", id="qs6-cover-scope", className="qs6-cover-scope"),
        ],
        className="qs6-cover", **{"aria-label": "Deck cover preview"},
    )


def deck_preview() -> html.Div:
    return html.Div(
        [
            html.Div([html.H3("Deck preview", className="qs6-h3"),
                      html.Span("Governed data", id="qs6-source-badge", className="qs6-badge")],
                     className="qs6-aside-head"),
            cover_preview(),
            # No spinner of its own: the page-level one already covers this panel.
            html.Div(S.scope_preview_empty(), id="studio-scope-preview",
                     className="qs6-figures"),
        ],
        className="qs6-card qs6-preview-card",
    )


def deck_contents(slides) -> html.Div:
    return html.Div(
        [
            html.Div(
                [html.H3(["Deck contents",
                          S.info_tip("qs-tip-pages",
                                     "What's in your QBR: every page of every sub-template, "
                                     "with the tick that decides whether your deck carries "
                                     "it. Untick a page and it is not built, not filled and "
                                     "not written. Hover a page to see it as the template "
                                     "draws it — the template's own example, not this "
                                     "carrier's numbers.")],
                         className="qs6-h3"),
                 html.Span("What's in your QBR", className="qs6-aside-sub")],
                className="qs6-aside-head",
            ),
            html.Div(S.template_sections_panel(basis=S.DATA_BASIS_DEFAULT, slides=slides),
                     id="studio-template-sections"),
        ],
        className="qs6-card qs6-contents-card",
    )


# ── the action bar ───────────────────────────────────────────────────────────


def action_bar() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span(html.I(className="bi bi-circle"), id="qs6-status-icon",
                              className="qs6-status-icon"),
                    html.Span("Pick a carrier to begin", id="qs6-status-text",
                              className="qs6-status-text"),
                    html.Span("", id="qs6-summary", className="qs6-summary"),
                ],
                className="qs6-bar-left",
            ),
            html.Div(
                [
                    # Why a Generate click was refused. Written by the generate callback.
                    html.Div(id="studio-setup-msg", className="qs-setup-msg qs6-bar-msg"),
                    html.Button([html.Span("Generate deck"), html.I(className="bi bi-arrow-right")],
                                id="studio-generate", className="qs-generate-btn qs6-generate"),
                ],
                className="qs6-bar-right",
            ),
        ],
        className="qs6-bar",
    )


def compose_setup(*, filter_options: Mapping[str, Any] | None = None,
                  filter_values: Mapping[str, Any] | None = None,
                  dataset: Optional[Mapping[str, Any]] = None,
                  slides: Optional[Any] = None) -> html.Div:
    options, values = filter_options or {}, filter_values or {}
    main = html.Div(
        [hero(), brief(dataset), market_and_period(options, values), benchmark(), survey()],
        className="qs6-main",
    )
    aside = html.Aside([deck_preview(), deck_contents(slides)], className="qs6-aside")
    return html.Div(
        [S.form_token(), html.Div([main, aside], className="qs6-setup"), action_bar()],
        className="qs-setup-wrap qs6-setup-wrap",
    )
