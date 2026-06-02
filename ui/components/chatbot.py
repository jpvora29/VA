from datetime import datetime

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from document_builder.report_generator import PITCH_THEMES


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


def welcome_hero():
    """Empty-state hero shown before the first message is sent."""
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
                            f"{_greeting()}, ",
                            html.Span(
                                "let's dig into the data",
                                className="welcome-accent",
                            ),
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
                [
                    suggestion_chip(question, icon, index)
                    for index, (icon, question) in enumerate(STARTER_SUGGESTIONS)
                ],
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


def chatbot_page():

    return html.Div(
        [
            dcc.Store(id="chat-store", data={}),
            dcc.Store(id="trigger-gpt", data=False),  # flag to run GPT call
            dcc.Store(id="is-thinking", data=False),  # flag to show loader
            dcc.Store(id="has-chart", data=False),
            dcc.Store(id="overflow_data", data={}),
            dbc.Container(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Div(
                                        id="chat-box",
                                        className="chat-bot-text-area",
                                        children=[welcome_hero()],
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
                                    html.Div(
                                        [
                                            dbc.InputGroup(
                                                [
                                                    dbc.Button(
                                                        [
                                                            html.I(
                                                                className="bi bi-window-sidebar",
                                                                style={
                                                                    "paddingRight": "8px"
                                                                },
                                                            ),
                                                            "Pitch Builder",
                                                        ],
                                                        id="pitch-builder-btn",
                                                        n_clicks=0,
                                                        className="pitch-builder-btn",
                                                    ),
                                                    dbc.Input(
                                                        id="user-input",
                                                        placeholder="Ask anything",
                                                        debounce=True,
                                                    ),
                                                    dbc.Button(
                                                        html.I(
                                                            className="bi bi-arrow-up-circle-fill",
                                                            style={
                                                                "fontSize": "30px",
                                                                "color": "black",
                                                            },
                                                        ),
                                                        id="send-btn",
                                                        n_clicks=0,
                                                        className="send-btn",
                                                    ),
                                                ]
                                            ),
                                        ]
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
                                options=["performance_analyze"],
                                value="performance_analyze",
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
                    "width": "min(470px, 96vw)",
                    "height": "100vh",
                    "overflowY": "auto",
                    "background": "#f5f7fb",
                    "borderLeft": "1px solid rgba(12, 25, 58, 0.14)",
                    "boxShadow": "0 20px 48px rgba(10, 22, 54, 0.12)",
                    "transform": "translateX(100%)",
                    "transition": "transform 260ms cubic-bezier(.4, .0, .2,1)",
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
