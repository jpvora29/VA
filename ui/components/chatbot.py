from datetime import datetime

from dash import html, dcc
import dash_bootstrap_components as dbc
from core.answers.commands import COMMANDS
from core.peers import MIN_CUSTOM_PEERS
from document_builder.report_generator import PITCH_THEMES, theme_options
from ui.components.answer_actions import (
    AnswerContext,
    answer_footer,
    feedback_panel,
    next_question,
)
from ui.components.answer_lead import Lead, split_lead
from ui.components.contribution import contribution_panel
from ui.components.evidence import evidence_panel
from ui.components.provenance import provenance_drawer
from ui.components.scope_bar import scope_bar
from ui.components.turn import assistant_header, user_footer


# Example questions surfaced on the welcome screen and (mirrored) in the
# animated input placeholder. Keep these aligned with assets/typewriter.js.
#
# Each is (icon, OUTCOME, question). The outcome is what the reader is scanning
# for — four full sentences of near-identical shape are four things to read
# before choosing, and the reader is choosing a job, not a sentence. The question
# stays underneath because it is what actually gets asked, and a starter that
# hides the question it sends is a starter you cannot trust.
STARTER_SUGGESTIONS = [
    ("bi bi-pie-chart", "Share of wallet",
     "What is Zurich's Share of Wallet in Canada for Property?"),
    ("bi bi-graph-up-arrow", "Explain premium growth",
     "Show premium growth for Chubb across all product lines"),
    ("bi bi-people", "Compare peers",
     "How does AXA's broker score compare to peers this year?"),
    ("bi bi-bar-chart-line", "Explore market rates",
     "What is the market composite rate change for Asia this quarter?"),
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
    """A clickable question chip that ASKS the question.

    The question text rides in the id so a single pattern-matching callback can
    send it. Used for follow-ups, where the reader has already seen an answer and
    the chip is a continuation of it.
    """
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


def starter_chip(outcome: str, question: str, icon: str, idx: int = 0):
    """A starter, which LOADS the question into the composer rather than sending it.

    A starter is an example, and an example the reader cannot adjust before it
    runs is a coin flip: the scope is almost never quite theirs, and the only way
    to fix it used to be to wait for the wrong answer and retype the question.
    Loading it leaves the reader one edit away from their own question, with the
    example still telling them what this box can be asked.
    """
    return html.Button(
        [
            html.I(className=f"{icon} starter-chip-icon"),
            html.Span(
                [
                    html.Span(outcome, className="starter-chip-outcome"),
                    html.Span(question, className="starter-chip-question"),
                ],
                className="starter-chip-text",
            ),
        ],
        id={"type": "starter-chip", "idx": idx, "q": question},
        n_clicks=0,
        className="starter-chip",
        title=question,
    )


def clarify_questions_of(payload: dict) -> list[dict]:
    """Normalise an interrupt payload to a list of question dicts.

    The clarify gate sends `{"kind": "clarify", "questions": [...]}`; the
    custom-peer gate (and any legacy caller) sends one flat ClarifyQuestion
    dict — wrapped here as a single-question list with a stable id.
    """
    payload = payload or {}
    questions = payload.get("questions")
    if isinstance(questions, list) and questions:
        return [dict(q) for q in questions if isinstance(q, dict)]
    flat = dict(payload)
    flat.setdefault("id", "q0")
    return [flat]


def _clarify_answered(question: dict, answer: str) -> "html.Div":
    """A settled question, collapsed to one line: what was asked, what was picked.

    Its options are GONE, not disabled — a row of dead buttons above the question
    you are actually being asked is noise, and re-reading a settled choice is not
    what the card is for. The full prompt stays in the tooltip.
    """
    return html.Div(
        [
            html.I(className="bi bi-check-circle-fill clarify-done-icon"),
            html.Span(question.get("header") or "Answered", className="clarify-done-label"),
            html.Span(answer, className="clarify-done-value"),
        ],
        className="clarify-answered",
        title=question.get("question") or "",
    )


def _clarify_question_block(question: dict) -> "html.Div":
    """The OPEN question: badge, prompt, options, free-text row."""
    qid = str(question.get("id") or "q0")
    prompt = question.get("question") or "Could you clarify what you mean?"
    header = question.get("header") or "Quick check"
    options = question.get("options") or []

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
            id={"type": "clarify-option", "qid": qid, "value": opt.get("label", "")},
            n_clicks=0,
            className="clarify-option",
        )
        for opt in options
        if opt.get("label")
    ]

    children = [
        html.Div(
            [
                html.I(className="bi bi-question-lg clarify-card-icon"),
                html.Span(header, className="clarify-card-header"),
            ],
            className="clarify-card-badge",
        ),
        html.Div(prompt, className="clarify-card-question"),
    ]
    if option_buttons:
        children.append(html.Div(option_buttons, className="clarify-option-grid"))
    if question.get("allow_free_text", True):
        children.append(
            dbc.InputGroup(
                [
                    dbc.Input(
                        id={"type": "clarify-free-text", "qid": qid},
                        placeholder=(
                            "…or type your own answer" if option_buttons else "Type your answer"
                        ),
                        debounce=True,
                        className="clarify-free-input",
                    ),
                    dbc.Button(
                        html.I(className="bi bi-arrow-return-left"),
                        id={"type": "clarify-free-submit", "qid": qid},
                        n_clicks=0,
                        className="clarify-free-submit",
                    ),
                ],
                className="clarify-free-group",
            )
        )
    return html.Div(children, className="clarify-question-block")


def clarify_card(payload: dict):
    """Inline clarification card — ONE open question at a time.

    `payload` is the interrupt value: either `{"kind": "clarify", "questions":
    [...], "answers": {...}}` from the clarify gate, or one flat ClarifyQuestion
    dict (custom-peer gate).

    Two questions used to arrive side by side, which reads as a form to fill in
    rather than a conversation — and the second question is often only worth
    asking once the first is answered. So the card shows the questions already
    answered as one settled line each, then the FIRST unanswered one, and nothing
    below it. The graph still interrupts once with the whole list and resumes
    with every answer (`submit_clarification` holds the partial ones), so this is
    a change of pace, not of contract.
    """
    payload = payload or {}
    questions = clarify_questions_of(payload)
    answers = payload.get("answers") or {}

    def qid_of(q: dict) -> str:
        return str(q.get("id") or "q0")

    done = [q for q in questions if answers.get(qid_of(q))]
    remaining = [q for q in questions if not answers.get(qid_of(q))]
    open_question = remaining[0] if remaining else None

    children: list = []
    if len(questions) > 1:
        children.append(_clarify_steps(len(done), len(questions)))
    children.extend(_clarify_answered(q, answers[qid_of(q)]) for q in done)
    if open_question is not None:
        children.append(_clarify_question_block(open_question))
    return html.Div(children, className="message clarify-card")


def _clarify_steps(done: int, total: int):
    """Where the reader is in the sequence: "Question 2 of 2", plus a pip each."""
    return html.Div(
        [
            html.Span(
                f"Question {min(done + 1, total)} of {total}",
                className="clarify-step-label",
            ),
            html.Div(
                [
                    html.Span(
                        className="clarify-pip" + (" done" if i < done else
                                                   " current" if i == done else ""),
                    )
                    for i in range(total)
                ],
                className="clarify-pips",
            ),
        ],
        className="clarify-steps",
    )


# A small rotation of icons for LLM-tailored starter questions (which arrive as
# plain strings, without their own icon).
_STARTER_ICONS = [
    "bi bi-pie-chart",
    "bi bi-graph-up-arrow",
    "bi bi-people",
    "bi bi-bar-chart-line",
]


def _outcome_for(question: str, index: int) -> str:
    """An outcome label for a tailored starter, which arrives as a bare question.

    The LLM writes the question; the label is the first few words of it, so the
    grid still scans as a list of jobs rather than a wall of sentences, and the
    label can never claim something the question does not.
    """
    words = str(question or "").strip().rstrip("?").split()
    if not words:
        return "Ask a question"
    return " ".join(words[:4]) + ("…" if len(words) > 4 else "")


def starter_chips(starters: list[str] | None = None) -> list:
    """Chips for the welcome hero — tailored strings if given, else the defaults."""
    if starters:
        return [
            starter_chip(
                _outcome_for(question, index),
                question,
                _STARTER_ICONS[index % len(_STARTER_ICONS)],
                index,
            )
            for index, question in enumerate(starters)
        ]
    return [
        starter_chip(outcome, question, icon, index)
        for index, (icon, outcome, question) in enumerate(STARTER_SUGGESTIONS)
    ]


def welcome_hero(name: str = "", starters: list[str] | None = None):
    """Empty-state hero shown before the first message is sent.

    Deliberately small. The hero used to fill the first screen — a floating
    badge, a display-size greeting, a three-line explanation and four full
    sentences — which put the composer at the bottom of a page about itself. The
    first thing on this screen is the question, so the greeting is one line, the
    explanation is one line, and the starters are labels.
    """
    greeting = f"{_greeting()}, "
    accent = name.strip() if name and name.strip() else "let's dig into the data"
    return html.Div(
        [
            html.Div(
                [
                    html.H1(
                        [
                            greeting,
                            html.Span(accent, className="welcome-accent"),
                        ],
                        className="welcome-title",
                    ),
                    html.P(
                        "Ask about premium, Share of Wallet, broker sentiment, peer "
                        "benchmarks or market rates — in plain English.",
                        className="welcome-subtitle",
                    ),
                ],
                className="welcome-head",
            ),
            html.Div("Start with one of these", className="welcome-suggest-label"),
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


def _answer_body(content: str, idx: int, editing: bool, className: str = ""):
    """The commentary — editable IN PLACE when the pencil is on.

    Editing happens where the words are. The first attempt swapped the whole card
    for a Markdown source box, which meant losing sight of the chart and the
    figures you were editing ABOUT, and reading as a dialog rather than as your
    own document. Here the card stays exactly as it is and the prose becomes
    typeable, with the save/discard pair appearing under it.

    Round-tripping is handled at save: a clientside serialiser walks the edited
    HTML back to Markdown (see `ui.callbacks`), so headings and points survive
    rather than collapsing into one paragraph the way raw contentEditable text
    would.
    """
    body = dcc.Markdown(content, className=className) if className else dcc.Markdown(content)
    if not editing:
        return html.Div(body, id={"type": "answer-body", "idx": idx})
    return html.Div(
        [
            html.Div(
                body,
                id={"type": "answer-body", "idx": idx},
                className="answer-body-editing",
                contentEditable="true",
                # The clientside serialiser finds the edited region by this
                # attribute rather than by parsing a pattern-matching id string.
                **{"data-answer-body": str(idx)},
            ),
            html.Div(
                [
                    html.Span(
                        [html.I(className="bi bi-pencil-fill"), "Editing — type over anything"],
                        className="answer-edit-flag",
                    ),
                    html.Button(
                        "Discard",
                        id={"type": "answer-edit-cancel", "idx": idx},
                        n_clicks=0,
                        className="answer-edit-btn ghost",
                    ),
                    html.Button(
                        [html.I(className="bi bi-check2"), "Save"],
                        id={"type": "answer-edit-save", "idx": idx},
                        n_clicks=0,
                        className="answer-edit-btn primary",
                    ),
                ],
                className="answer-edit-bar",
            ),
        ],
        className="answer-body-wrap",
    )


def answer_scope(scope: list | None):
    """The filters THIS answer was built from, stated on the answer itself.

    Scope used to be a bar above the composer. That bar described the most recent
    turn wherever you were in the transcript, so scrolling back to an older answer
    told you the scope of a different one — and it sat directly above the input,
    where it competed with the question being typed. On the answer, each set of
    pills belongs to the answer it is printed under, and scrolls away with it.
    """
    bar = scope_bar(scope, compact=True)
    return html.Div(bar, className="answer-scope") if bar is not None else None


def _period_of(scope: list | None) -> str:
    """The timeframe this answer ran under, read off its own scope pills."""
    for chip in scope or []:
        if chip.get("key") in ("period", "timeframe", "year", "quarter"):
            return str(chip.get("value") or "")
    return ""


def _lead_block(lead: Lead, figures: list):
    """The finding, set as the finding: one line, its qualifier, its key numbers."""
    if not lead.has_headline and not figures:
        return None
    return html.Div(
        [
            html.H2(lead.headline, className="answer-headline")
            if lead.has_headline
            else None,
            html.P(lead.standfirst, className="answer-standfirst")
            if lead.standfirst
            else None,
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(figure.value, className="answer-figure-value"),
                            html.Div(figure.label, className="answer-figure-label"),
                        ],
                        className="answer-figure",
                    )
                    for figure in figures
                ],
                className="answer-figures",
            )
            if figures
            else None,
        ],
        className="answer-lead",
    )


def ai_message(
    content: str,
    is_insight: bool,
    idx: int = 0,
    *,
    question: str = "",
    route: str = "",
    shape: str = "",
    has_rows: bool = False,
    scope: list | None = None,
    provenance: dict | None = None,
    evidence: list | None = None,
    contribution: dict | None = None,
    card_idx: int | None = None,
    pane_ids: list | None = None,
    editing: bool = False,
    ts: str = "",
    source: str = "",
    followup: str = "",
):
    """One turn, whole: who answered, and everything that answer produced.

    Reading order is the order an analyst works in — who wrote it and from what,
    the scope it ran under, the finding, the numbers it turns on, the evidence,
    what drove it, how it was calculated, and only then what to do next:

        header -> scope -> FINDING -> figures -> prose -> chart / table
               -> drivers -> source & calculation -> actions -> next question

    Three things about that order are the point.

    *The header is outside the card.* An answer with no attribution reads as the
    page talking to itself; the mark, the dataset and the time say who is
    accountable for the number, and they belong above the thing they vouch for.

    *The finding is set as the finding.* The answer's own first sentence is
    lifted out and set large (:mod:`ui.components.answer_lead`) — nothing is
    written or dropped, it is the same words at a size that matches their job.
    While the prose is being REWRITTEN the split is suspended, because the
    serialiser saves one editable region and would otherwise drop the headline.

    *The chart is in the card.* It used to be a separate message below the
    answer, at a different width, which read as two unrelated things and made the
    card look broken. It is one card because it is one answer. (It is also in
    the analysis panel, which is the copy that does not scroll away —
    :mod:`ui.components.analysis_dock`.)

    Copy, the pin, the next steps and the thumbs live in ONE row at the foot —
    see :mod:`ui.components.answer_actions`. The feedback panel is mounted hidden
    and revealed by a thumbs-down.

    The "Consulting Insight" badge is gone: the turn header names the writer on
    every answer, so a second label saying this one is an insight was telling the
    reader something the card already looked like.
    """
    ctx = AnswerContext(
        idx=idx,
        question=question,
        route=route,
        shape=shape,
        has_rows=has_rows,
        is_insight=is_insight,
        has_analysis=bool(evidence) or bool((contribution or {}).get("drivers")),
    )
    pills = answer_scope(scope)
    views = evidence_panel(evidence or [], idx if card_idx is None else card_idx,
                           pane_ids or []) if evidence else None
    drivers = contribution_panel(contribution)
    # Between the prose and the actions: the answer states where it came from
    # before it offers you somewhere to take it.
    drawer = provenance_drawer(provenance, period=_period_of(scope))
    footer = answer_footer(ctx, content=content)
    panel = feedback_panel(idx)
    # While the prose is being rewritten it must be ONE editable region, or the
    # serialiser saves the body and silently drops the headline above it.
    lead = Lead(body=content) if editing else split_lead(content)
    # A single source for the headline and prose. Independent driver tiles can
    # describe another cut; keep those numbers in their own driver panel.
    head = _lead_block(lead, [])
    # A card carrying a chart or a table needs the room; a bare paragraph does
    # not, and stretching every answer to full width makes short ones look empty.
    wide = " has-evidence" if (views is not None or drivers is not None) else ""

    card_class = "message insight-card" if is_insight else "message gpt-message"
    body_class = "insight-card-body" if is_insight else ""
    card = html.Div(
        [
            pills,
            head,
            _answer_body(lead.body, idx, editing, className=body_class),
            views,
            drivers,
            drawer,
            footer,
            next_question(followup, idx),
            panel,
        ],
        className=card_class + wide,
    )
    return html.Div(
        [assistant_header(source=source, ts=ts), card],
        className="turn turn-assistant",
    )


def user_message(content: str, *, ts: str = "", initial: str = ""):
    """Render a user turn with a hover-reveal copy action.

    Mirrors `ai_message`'s native `dcc.Clipboard` copy so the human side of the
    conversation gets the same affordance. The bubble is position:relative so the
    copy chip can sit at its corner.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Span(content, className="user-message-text"),
                    dcc.Clipboard(content=content, title="Copy", className="msg-copy"),
                ],
                className="message user-message",
            ),
            user_footer(initial=initial, ts=ts),
        ],
        className="turn turn-user",
    )


def command_menu():
    """The task list, revealed the moment the user types "/".

    A blank prompt box asks people to guess what the product can do, and most
    guess low — they type a lookup, get a number, and never learn the same box
    will brief them or decompose a movement. This is that capability list, made
    typeable.

    Every row is rendered once and shown/hidden by a clientside filter, so the
    menu costs no round trip per keystroke.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.I(className=f"{command.icon} cmd-icon"),
                    html.Span(command.label, className="cmd-name"),
                    html.Span(command.hint, className="cmd-hint"),
                ],
                id={"type": "cmd-item", "name": command.name},
                n_clicks=0,
                className="cmd-item",
            )
            for command in COMMANDS
        ],
        id="command-menu",
        className="command-menu",
        style={"display": "none"},
    )


def _tool_item(item_id: str, icon: str, label: str, hint: str):
    """One row of the Tools menu: what it is, and what it does for you."""
    return dbc.DropdownMenuItem(
        [
            html.I(className=f"{icon} composer-menu-icon"),
            html.Span(
                [
                    html.Span(label, className="composer-menu-name"),
                    html.Span(hint, className="composer-menu-hint"),
                ],
                className="composer-menu-text",
            ),
        ],
        id=item_id,
        n_clicks=0,
    )


def chatbot_page(username: str = "", starters: list[str] | None = None):

    return html.Div(
        [
            dcc.Store(id="chat-store", data={}),
            dcc.Store(id="chat-cursor", data={}),
            dcc.Store(id="job-event", data={}),
            dcc.Store(id="chat-job-ack", data=None),
            dcc.Store(id="chat-load-ack", data=None),
            dcc.Store(id="conversation-load", data={}),
            dcc.Store(id="chat-render", data={}),
            html.Div("Loading conversation…", id="chat-loading", hidden=True,
                     role="status", className="chat-loading"),
            dcc.Store(id="trigger-gpt", data=False),  # flag to run GPT call
            dcc.Store(id="trigger-resume", data=False),  # flag to resume a paused HITL thread
            dcc.Store(id="is-thinking", data=False),  # flag to show loader
            dcc.Store(id="has-chart", data=False),
            dcc.Store(id="overflow_data", data={}),
            dcc.Store(id="feedback-sink", data={}),  # write-only sink for thumb clicks
            dcc.Store(id="persist-sink", data={}),  # write-only sink for edit persistence
            # Which answer (if any) is open for rewriting. One at a time.
            dcc.Store(id="answer-editing", data=None),
            # The edited Markdown, handed from the browser to the server.
            dcc.Store(id="answer-edit-buffer", data=None),
            # Polls the in-process streaming job for live status + completion;
            # enabled by launch_new_job / launch_resume_job. A short cadence makes
            # the answer flow in small increments (Claude-like) instead of landing
            # in chunky ~third-second bursts — the read is in-memory, so the cost
            # of polling more often is negligible.
            dcc.Interval(id="job-poll", interval=500, n_intervals=0, disabled=True),
            # Which answer the analysis panel is holding open (None means it
            # follows the newest), and how the two columns are arranged.
            # Below the split breakpoint the two columns cannot both fit, so they
            # become two views of one workspace. Hidden above it.
            html.Div(
                [
                    html.Div(
                        dbc.Container(
                            [
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            [
                                                # ONE scroll viewport holds the transcript AND
                                                # the streaming draft. They used to be siblings
                                                # of the scroller, so a growing draft was laid
                                                # out over the answer above it and the reader
                                                # lost the message they were still reading.
                                                html.Div(
                                                    [
                                                        html.Div(
                                                            id="chat-box",
                                                            className="chat-bot-text-area",
                                                            children=[welcome_hero(username, starters)],
                                                        ),
                                                        # The final answer streams here token by
                                                        # token while the turn runs; poll_job
                                                        # clears it once the committed answer
                                                        # lands in chat-box.
                                                        html.Div(id="live-draft", className="live-draft"),
                                                    ],
                                                    id="chat-viewport",
                                                    className="chat-viewport",
                                                ),
                                                dcc.Download(id="download-excel"),
                                            ],
                                            lg=12,
                                            md=12,
                                            xs=12,
                                        )
                                    ],
                                    className="chat-row",
                                ),
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            [
                                                # The scope of an answer is stated ON that
                                                # answer (see `ai_message`), not above the
                                                # composer: a bar here sat between the last
                                                # message and the input, described a turn that
                                                # had scrolled away, and pushed the question
                                                # under the status bar as it grew.
                                                #
                                                # Live status bar — shown only while a turn is
                                                # streaming. poll_job updates the stage label +
                                                # elapsed time; a clientside callback toggles
                                                # its visibility off is-thinking. The bar keeps
                                                # a shimmer track so a long turn still reads as
                                                # progress rather than a frozen pill.
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
                                                        html.Span(className="thinking-track"),
                                                    ],
                                                    id="thinking-bar",
                                                    className="thinking-bar",
                                                    style={"display": "none"},
                                                ),
                                                command_menu(),
                                                html.Div(
                                                    [
                                                        # Top row: the (growable) text field with
                                                        # the send/stop buttons aligned to it.
                                                        html.Div(
                                                            [
                                                                dcc.Textarea(
                                                                    id="user-input",
                                                                    placeholder="Ask anything",
                                                                    className="composer-input",
                                                                    rows=1,
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
                                                            className="composer-input-row",
                                                        ),
                                                        # Bottom toolbar: + actions and cues only;
                                                        # send stays up beside the input.
                                                        html.Div(
                                                            [
                                                                # Named, not a "+". The plus
                                                                # reads as "attach a file", so
                                                                # the three analytical
                                                                # workflows behind it were
                                                                # found by accident or not at
                                                                # all. Each item now says what
                                                                # it is FOR under its name,
                                                                # because "Boardroom Mode" is a
                                                                # label, not an explanation.
                                                                dbc.DropdownMenu(
                                                                    [
                                                                        _tool_item(
                                                                            "menu-pitch-builder",
                                                                            "bi bi-easel2",
                                                                            "Pitch Builder",
                                                                            "Build a themed one-page report",
                                                                        ),
                                                                        _tool_item(
                                                                            "menu-boardroom-mode",
                                                                            "bi bi-grid-1x2",
                                                                            "Boardroom Mode",
                                                                            "Answer the next question as a dashboard",
                                                                        ),
                                                                    ],
                                                                    id="composer-add-menu",
                                                                    label=[
                                                                        html.I(className="bi bi-sliders2"),
                                                                        html.Span(
                                                                            "Tools",
                                                                            className="composer-tool-label",
                                                                        ),
                                                                        html.I(
                                                                            className="bi bi-chevron-up composer-tool-caret"
                                                                        ),
                                                                    ],
                                                                    direction="up",
                                                                    caret=False,
                                                                    toggleClassName="composer-tool-btn",
                                                                    className="composer-add-wrap",
                                                                ),
                                                                # Armed-state pill for Boardroom
                                                                # Mode; next answer is a card.
                                                                html.Div(
                                                                    id="boardroom-mode-cue",
                                                                    className="boardroom-mode-cue",
                                                                ),
                                                                # The peer set is scope the user
                                                                # can edit, so it belongs with
                                                                # the other armed-state controls
                                                                # rather than with the read-only
                                                                # pills on the answer.
                                                                html.Div(
                                                                    id="custom-peers-cue",
                                                                    className="custom-peers-cue",
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
                        className="chat-column",
                    ),
                    # The evidence, kept in view while the conversation moves on.
                ],
                id="chat-workspace",
                className="chat-workspace show-chat",
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
                title="Download this board as an editable PowerPoint deck",
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
                        "will use exactly these instead of the default peer group. "
                        f"Pick at least {MIN_CUSTOM_PEERS} peers — a benchmark of "
                        "one or two carriers is close enough to naming them.",
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
                            # The under-minimum line, filled by
                            # `toggle_custom_peers_apply` while Apply stays disabled.
                            html.Div(id="custom-peers-min", className="custom-peers-min"),
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
    """The peer set, stated beside the question it will be answered against.

    This used to appear only once a custom set was pinned, which meant the
    default — every peer benchmark the app produced, all day — was never stated
    anywhere. A benchmark whose comparison set is invisible is a number you
    cannot check, so the control is always here: it says which set is in force
    and it is the way to change it.

    The ✕ exists only where there is something to clear; "Default" is not a state
    you can undo.
    """
    custom_peers = custom_peers or {}
    peers = custom_peers.get("peers") or []
    carrier = custom_peers.get("carrier")
    active = bool(peers and carrier)

    if active:
        flow_label = (
            "GPR" if (custom_peers.get("flow") or "").lower() == "gpr" else "Survey"
        )
        body = [
            html.I(className="bi bi-people custom-peers-cue-icon"),
            html.Span("Peers:", className="custom-peers-cue-key"),
            html.Span(
                f"{len(peers)} custom · {carrier}", className="custom-peers-cue-text"
            ),
            html.Span(flow_label, className="custom-peers-cue-flow"),
        ]
        title = f"{len(peers)} hand-picked peers for {carrier} — click to edit"
    else:
        body = [
            html.I(className="bi bi-people custom-peers-cue-icon"),
            html.Span("Peers:", className="custom-peers-cue-key"),
            html.Span("Default", className="custom-peers-cue-text"),
            html.I(className="bi bi-chevron-up composer-tool-caret"),
        ]
        title = "Benchmarking against the standard peer set — click to choose your own"

    return html.Div(
        [
            html.Button(
                body,
                id="custom-peers-edit",
                n_clicks=0,
                className="custom-peers-cue-body",
                title=title,
            ),
            html.Button(
                html.I(className="bi bi-x-lg"),
                id="custom-peers-clear",
                n_clicks=0,
                className="custom-peers-cue-clear",
                title="Clear custom peers",
            )
            if active
            else None,
        ],
        className="custom-peers-cue-pill" + ("" if active else " is-default"),
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
