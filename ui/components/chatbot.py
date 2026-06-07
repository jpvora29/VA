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
            dcc.Store(id="persist-sink", data={}),  # write-only sink for edit persistence
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
                                            # Top row: the (growable) text field.
                                            dcc.Textarea(
                                                id="user-input",
                                                placeholder="Ask anything",
                                                className="composer-input",
                                                rows=1,
                                            ),
                                            # Bottom toolbar: + actions on the left,
                                            # cues in the middle, send/stop on the right
                                            # (Codex-style composer footer).
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
                                                        label=html.I(
                                                            className="bi bi-plus-lg"
                                                        ),
                                                        direction="up",
                                                        caret=False,
                                                        toggleClassName="pitch-trigger-btn",
                                                        className="composer-add-wrap",
                                                    ),
                                                    # Visual cue (like Claude's Search
                                                    # pill) shown only while a custom
                                                    # peer set is pinned.
                                                    html.Div(
                                                        id="custom-peers-cue",
                                                        className="custom-peers-cue",
                                                    ),
                                                    # Armed-state pill for Boardroom
                                                    # Mode; next answer is a card.
                                                    html.Div(
                                                        id="boardroom-mode-cue",
                                                        className="boardroom-mode-cue",
                                                    ),
                                                    html.Div(
                                                        [
                                                            dbc.Button(
                                                                html.I(
                                                                    className="bi bi-arrow-up"
                                                                ),
                                                                id="send-btn",
                                                                n_clicks=0,
                                                                className="send-btn",
                                                            ),
                                                            dbc.Button(
                                                                html.I(
                                                                    className="bi bi-stop-fill"
                                                                ),
                                                                id="stop-btn",
                                                                n_clicks=0,
                                                                className="stop-btn",
                                                                style={"display": "none"},
                                                            ),
                                                        ],
                                                        className="composer-actions",
                                                    ),
                                                ],
                                                className="composer-toolbar",
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


def _bm_insight(card: dict):
    """A polished executive insight callout (narrative takeaway, not a metric)."""
    tone = _bm_tone(card.get("tone"))
    detail = card.get("detail") or ""
    return html.Div(
        [
            html.Div(
                html.I(className=card.get("icon") or "bi bi-lightbulb"),
                className=f"bm-insight-icon {tone}",
            ),
            html.Div(
                [
                    html.Div(card.get("headline", ""), className="bm-insight-headline"),
                    html.Div(detail, className="bm-insight-detail") if detail else None,
                ],
                className="bm-insight-copy",
            ),
        ],
        className=f"bm-insight-card {tone}",
    )


def _bm_battlecard(bc: dict):
    """An auto-generated competitive profile card for one carrier."""

    def _col(title, icon, items, kind):
        items = [i for i in (items or []) if i]
        if not items:
            return None
        return html.Div(
            [
                html.Div(
                    [html.I(className=icon), html.Span(title)],
                    className=f"bm-bc-col-title {kind}",
                ),
                html.Ul([html.Li(i) for i in items], className="bm-bc-list"),
            ],
            className="bm-bc-col",
        )

    cols = [
        _col("Strengths", "bi bi-hand-thumbs-up", bc.get("strengths"), "good"),
        _col("Weaknesses", "bi bi-hand-thumbs-down", bc.get("weaknesses"), "danger"),
        _col("Product gaps", "bi bi-grid-3x3-gap", bc.get("product_gaps"), "warn"),
    ]
    cols = [c for c in cols if c is not None]

    footer = (
        html.Div(
            [
                html.I(className="bi bi-chat-quote"),
                html.Span(bc.get("broker_perception")),
            ],
            className="bm-bc-perception",
        )
        if bc.get("broker_perception")
        else None
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                (bc.get("carrier") or "?")[:2].upper(),
                                className="bm-bc-avatar",
                            ),
                            html.Div(bc.get("carrier", ""), className="bm-bc-name"),
                        ],
                        className="bm-bc-id",
                    ),
                    html.Div(bc.get("peer_position", ""), className="bm-bc-position")
                    if bc.get("peer_position")
                    else None,
                ],
                className="bm-bc-head",
            ),
            html.Div(cols, className="bm-bc-cols") if cols else None,
            footer,
        ],
        className="bm-battlecard",
    )


def _bm_comparison(comp: dict):
    """A side-by-side comparison panel: subjects as columns, metrics as rows."""
    subjects = comp.get("subjects") or []
    metrics = comp.get("metrics") or []
    if not subjects or not metrics:
        return None
    highlight = comp.get("highlight", 0)

    # Header: a blank corner cell + one column per subject.
    header = html.Div(
        [html.Div("", className="bm-cmp-cell bm-cmp-corner")]
        + [
            html.Div(
                s,
                className="bm-cmp-cell bm-cmp-subject"
                + (" highlight" if i == highlight else ""),
            )
            for i, s in enumerate(subjects)
        ],
        className="bm-cmp-row bm-cmp-head",
    )

    rows = []
    for m in metrics:
        values = m.get("values") or []
        tones = m.get("tones") or []
        cells = [html.Div(m.get("label", ""), className="bm-cmp-cell bm-cmp-metric")]
        for i in range(len(subjects)):
            val = values[i] if i < len(values) else "—"
            tone = _bm_tone(tones[i]) if i < len(tones) else "neutral"
            cells.append(
                html.Div(
                    val,
                    className=f"bm-cmp-cell bm-cmp-value {tone}"
                    + (" highlight" if i == highlight else ""),
                )
            )
        rows.append(html.Div(cells, className="bm-cmp-row"))

    # Drive the CSS grid column count off the subject count.
    grid_style = {
        "gridTemplateColumns": f"minmax(120px, 1.4fr) repeat({len(subjects)}, minmax(90px, 1fr))"
    }
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-layout-split"),
                    html.Span("Side-by-side comparison"),
                ],
                className="bm-section-title",
            ),
            html.Div(
                [header] + rows,
                className="bm-cmp-grid",
                style=grid_style,
            ),
        ],
        className="bm-comparison",
    )


_TONE_RGB = {
    "good": "31,157,85",
    "warn": "240,180,41",
    "danger": "197,53,50",
    "neutral": "11,75,255",
}


def _tone_rgba(tone: str, opacity: float) -> str:
    return f"rgba({_TONE_RGB.get(_bm_tone(tone), _TONE_RGB['neutral'])},{round(opacity, 2)})"


def _bm_widget(title: str, icon: str, body, extra_class: str = ""):
    """Standard widget shell: a section title + a panel — keeps every analytic
    widget visually consistent with the rest of the dashboard."""
    return html.Div(
        [
            html.Div(
                [html.I(className=icon), html.Span(title)],
                className="bm-section-title",
            ),
            body,
        ],
        className=("bm-widget " + extra_class).strip(),
    )


def _bm_timeline(events: list):
    """Insight Timeline — major carrier movements across periods."""
    cat_icon = {
        "premium": "bi bi-cash-stack",
        "rank": "bi bi-trophy",
        "score": "bi bi-stars",
        "product": "bi bi-box-seam",
        "other": "bi bi-dot",
    }
    items = []
    for e in events:
        tone = _bm_tone(e.get("tone"))
        items.append(
            html.Div(
                [
                    html.Div(e.get("period", ""), className="bm-tl-period"),
                    html.Div(className=f"bm-tl-dot {tone}"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.I(className=cat_icon.get(e.get("category", "other"), "bi bi-dot")),
                                    html.Span(e.get("title", "")),
                                ],
                                className="bm-tl-title",
                            ),
                            html.Div(e.get("detail", ""), className="bm-tl-detail")
                            if e.get("detail")
                            else None,
                        ],
                        className="bm-tl-body",
                    ),
                ],
                className="bm-tl-item",
            )
        )
    return _bm_widget(
        "Insight timeline", "bi bi-hourglass-split", html.Div(items, className="bm-timeline")
    )


def _bm_opportunity_map(m: dict):
    """Market Opportunity Map — country×product whitespace/growth heatmap."""
    rows = m.get("rows") or []
    cols = m.get("cols") or []
    cells = m.get("cells") or []
    if not rows or not cols:
        return None
    lut = {(c.get("row"), c.get("col")): c for c in cells}
    grid_style = {
        "gridTemplateColumns": f"minmax(96px, 1.3fr) repeat({len(cols)}, minmax(56px, 1fr))"
    }
    header = [html.Div("", className="bm-map-cell bm-map-corner")] + [
        html.Div(c, className="bm-map-cell bm-map-colhead") for c in cols
    ]
    body_rows = [html.Div(header, className="bm-map-row bm-map-head")]
    for r in rows:
        cells_row = [html.Div(r, className="bm-map-cell bm-map-rowhead")]
        for c in cols:
            cell = lut.get((r, c))
            if cell:
                inten = max(0, min(100, int(cell.get("intensity", 0))))
                tone = _bm_tone(cell.get("tone"))
                cells_row.append(
                    html.Div(
                        str(inten),
                        className=f"bm-map-cell bm-map-val {tone}",
                        style={"backgroundColor": _tone_rgba(tone, 0.12 + 0.0085 * inten)},
                        title=cell.get("note") or f"{r} · {c}: {inten}",
                    )
                )
            else:
                cells_row.append(html.Div("", className="bm-map-cell bm-map-empty"))
        body_rows.append(html.Div(cells_row, className="bm-map-row"))
    grid = html.Div(body_rows, className="bm-map-grid", style=grid_style)
    legend = (
        html.Div(m.get("legend", ""), className="bm-map-legend") if m.get("legend") else None
    )
    return _bm_widget(
        "Market opportunity map", "bi bi-globe-americas", html.Div([grid, legend])
    )


def _bm_radar(ops: list):
    """Opportunity Radar — ranked whitespace gaps (carrier low, Marsh/peers high)."""
    ops = sorted(ops, key=lambda o: o.get("gap_score", 0), reverse=True)
    items = []
    for o in ops:
        tone = _bm_tone(o.get("tone"))
        gap = max(0, min(100, int(o.get("gap_score", 0))))
        levels = None
        if o.get("carrier_level") or o.get("peer_level"):
            levels = html.Div(
                [
                    html.Span(
                        [html.I(className="bi bi-building"), f"Carrier: {o.get('carrier_level', '—')}"],
                        className="bm-opp-meta",
                    ),
                    html.Span(
                        [html.I(className="bi bi-people"), f"Marsh/Peers: {o.get('peer_level', '—')}"],
                        className="bm-opp-meta",
                    ),
                ],
                className="bm-opp-levels",
            )
        items.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(o.get("area", ""), className="bm-opp-area"),
                            html.Span((o.get("dimension", "") or "").title(), className="bm-opp-dim"),
                            html.Span(str(gap), className=f"bm-opp-score {tone}"),
                        ],
                        className="bm-opp-head",
                    ),
                    html.Div(
                        html.Div(className=f"bm-opp-fill {tone}", style={"width": f"{gap}%"}),
                        className="bm-opp-track",
                    ),
                    levels,
                    html.Div(
                        [html.I(className="bi bi-arrow-right-circle"), html.Span(o.get("recommendation", ""))],
                        className="bm-opp-rec",
                    )
                    if o.get("recommendation")
                    else None,
                ],
                className="bm-opp-item",
            )
        )
    return _bm_widget("Opportunity radar", "bi bi-radar", html.Div(items, className="bm-opp-list"))


def _bm_positioning(mx: dict):
    """Peer Positioning Matrix — 2x2 premium strength vs broker perception."""
    pts = mx.get("points") or []
    if not pts:
        return None
    dots = []
    for p in pts:
        x = max(0, min(100, int(p.get("premium_strength", 50))))
        y = max(0, min(100, int(p.get("broker_perception", 50))))
        tone = _bm_tone(p.get("tone"))
        sub = " subject" if p.get("is_subject") else ""
        dots.append(
            html.Div(
                [
                    html.Span(className=f"bm-pos-dot {tone}{sub}"),
                    html.Span(p.get("label", ""), className="bm-pos-label"),
                ],
                className="bm-pos-point",
                style={"left": f"{x}%", "bottom": f"{y}%"},
                title=f"{p.get('label', '')}: premium {x}, perception {y}",
            )
        )
    plot = html.Div(
        [
            html.Div("Emerging", className="bm-pos-q q-tl"),
            html.Div("Strong", className="bm-pos-q q-tr"),
            html.Div("Underperforming", className="bm-pos-q q-bl"),
            html.Div("Vulnerable", className="bm-pos-q q-br"),
            html.Div(className="bm-pos-axis-x"),
            html.Div(className="bm-pos-axis-y"),
        ]
        + dots,
        className="bm-pos-plot",
    )
    wrap = html.Div(
        [
            html.Div("Broker perception →", className="bm-pos-ylab"),
            html.Div(plot, className="bm-pos-plotwrap"),
            html.Div("Premium strength →", className="bm-pos-xlab"),
        ],
        className="bm-pos-wrap",
    )
    note = html.Div(mx.get("note", ""), className="bm-pos-note") if mx.get("note") else None
    return _bm_widget("Peer positioning matrix", "bi bi-grid-3x3", html.Div([wrap, note]))


def boardroom_card(digest: dict, figures: list | None = None, idx: int = 0):
    """The inline Boardroom dashboard: one self-contained, multi-page card.

    The content is split across pages (Summary · Visuals · Opportunities ·
    Battlecards) with a pager below, so the first page stays clean and charts /
    heavy analytics live on later pages. Empty pages are dropped. `digest` is the
    `BoardroomDigest` dict from boardroom_node; `figures` are prebuilt plotly figs.
    """
    digest = digest or {}
    figures = figures or []

    kpis = digest.get("kpis") or []
    insights = digest.get("insights") or []
    commentary = digest.get("commentary") or []
    risks = digest.get("risks") or []
    headline = (digest.get("headline") or "").strip()
    comparison = digest.get("comparison")
    battlecards = digest.get("battlecards") or []

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

    # ── Executive insight cards ──────────────────────────────────────────────
    insights_row = (
        _bm_widget(
            "Executive insights",
            "bi bi-stars",
            html.Div([_bm_insight(c) for c in insights], className="bm-insight-grid"),
        )
        if insights
        else None
    )

    # ── Editable commentary (headline + sections) ────────────────────────────
    comm_children = []
    if headline:
        comm_children.append(html.Div(headline, className="bm-headline"))
    comm_children.extend(_bm_commentary(s) for s in commentary)
    commentary_block = None
    if comm_children:
        commentary_block = _bm_widget(
            "Commentary",
            "bi bi-card-text",
            html.Div(
                [
                    html.Div(
                        comm_children,
                        className="bm-rail-editable",
                        contentEditable="true",
                    ),
                    html.Div(
                        [
                            html.I(className="bi bi-pencil"),
                            html.Span("Editable — click any line to refine"),
                        ],
                        className="bm-edit-hint",
                    ),
                ]
            ),
            extra_class="bm-commentary-widget",
        )

    risks_block = (
        _bm_widget(
            "Risks & watch items",
            "bi bi-exclamation-triangle",
            html.Div([_bm_risk(r) for r in risks], className="bm-risk-block"),
        )
        if risks
        else None
    )

    comparison_panel = _bm_comparison(comparison) if comparison else None

    # ── Charts (smaller, widget-styled grid) ─────────────────────────────────
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
    charts_widget = (
        _bm_widget(
            "Charts",
            "bi bi-bar-chart-line",
            html.Div(chart_panels, className="bm-charts-grid"),
        )
        if chart_panels
        else None
    )

    # ── Carrier battlecards ──────────────────────────────────────────────────
    battlecards_section = (
        _bm_widget(
            "Carrier battlecards",
            "bi bi-clipboard-data",
            html.Div([_bm_battlecard(b) for b in battlecards], className="bm-bc-grid"),
        )
        if battlecards
        else None
    )

    # ── Query-dependent advanced widgets ─────────────────────────────────────
    positioning_panel = _bm_positioning(digest.get("positioning")) if digest.get("positioning") else None
    opp_map_panel = _bm_opportunity_map(digest.get("opportunity_map")) if digest.get("opportunity_map") else None
    radar_panel = _bm_radar(digest.get("opportunities")) if digest.get("opportunities") else None
    timeline_panel = _bm_timeline(digest.get("timeline")) if digest.get("timeline") else None

    # ── Compose pages (drop empties) ─────────────────────────────────────────
    def _clean(items):
        return [x for x in items if x is not None]

    page_specs = [
        ("Summary", "bi bi-clipboard2-pulse",
         _clean([kpi_row, insights_row, commentary_block, risks_block, comparison_panel])),
        ("Visuals", "bi bi-graph-up-arrow",
         _clean([charts_widget, positioning_panel, opp_map_panel])),
        ("Opportunities", "bi bi-compass",
         _clean([radar_panel, timeline_panel])),
        ("Battlecards", "bi bi-clipboard-data",
         _clean([battlecards_section])),
    ]
    pages = [(t, ic, secs) for (t, ic, secs) in page_specs if secs]
    if not pages:
        pages = [
            (
                "Summary",
                "bi bi-clipboard2-pulse",
                [html.Div(
                    [html.I(className="bi bi-info-circle"), html.Span("No structured view for this answer.")],
                    className="bm-charts-empty",
                )],
            )
        ]

    page_divs = [
        html.Div(
            secs,
            id={"type": "bm-page", "idx": idx, "page": p},
            className="bm-page",
            style=({} if p == 0 else {"display": "none"}),
        )
        for p, (t, ic, secs) in enumerate(pages)
    ]

    children = [header, html.Div(page_divs, className="bm-pages")]

    if len(pages) > 1:
        marks = {p: {"label": t} for p, (t, ic, secs) in enumerate(pages)}
        pager = html.Div(
            [
                html.Div(
                    [
                        html.I(className="bi bi-layers-half"),
                        html.Span(f"{len(pages)} pages · drag the slider to navigate"),
                    ],
                    className="bm-pager-caption",
                ),
                dcc.Slider(
                    id={"type": "bm-slider", "idx": idx},
                    min=0,
                    max=len(pages) - 1,
                    step=None,
                    value=0,
                    marks=marks,
                    included=False,
                    className="bm-slider",
                ),
            ],
            className="bm-pager",
        )
        children.append(pager)

    return html.Div(children, className="message boardroom-card")


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
