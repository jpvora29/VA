from datetime import datetime

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from document_builder.report_generator import PITCH_THEMES, theme_options


# Example questions surfaced on the welcome screen and (mirrored) in the
# animated input placeholder. Keep these aligned with assets/typewriter.js.
STARTER_SUGGESTIONS = [
    ("bi bi-pie-chart", "What is Zurich's Share of Wallet in Canada for Property?"),
    ("bi bi-graph-up-arrow", "Show premium growth for Chubb across all product lines"),
    ("bi bi-people", "How does AXA's broker score compare to peers this year?"),
    ("bi bi-bar-chart-line", "What is the market composite rate change for Asia this quarter?"),
]


def _greeting() -> str:
    """Time-of-day greeting, Claude-style."""
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def suggestion_chip(question: str, icon: str | None = None, idx: int = 0):
    """A clickable question chip. The question text rides in the id so a single
    pattern-matching callback can handle both starter and follow-up chips."""
    children = []
    if icon:
        children.append(html.I(className=f"{icon} suggestion-chip-icon"))
    children.append(html.Span(question, className="suggestion-chip-text"))
    return html.Button(
        children,
        id={"type": "suggestion-chip", "idx": idx, "q": question},
        n_clicks=0,
        className="suggestion-chip",
    )


def clarify_card(payload: dict):
    """Inline Claude-style MCQ clarification card.

    `payload` is a ClarifyQuestion dict (question, header, options, allow_free_text).
    Option buttons carry their answer value in the id so one pattern-matching
    callback handles any option; a free-text box + send button is the fallback.
    """
    payload = payload or {}
    question = payload.get("question") or "Could you clarify what you mean?"
    header = payload.get("header") or "Quick check"
    options = payload.get("options") or []

    option_buttons = [
        html.Button(
            [
                html.Span(opt.get("label", ""), className="clarify-option-label"),
                (
                    html.Span(opt.get("description", ""), className="clarify-option-desc")
                    if opt.get("description")
                    else None
                ),
            ],
            id={"type": "clarify-option", "value": opt.get("label", "")},
            n_clicks=0,
            className="clarify-option",
        )
        for opt in options
        if opt.get("label")
    ]

    children = [
        html.Div(
            [
                html.I(className="bi bi-question-circle clarify-card-icon"),
                html.Span(header, className="clarify-card-header"),
            ],
            className="clarify-card-badge",
        ),
        html.Div(question, className="clarify-card-question"),
    ]
    if option_buttons:
        children.append(html.Div(option_buttons, className="clarify-option-grid"))
        if payload.get("allow_free_text", True):
            children.append(
                html.Div("Pick one, or type your own answer below.", className="clarify-hint")
            )
    if payload.get("allow_free_text", True):
        children.append(
            dbc.InputGroup(
                [
                    dbc.Input(
                        id="clarify-free-text",
                        placeholder="Or type your answer…",
                        debounce=True,
                        className="clarify-free-input",
                    ),
                    dbc.Button(
                        html.I(className="bi bi-arrow-return-left"),
                        id="clarify-free-submit",
                        n_clicks=0,
                        className="clarify-free-submit",
                    ),
                ],
                className="clarify-free-group",
            )
        )

    return html.Div(children, className="message clarify-card")


# A small rotation of icons for LLM-tailored starter questions (which arrive as
# plain strings, without their own icon).
_STARTER_ICONS = [
    "bi bi-pie-chart",
    "bi bi-graph-up-arrow",
    "bi bi-people",
    "bi bi-bar-chart-line",
]


def starter_chips(starters: list[str] | None = None) -> list:
    """Chips for the welcome hero — tailored strings if given, else the defaults."""
    if starters:
        return [
            suggestion_chip(question, _STARTER_ICONS[index % len(_STARTER_ICONS)], index)
            for index, question in enumerate(starters)
        ]
    return [
        suggestion_chip(question, icon, index)
        for index, (icon, question) in enumerate(STARTER_SUGGESTIONS)
    ]


def welcome_hero(name: str = "", starters: list[str] | None = None):
    """Empty-state hero shown before the first message is sent."""
    greeting = f"{_greeting()}, "
    accent = name.strip() if name and name.strip() else "let's dig into the data"
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        html.I(className="bi bi-stars"),
                        className="welcome-badge",
                    ),
                    html.H1(
                        [
                            greeting,
                            html.Span(accent, className="welcome-accent"),
                        ],
                        className="welcome-title",
                    ),
                    html.P(
                        "Your virtual insurance analyst. Ask about premium, Share of "
                        "Wallet, broker sentiment, peer benchmarks, or market rates — "
                        "all in plain English.",
                        className="welcome-subtitle",
                    ),
                ],
                className="welcome-head",
            ),
            html.Div("Try one of these", className="welcome-suggest-label"),
            html.Div(
                starter_chips(starters),
                id="starter-suggestions",
                className="suggestion-grid",
            ),
        ],
        className="welcome-hero",
    )


def followup_suggestions(followups: list[str]):
    """Row of suggested follow-up question chips shown under the latest answer."""
    if not followups:
        return None
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-lightbulb followup-icon"),
                    html.Span("Suggested follow-ups"),
                ],
                className="followup-label",
            ),
            html.Div(
                [
                    suggestion_chip(question, idx=index)
                    for index, question in enumerate(followups)
                ],
                className="followup-row",
            ),
        ],
        className="followup-block",
    )


def feedback_bar(idx: int):
    """Thumbs up/down for an assistant turn; click is recorded to episodic memory.

    `idx` is the message's position in the transcript so the recording callback
    (and the clientside active-state toggle) can pair the click to its answer.
    """
    return html.Div(
        [
            html.Button(
                html.I(className="bi bi-hand-thumbs-up"),
                id={"type": "msg-feedback", "idx": idx, "rating": "up"},
                n_clicks=0,
                className="msg-feedback-btn",
                title="Helpful",
            ),
            html.Button(
                html.I(className="bi bi-hand-thumbs-down"),
                id={"type": "msg-feedback", "idx": idx, "rating": "down"},
                n_clicks=0,
                className="msg-feedback-btn",
                title="Not helpful",
            ),
        ],
        className="msg-feedback",
    )


def ai_message(content: str, is_insight: bool, idx: int = 0):
    """Render an assistant turn with copy + thumbs-up/down feedback actions.

    `dcc.Clipboard` copies its `content` natively, so no callback is needed.
    The insight variant keeps the consulting-card chrome; the base variant is a
    plain bubble. Both are position:relative so the actions can sit top-right.
    """
    copy = dcc.Clipboard(
        content=content,
        title="Copy",
        className="msg-copy",
    )
    feedback = feedback_bar(idx)

    if is_insight:
        return html.Div(
            [
                html.Div(
                    [
                        html.Span("✨", className="insight-card-badge-icon"),
                        html.Span(
                            "Consulting Insight", className="insight-card-badge-text"
                        ),
                    ],
                    className="insight-card-badge",
                ),
                dcc.Markdown(
                    content, className="insight-card-body", link_target="_blank"
                ),
                copy,
                feedback,
            ],
            className="message insight-card",
        )

    return html.Div(
        [dcc.Markdown(content), copy, feedback],
        className="message gpt-message",
    )


def chart_block(figure, columns: list[str], records: list[dict], idx: int):
    """A chart with a Chart/Data switch that flips to the underlying rows.

    The graph and the data table are both rendered; a clientside callback
    (see ui.callbacks) toggles their visibility off the switch buttons. `idx`
    must be unique per chart within a turn so the MATCH callback pairs them.
    """
    table = dash_table.DataTable(
        columns=[{"name": str(c), "id": str(c)} for c in columns],
        data=records,
        page_size=10,
        sort_action="native",
        style_as_list_view=True,
        style_table={"overflowX": "auto", "maxHeight": "440px", "overflowY": "auto"},
        style_cell={
            "fontFamily": "'Inter', sans-serif",
            "fontSize": "13px",
            "padding": "8px 12px",
            "textAlign": "left",
            "border": "none",
            "borderBottom": "1px solid rgba(12, 25, 58, 0.06)",
        },
        style_header={
            "fontWeight": "600",
            "fontSize": "12px",
            "textTransform": "uppercase",
            "letterSpacing": "0.04em",
            "backgroundColor": "#f5f7fb",
            "borderBottom": "1px solid rgba(12, 25, 58, 0.12)",
        },
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        [html.I(className="bi bi-bar-chart-line"), "Chart"],
                        id={"type": "chart-toggle-chart", "idx": idx},
                        n_clicks=0,
                        className="chart-view-btn active",
                    ),
                    html.Button(
                        [html.I(className="bi bi-table"), "Data"],
                        id={"type": "chart-toggle-data", "idx": idx},
                        n_clicks=0,
                        className="chart-view-btn",
                    ),
                ],
                className="chart-view-switch",
            ),
            html.Div(
                dcc.Graph(figure=figure, className="gpt-chart-display"),
                id={"type": "chart-fig", "idx": idx},
            ),
            html.Div(
                table,
                id={"type": "chart-table", "idx": idx},
                className="chart-data-wrap",
                style={"display": "none"},
            ),
        ],
        className="chart-block",
    )


def chatbot_page(username: str = "", starters: list[str] | None = None):

    return html.Div(
        [
            dcc.Store(id="chat-store", data={}),
            dcc.Store(id="trigger-gpt", data=False),  # flag to run GPT call
            dcc.Store(id="trigger-resume", data=False),  # flag to resume a paused HITL thread
            dcc.Store(id="is-thinking", data=False),  # flag to show loader
            dcc.Store(id="has-chart", data=False),
            dcc.Store(id="overflow_data", data={}),
            dcc.Store(id="feedback-sink", data={}),  # write-only sink for thumb clicks
            # Polls the in-process streaming job each second for live status +
            # completion; enabled by launch_new_job / launch_resume_job.
            dcc.Interval(id="job-poll", interval=1000, n_intervals=0, disabled=True),
            dbc.Container(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Div(
                                        id="chat-box",
                                        className="chat-bot-text-area",
                                        children=[welcome_hero(username, starters)],
                                    ),
                                    dcc.Download(id="download-excel"),
                                ],
                                lg=12,
                                md=12,
                                xs=12,
                            )
                        ],
                        className="flex-grow-1 overflow-auto",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    # Live status bar — shown only while a turn is
                                    # streaming. poll_job updates the agent label +
                                    # elapsed seconds; a clientside callback toggles
                                    # its visibility off is-thinking.
                                    html.Div(
                                        [
                                            html.Span(className="thinking-dot"),
                                            html.Span(
                                                "Thinking",
                                                id="thinking-agent",
                                                className="thinking-agent",
                                            ),
                                            html.Span(
                                                "",
                                                id="thinking-elapsed",
                                                className="thinking-elapsed",
                                            ),
                                        ],
                                        id="thinking-bar",
                                        className="thinking-bar",
                                        style={"display": "none"},
                                    ),
                                    html.Div(
                                        [
                                            dbc.DropdownMenu(
                                                [
                                                    dbc.DropdownMenuItem(
                                                        [
                                                            html.I(
                                                                className="bi bi-easel2 composer-menu-icon"
                                                            ),
                                                            "Pitch Builder",
                                                        ],
                                                        id="menu-pitch-builder",
                                                        n_clicks=0,
                                                    ),
                                                    dbc.DropdownMenuItem(
                                                        [
                                                            html.I(
                                                                className="bi bi-grid-1x2 composer-menu-icon"
                                                            ),
                                                            "Boardroom Mode",
                                                        ],
                                                        id="menu-boardroom-mode",
                                                        n_clicks=0,
                                                    ),
                                                    dbc.DropdownMenuItem(
                                                        [
                                                            html.I(
                                                                className="bi bi-people composer-menu-icon"
                                                            ),
                                                            "Custom Peers",
                                                        ],
                                                        id="menu-custom-peers",
                                                        n_clicks=0,
                                                    ),
                                                ],
                                                id="composer-add-menu",
                                                label=html.I(className="bi bi-plus-lg"),
                                                direction="up",
                                                caret=False,
                                                toggleClassName="pitch-trigger-btn",
                                                className="composer-add-wrap",
                                            ),
                                            # Visual cue (like Claude's Search pill)
                                            # shown only while a custom peer set is
                                            # pinned for this conversation.
                                            html.Div(
                                                id="custom-peers-cue",
                                                className="custom-peers-cue",
                                            ),
                                            # Armed-state pill for Boardroom Mode; the
                                            # next answer renders as a dashboard card.
                                            html.Div(
                                                id="boardroom-mode-cue",
                                                className="boardroom-mode-cue",
                                            ),
                                            dbc.Input(
                                                id="user-input",
                                                placeholder="Ask anything",
                                                debounce=True,
                                                className="composer-input",
                                            ),
                                            dbc.Button(
                                                html.I(className="bi bi-arrow-up"),
                                                id="send-btn",
                                                n_clicks=0,
                                                className="send-btn",
                                            ),
                                            dbc.Button(
                                                html.I(className="bi bi-stop-fill"),
                                                id="stop-btn",
                                                n_clicks=0,
                                                className="stop-btn",
                                                style={"display": "none"},
                                            ),
                                        ],
                                        className="composer",
                                    ),
                                    html.Div(
                                        "Virtual Analyst can make mistakes. Verify important figures.",
                                        className="composer-disclaimer",
                                    ),
                                ],
                                lg=12,
                                md=12,
                                xs=12,
                                className="type-area",
                            ),
                        ],
                        className="input-area",
                    ),
                ],
                fluid=True,
            ),
        ],
        className="chatbot-area",
    )


def pitch_builder_drawer():
    return html.Div(
        [
            dcc.Interval(
                id="pitch-progress-interval", interval=700, n_intervals=0, disabled=True
            ),
            html.Div(
                id="pitch-builder-backdrop",
                className="pitch-builder-backdrop",
                style={
                    "position": "absolute",
                    "inset": 0,
                    "background": "rgba(11, 19, 32, 0.32)",
                    "opacity": 0,
                    "transition": "opacity 260ms cubic-bezier(.4, .0, .2, .1)",
                },
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        "Pitch Builder", className="pitch-builder-title"
                                    ),
                                    html.Div(
                                        "Theme-led questions, filtered data, and one-page report",
                                        className="pitch-drawer-subtitle",
                                    ),
                                ]
                            ),
                            dbc.Button(
                                html.I(className="bi bi-x-lg"),
                                id="pitch-close-btn",
                                n_clicks=0,
                                className="pitch-close-btn",
                            ),
                        ],
                        className="pitch-drawer-header",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div("1", className="pitch-step-num"),
                                    html.Span("Theme", className="pitch-step-label"),
                                ],
                                className="pitch-step",
                            ),
                            html.Div(className="pitch-step-line"),
                            html.Div(
                                [
                                    html.Div("2", className="pitch-step-num"),
                                    html.Span("Filters", className="pitch-step-label"),
                                ],
                                className="pitch-step",
                            ),
                            html.Div(className="pitch-step-line"),
                            html.Div(
                                [
                                    html.Div("3", className="pitch-step-num"),
                                    html.Span(
                                        "Questions", className="pitch-step-label"
                                    ),
                                ],
                                className="pitch-step",
                            ),
                        ],
                        className="pitch-step-strip",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.I(
                                        className="bi bi-palette2 pitch-section-icon"
                                    ),
                                    "Report Theme",
                                ],
                                className="pitch-section-title",
                            ),
                            dcc.Dropdown(
                                id="pitch-theme",
                                options=theme_options(),
                                value="performance_pitch",
                                clearable=False,
                                className="pitch-dropdown",
                            ),
                            html.Div(
                                PITCH_THEMES["performance_pitch"]["description"],
                                id="pitch-theme-description",
                                className="pitch-theme-description",
                            ),
                        ],
                        className="pitch-section",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.I(
                                        className="bi bi-funnel-fill pitch-section-icon"
                                    ),
                                    "Filters",
                                ],
                                className="pitch-section-title",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label(
                                                [
                                                    html.I(
                                                        className="bi bi-globe2 pitch-label-icon"
                                                    ),
                                                    "Country",
                                                ],
                                                className="pitch-field-label",
                                            ),
                                            dcc.Dropdown(
                                                id="pitch-country",
                                                placeholder="Select country",
                                                className="pitch-dropdown",
                                            ),
                                        ],
                                        className="pitch-filter-field",
                                    ),
                                    html.Div(
                                        [
                                            html.Label(
                                                [
                                                    html.I(
                                                        className="bi bi-building pitch-label-icon"
                                                    ),
                                                    "Carrier",
                                                ],
                                                className="pitch-field-label",
                                            ),
                                            dcc.Dropdown(
                                                id="pitch-carrier",
                                                placeholder="Select carrier",
                                                className="pitch-dropdown",
                                            ),
                                        ],
                                        className="pitch-filter-field",
                                    ),
                                    html.Div(
                                        [
                                            html.Label(
                                                [
                                                    html.I(
                                                        className="bi bi-calendar3 pitch-label-icon"
                                                    ),
                                                    "Year",
                                                ],
                                                className="pitch-field-label",
                                            ),
                                            dcc.Dropdown(
                                                id="pitch-year",
                                                placeholder="Select year",
                                                className="pitch-dropdown",
                                            ),
                                        ],
                                        className="pitch-filter-field",
                                    ),
                                ],
                                className="pitch-filter-grid",
                            ),
                        ],
                        className="pitch-section",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.I(
                                        className="bi bi-chat-square-text pitch-section-icon"
                                    ),
                                    html.Span(
                                        "Pitch Questions", id="pitch-questions-heading"
                                    ),
                                ],
                                className="pitch-section-title",
                            ),
                            html.Div(
                                [
                                    pitch_question_card(index, question)
                                    for index, question in enumerate(
                                        PITCH_THEMES["performance_pitch"]["questions"]
                                    )
                                ],
                                id="pitch-question-list",
                            ),
                        ],
                        id="pitch-question-section",
                        className="pitch-section pitch-question-section",
                        style={"display": "none"},
                    ),
                    html.Div(
                        [
                            dbc.Button(
                                [
                                    html.I(
                                        className="bi bi-file-earmark-word",
                                        style={
                                            "paddingRight": "8px",
                                            "color": "#FFFFFF",
                                        },
                                    ),
                                    "Generate Report",
                                ],
                                id="pitch-generate-report-btn",
                                n_clicks=0,
                                className="pitch-generate-btn",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span(
                                                "Status",
                                                className="pitch-progress-title",
                                            ),
                                            html.Span(
                                                "0% Ready",
                                                id="pitch-progress-label",
                                                className="pitch-progress-label",
                                            ),
                                        ],
                                        className="pitch-progress-meta",
                                    ),
                                    html.Div(
                                        html.Div(
                                            id="pitch-progress-fill",
                                            className="pitch-progress-fill",
                                            style={"width": "0%"},
                                        ),
                                        className="pitch-progress-track",
                                    ),
                                ],
                                className="pitch-progress",
                            ),
                            html.Div(
                                id="pitch-report-status",
                                className="pitch-report-status",
                            ),
                        ],
                        className="pitch-actions",
                    ),
                ],
                id="pitch-builder-panel",
                style={
                    "position": "absolute",
                    "top": 0,
                    "right": 0,
                    "width": "min(480px, 96vw)",
                    "height": "100vh",
                    "overflowY": "auto",
                    "background": "linear-gradient(180deg, #ffffff 0%, #f6f8fc 100%)",
                    "borderLeft": "1px solid rgba(12, 25, 58, 0.10)",
                    "boxShadow": "-24px 0 60px rgba(10, 22, 54, 0.16)",
                    "transform": "translateX(100%)",
                    "transition": "transform 320ms cubic-bezier(.16, .84, .44, 1)",
                },
            ),
        ],
        id="pitch-builder-drawer",
        className="pitch-builder-drawer",
        style={
            "position": "fixed",
            "inset": 0,
            "zIndex": 2000,
            "pointerEvents": "none",
            "visibility": "hidden",
        },
    )


def boardroom_mode_cue(is_on: bool):
    """Composer pill shown while Boardroom Mode is armed for the next answer."""
    if not is_on:
        return None
    return html.Div(
        [
            html.I(className="bi bi-grid-1x2-fill boardroom-mode-cue-icon"),
            html.Span("Boardroom Mode", className="boardroom-mode-cue-text"),
            html.Button(
                html.I(className="bi bi-x"),
                id="boardroom-mode-clear",
                n_clicks=0,
                className="boardroom-mode-cue-clear",
                title="Turn off Boardroom Mode",
            ),
        ],
        className="boardroom-mode-cue-pill",
    )


_BM_RISK_WIDTH = {"high": 92, "med": 62, "medium": 62, "low": 32}


def _bm_tone(value: str) -> str:
    """Clamp an arbitrary tone string to the four supported classes."""
    v = (value or "neutral").strip().lower()
    return v if v in ("good", "warn", "danger", "neutral") else "neutral"


def _bm_kpi(card: dict):
    tone = _bm_tone(card.get("tone"))
    icon = card.get("icon") or "bi bi-graph-up"
    delta = card.get("delta") or ""
    children = [
        html.Div(html.I(className=icon), className=f"bm-kpi-icon {tone}"),
        html.Div(
            [
                html.Div(card.get("label", ""), className="bm-kpi-label"),
                html.Div(card.get("value", ""), className="bm-kpi-value"),
            ]
            + ([html.Div(delta, className=f"bm-kpi-delta {tone}")] if delta else []),
            className="bm-kpi-copy",
        ),
    ]
    return html.Div(children, className="bm-kpi-card")


def _bm_commentary(section: dict):
    points = section.get("points") or []
    return html.Div(
        [
            html.Div(section.get("heading", ""), className="bm-commentary-heading"),
            html.Ul([html.Li(p) for p in points], className="bm-commentary-list"),
        ],
        className="bm-commentary-section",
    )


def _bm_risk(item: dict):
    tone = _bm_tone(item.get("tone"))
    severity = item.get("severity", "")
    width = _BM_RISK_WIDTH.get(severity.strip().lower(), 50)
    return html.Div(
        [
            html.Div(
                [
                    html.Span(item.get("label", ""), className="bm-risk-name"),
                    html.Span(severity, className=f"bm-risk-pill {tone}"),
                ],
                className="bm-risk-head",
            ),
            html.Div(
                html.Div(className=f"bm-risk-fill {tone}", style={"width": f"{width}%"}),
                className="bm-risk-track",
            ),
        ],
        className="bm-risk-item",
    )


def boardroom_card(digest: dict, figures: list | None = None, idx: int = 0):
    """The inline Boardroom dashboard: one self-contained card for an answer.

    Layout: header (title + Export to PPT) · KPI row · [commentary rail | charts]
    · risks. `digest` is the `BoardroomDigest` dict from the boardroom_node;
    `figures` are pre-built plotly figures for the attached chart specs.
    """
    digest = digest or {}
    figures = figures or []

    kpis = digest.get("kpis") or []
    commentary = digest.get("commentary") or []
    risks = digest.get("risks") or []
    headline = (digest.get("headline") or "").strip()

    # ── Header ───────────────────────────────────────────────────────────────
    header = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-grid-1x2-fill"),
                            html.Span("Boardroom"),
                        ],
                        className="bm-eyebrow",
                    ),
                    html.Div(
                        digest.get("title", "Executive Summary"), className="bm-title"
                    ),
                    html.Div(digest.get("subtitle", ""), className="bm-subtitle")
                    if digest.get("subtitle")
                    else None,
                ],
                className="bm-title-block",
            ),
            html.Button(
                [html.I(className="bi bi-file-earmark-slides"), "Export to PPT"],
                id={"type": "boardroom-export", "idx": idx},
                n_clicks=0,
                className="bm-export-btn",
                disabled=True,
                title="PowerPoint export is coming soon",
            ),
        ],
        className="bm-header",
    )

    # ── KPI row ──────────────────────────────────────────────────────────────
    kpi_row = (
        html.Div([_bm_kpi(c) for c in kpis], className="bm-kpi-grid") if kpis else None
    )

    # ── Commentary rail (left) ───────────────────────────────────────────────
    rail_children = []
    if headline:
        rail_children.append(html.Div(headline, className="bm-headline"))
    rail_children.extend(_bm_commentary(s) for s in commentary)
    if risks:
        rail_children.append(
            html.Div(
                [html.Div("Risks & watch items", className="bm-commentary-heading")]
                + [_bm_risk(r) for r in risks],
                className="bm-risk-block",
            )
        )
    commentary_rail = html.Div(rail_children, className="bm-rail")

    # ── Charts (right) ───────────────────────────────────────────────────────
    chart_panels = [
        html.Div(
            dcc.Graph(
                figure=fig,
                className="bm-chart-fig",
                config={"displayModeBar": False, "responsive": True},
            ),
            className="bm-chart-panel",
        )
        for fig in figures
    ]
    charts_col = (
        html.Div(chart_panels, className="bm-charts")
        if chart_panels
        else html.Div(
            html.Div(
                [
                    html.I(className="bi bi-bar-chart-line"),
                    html.Span("No chart for this view"),
                ],
                className="bm-charts-empty",
            ),
            className="bm-charts",
        )
    )

    body = html.Div([commentary_rail, charts_col], className="bm-body")

    return html.Div(
        [header, kpi_row, body] if kpi_row is not None else [header, body],
        className="message boardroom-card",
    )


def custom_peers_modal():
    """Dialog to pin a hand-picked peer set for the current conversation.

    Flow → Country → Carrier cascade, then a multi-select of every other carrier
    (Survey) / Carrier_Group (GPR) in that country. The callbacks live in
    ui.callbacks; `is_open` is driven by the `custom-peers-open` store.
    """
    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle(
                    [
                        html.I(className="bi bi-people custom-peers-title-icon"),
                        "Custom Peers",
                    ]
                ),
                close_button=True,
            ),
            dbc.ModalBody(
                [
                    html.Div(
                        "Pin a peer set for this conversation. Peer comparisons "
                        "will use exactly these instead of the default peer group.",
                        className="custom-peers-subtitle",
                    ),
                    html.Div(
                        [
                            html.Label("Data", className="custom-peers-label"),
                            dbc.RadioItems(
                                id="custom-peers-flow",
                                options=[
                                    {"label": "Survey (Carrier)", "value": "survey"},
                                    {"label": "GPR (Carrier Group)", "value": "gpr"},
                                ],
                                value="gpr",
                                inline=True,
                                className="custom-peers-flow",
                            ),
                        ],
                        className="custom-peers-field",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Country", className="custom-peers-label"),
                                    dcc.Dropdown(
                                        id="custom-peers-country",
                                        placeholder="Select country",
                                        className="pitch-dropdown",
                                    ),
                                ],
                                className="custom-peers-field",
                            ),
                            html.Div(
                                [
                                    html.Label("Carrier", className="custom-peers-label"),
                                    dcc.Dropdown(
                                        id="custom-peers-carrier",
                                        placeholder="Select carrier",
                                        className="pitch-dropdown",
                                    ),
                                ],
                                className="custom-peers-field",
                            ),
                        ],
                        className="custom-peers-row",
                    ),
                    html.Div(
                        [
                            html.Label(
                                [
                                    "Peers",
                                    html.Span(
                                        id="custom-peers-count",
                                        className="custom-peers-count",
                                    ),
                                ],
                                className="custom-peers-label",
                            ),
                            dcc.Dropdown(
                                id="custom-peers-list",
                                placeholder="Select peers to benchmark against",
                                multi=True,
                                className="pitch-dropdown",
                            ),
                        ],
                        className="custom-peers-field",
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel",
                        id="custom-peers-cancel",
                        n_clicks=0,
                        className="custom-peers-cancel-btn",
                    ),
                    dbc.Button(
                        "Apply peers",
                        id="custom-peers-apply",
                        n_clicks=0,
                        className="custom-peers-apply-btn",
                        disabled=True,
                    ),
                ]
            ),
        ],
        id="custom-peers-modal",
        is_open=False,
        centered=True,
        backdrop=True,
        className="custom-peers-modal",
    )


def custom_peers_cue(custom_peers: dict | None):
    """The composer pill shown when a custom peer set is active (else nothing)."""
    custom_peers = custom_peers or {}
    peers = custom_peers.get("peers") or []
    carrier = custom_peers.get("carrier")
    if not peers or not carrier:
        return None
    flow_label = "GPR" if (custom_peers.get("flow") or "").lower() == "gpr" else "Survey"
    return html.Div(
        [
            html.Button(
                [
                    html.I(className="bi bi-people custom-peers-cue-icon"),
                    html.Span(
                        f"{len(peers)} custom peers · {carrier}",
                        className="custom-peers-cue-text",
                    ),
                    html.Span(flow_label, className="custom-peers-cue-flow"),
                ],
                id="custom-peers-edit",
                n_clicks=0,
                className="custom-peers-cue-body",
                title="Edit custom peers",
            ),
            html.Button(
                html.I(className="bi bi-x-lg"),
                id="custom-peers-clear",
                n_clicks=0,
                className="custom-peers-cue-clear",
                title="Clear custom peers",
            ),
        ],
        className="custom-peers-cue-pill",
    )


def pitch_question_card(index, question):
    return html.Div(
        [
            html.Div(
                [
                    html.Span(f"{index + 1}", className="pitch-question-index"),
                    dcc.Textarea(
                        id={"type": "pitch-question", "index": index},
                        value=question,
                        className="pitch-question-input",
                    ),
                ],
                className="pitch-question-row",
            ),
        ],
        className="pitch-question-card",
    )
