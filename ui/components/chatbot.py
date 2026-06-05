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
                                            dbc.Button(
                                                html.I(className="bi bi-plus-lg"),
                                                id="pitch-builder-btn",
                                                n_clicks=0,
                                                className="pitch-trigger-btn",
                                            ),
                                            dbc.Tooltip(
                                                "Pitch Builder",
                                                target="pitch-builder-btn",
                                                placement="top",
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
