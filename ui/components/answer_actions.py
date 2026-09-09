"""The row under an answer: what you can DO with it, and what was wrong with it.

Two problems, one strip of UI, because they are the same moment.

*Actions.* A conclusion used to end in the transcript. Every next step — put it
in a deck, raise it as a decision, pull the rows into Excel, ask what drove it —
lived in another workspace the user had to know about, navigate to, and retype
the finding into. Each destination already exists in this app; only the route
from an answer to it was missing. So the relevant action sits directly under the
answer, and the user never has to know which workspace owns the next step.

*Feedback.* A thumbs-down recorded that an answer failed and nothing about how,
which is the only part that can be acted on. Pressing it now opens the reason
chips from :mod:`core.memory.feedback_reasons`, so the store gets a defect rather
than a mood.

Both are deliberately quiet: one line, text buttons, dimmed until the message is
hovered. The old floating copy chip (top-right) and thumbs cluster (bottom-right)
are folded into it — two hovering clusters replaced by one row is less chrome,
not more, which is the only way an action bar earns its place.

Pure presentation. Every control is a pattern-matching id keyed by the message
index, so `ui.callbacks` can wire them without this module importing state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

import dash_bootstrap_components as dbc
from dash import dcc, html

from core.memory.feedback_reasons import FREE_TEXT_REASON, REASONS


@dataclass(frozen=True)
class AnswerContext:
    """What the toolbar knows about the answer it sits under.

    Stamped onto the message at commit time (`_stamp_answer_context` in
    ``ui.callbacks``) so an action never has to re-derive the turn it belongs to.
    """

    idx: int
    question: str = ""
    route: str = ""
    shape: str = ""
    has_rows: bool = False
    is_insight: bool = False
    #: Whether this answer produced evidence the analysis panel can hold open.
    has_analysis: bool = False


@dataclass(frozen=True)
class AnswerAction:
    """One next step offered under an answer.

    `applies` is what keeps the row short: an action that cannot work on this
    particular answer is not rendered greyed out, it is not rendered at all. A
    lookup answer showing "Create a decision" would be noise, and noise is how a
    four-button row becomes a ten-button row nobody reads.
    """

    key: str
    label: str
    icon: str
    title: str
    applies: Callable[[AnswerContext], bool]


#: Shapes whose answers are a bare number, not a finding. Offering to raise
#: "$12.4M" on the Decision Board would be silly.
_BARE_SHAPES = frozenset({"direct"})


def is_finding(shape: str, *, looks_structured: bool) -> bool:
    """Whether this answer is a finding — something to act on and to frame.

    Keyed on the turn's answer SHAPE, falling back to how the markdown came out
    only for transcripts saved before the shape was stamped. The fallback counts
    H3 headings, which was a fair guess while every answer used the same five,
    but a comparison or a ranking may now legitimately carry none — and trusting
    the guess would strip both the card and its actions from exactly the answers
    most worth acting on.

    One function for both decisions so the chrome and the actions can never
    disagree about whether the same answer is a finding.
    """
    if shape:
        return shape not in _BARE_SHAPES
    return looks_structured


def _is_analysis(ctx: AnswerContext) -> bool:
    return is_finding(ctx.shape, looks_structured=ctx.is_insight)


#: Display order, left to right. Adding a next step means adding a row here and a
#: branch in ``ui.callbacks.run_answer_action`` — nothing else.
ACTIONS: Tuple[AnswerAction, ...] = (
    AnswerAction(
        "drivers",
        "Explore drivers",
        "bi bi-diagram-3",
        "Ask what drove this",
        _is_analysis,
    ),
    AnswerAction(
        "export",
        "Export data",
        "bi bi-file-earmark-spreadsheet",
        "Download the rows behind this answer",
        lambda ctx: ctx.has_rows,
    ),
    AnswerAction(
        "decision",
        "Create decision",
        "bi bi-clipboard-check",
        "Raise this on the Decision Board",
        _is_analysis,
    ),
    AnswerAction(
        "board",
        "View as board",
        "bi bi-grid-1x2",
        "Rebuild this answer as a Boardroom card",
        _is_analysis,
    ),
)


#: The next step worth promoting to a filled button when it applies. A row of
#: four equal-weight buttons asks the reader to choose; one primary and the rest
#: quiet tells them what this answer is actually FOR — and raising a finding as a
#: decision is the step that turns an answer into work.
PROMOTED = "decision"


def actions_for(ctx: AnswerContext) -> List[AnswerAction]:
    """The actions that actually apply to this answer, in display order."""
    return [action for action in ACTIONS if action.applies(ctx)]


def promoted_action(actions: Sequence[AnswerAction]) -> Optional[AnswerAction]:
    """The one action to lead with, or ``None`` when there is nothing to promote.

    Exactly one, and only from the actions that already applied — promoting a
    step this answer cannot take would be worse than promoting nothing.
    """
    if not actions:
        return None
    return next((a for a in actions if a.key == PROMOTED), actions[0])


def _action_button(action: AnswerAction, idx: int, *, primary: bool = False):
    return html.Button(
        [html.I(className=f"{action.icon} answer-action-icon"), html.Span(action.label)],
        id={"type": "answer-action", "idx": idx, "action": action.key},
        n_clicks=0,
        className="answer-action-btn" + (" is-primary" if primary else ""),
        title=action.title,
    )


def _pin_button(idx: int):
    """Hold this answer's evidence open in the analysis panel."""
    return html.Button(
        html.I(className="bi bi-pin-angle"),
        id={"type": "answer-pin", "idx": idx},
        n_clicks=0,
        className="answer-pin-btn",
        title="Keep this analysis in the panel while you follow up",
    )


def next_question(question: str, idx: int = 0):
    """The single follow-up worth offering under an answer.

    One, not a row: the point is to name the obvious next move, and four
    equally-plausible questions is a menu the reader has to read rather than a
    suggestion they can take. The rest stay in the follow-up block below.
    """
    text = (question or "").strip()
    if not text:
        return None
    return html.Div(
        [
            html.Span("Suggested next question", className="answer-next-label"),
            html.Button(
                [html.I(className="bi bi-chat-square-text"), html.Span(text)],
                id={"type": "suggestion-chip", "idx": idx, "q": text},
                n_clicks=0,
                className="answer-next-chip",
                title=text,
            ),
        ],
        className="answer-next",
    )


def _rating_button(idx: int, rating: str, icon: str, title: str):
    return html.Button(
        html.I(className=icon),
        id={"type": "msg-feedback", "idx": idx, "rating": rating},
        n_clicks=0,
        className="msg-feedback-btn",
        title=title,
    )


def feedback_panel(idx: int):
    """The reason chips, revealed by a thumbs-down. Collapsed and empty until then.

    Mounted (hidden) rather than injected on click so the callbacks that read the
    chips always have something to point at — the same reason the decision
    editor's fields are static.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Span("What went wrong?", className="fb-reason-prompt"),
                    html.Button(
                        html.I(className="bi bi-x"),
                        id={"type": "fb-dismiss", "idx": idx},
                        n_clicks=0,
                        className="fb-dismiss",
                        title="Dismiss",
                    ),
                ],
                className="fb-reason-head",
            ),
            html.Div(
                [
                    html.Button(
                        [
                            html.I(className=f"{reason.icon} fb-reason-icon"),
                            html.Span(reason.label),
                        ],
                        id={"type": "fb-reason", "idx": idx, "reason": reason.key},
                        n_clicks=0,
                        className="fb-reason-chip",
                        title=f"Feeds: {reason.feeds}",
                    )
                    for reason in REASONS
                ],
                className="fb-reason-row",
            ),
            html.Div(
                [
                    dcc.Input(
                        id={"type": "fb-note", "idx": idx},
                        type="text",
                        placeholder="What should it have said? (optional)",
                        className="fb-note-input",
                        debounce=True,
                    ),
                    dbc.Button(
                        "Send",
                        id={"type": "fb-send", "idx": idx},
                        n_clicks=0,
                        className="fb-send-btn",
                    ),
                ],
                className="fb-note-row",
            ),
            html.Div(id={"type": "fb-ack", "idx": idx}, className="fb-ack"),
        ],
        id={"type": "fb-panel", "idx": idx},
        className="fb-panel",
        hidden=True,
    )


def answer_footer(ctx: AnswerContext, *, content: str):
    """The action row plus the (hidden) feedback panel, for one answer.

    Two clusters, and the split is what keeps the row short. On the LEFT, the
    next steps — things that start new work, capped at four (see
    `test_the_row_stays_short`). On the RIGHT, the things you do TO this answer:
    copy it, rewrite it, rate it. "Edit" belongs on the right for that reason —
    it is not somewhere to go next, it is this answer in your own words.

    `content` is the answer text, handed to `dcc.Clipboard` so copy stays a
    native browser action with no callback behind it.
    """
    actions = actions_for(ctx)
    lead = promoted_action(actions)
    return html.Div(
        [
            html.Div(
                [
                    _action_button(action, ctx.idx, primary=(action is lead))
                    for action in sorted(actions, key=lambda a: a is not lead)
                ],
                className="answer-actions",
            ),
            html.Div(
                [
                    _pin_button(ctx.idx) if ctx.has_analysis else None,
                    dcc.Clipboard(
                        content=content, title="Copy", className="answer-copy"
                    ),
                    html.Button(
                        html.I(className="bi bi-pencil"),
                        # Its OWN id type, not an "answer-action": the next-steps
                        # row is somewhere to go, this is something you do to the
                        # answer in front of you.
                        id={"type": "answer-edit-open", "idx": ctx.idx},
                        n_clicks=0,
                        className="answer-edit-toggle",
                        title="Rewrite this insight in your own words",
                    )
                    if _is_analysis(ctx)
                    else None,
                    _rating_button(
                        ctx.idx, "up", "bi bi-hand-thumbs-up", "Helpful"
                    ),
                    _rating_button(
                        ctx.idx, "down", "bi bi-hand-thumbs-down", "Not helpful"
                    ),
                ],
                className="answer-rating",
            ),
        ],
        className="answer-footer" + ("" if actions else " is-bare"),
    )


def feedback_ack(reason_label: str, noted: bool) -> Any:
    """The one-line confirmation shown in place of the chips once a reason lands."""
    text = f"Thanks — logged as “{reason_label}”."
    if noted:
        text += " Your correction is saved with it."
    return html.Span([html.I(className="bi bi-check2 fb-ack-icon"), text])


def wants_note(reason_key: Optional[str]) -> bool:
    """Whether this reason is one the user should be asked to write out.

    "Something else" carries no diagnosis on its own, so the note is the whole
    signal; every other chip is already actionable without one.
    """
    return (reason_key or "") == FREE_TEXT_REASON
