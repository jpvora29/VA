"""The Recap workspace: drop the QBR decks, check what they say, generate.

Pure layout — every function here returns a component and nothing else. The wiring
lives in :mod:`ui.recap.callbacks`, and the engine in :mod:`recap`.

It is the MoM workspace's page, deliberately: the same rail, the same cards, the same
progress panel and the same result block, because the two workspaces do the same
*shape* of thing — upload, watch a long run, take the document away — and a person who
has used one should not have to learn the other.

Three things differ, and each is something Recap actually needs:

    one zone, many decks   a recap can cover several quarters, so the zone takes a
                           set of .pptx files rather than two named slots.
    what the cover says    the client and the period are read off slide 1 and shown
                           back as chips, so a wrong reading is visible BEFORE the run.
    a deck, not a document the result is a .pptx rendered into the QBR Recap template.

The body is built ONCE and never re-rendered as a whole: a re-render of the upload
zone would drop the decks the user already chose.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from dash import dcc, html

from recap.metadata import DeckMetadata
from recap.progress import PHASES, phase_index
from recap.uploads import ACCEPT
from ui.shell.rail import rail_frame, rail_section

# The poll runs only while a job is in flight; ``callbacks`` enables and disables it.
POLL_INTERVAL_MS = 1500

#: What each detected metadata field is called on its chip.
CHIP_LABELS: dict = {
    "client_name": "Client",
    "company_name": "Company",
    "period_label": "Period",
    "quarter": "Quarter",
    "year": "Year",
    "meeting_date": "Date",
}


# ── the rail ──────────────────────────────────────────────────────────────────


def step_class(index: int, phase: Optional[str], done: bool) -> str:
    """How one rail step looks for the phase a run is currently in.

    Shares ``va-rail-step`` with every other workspace on purpose: the collapsed icon
    column is sized off that class, so the live rail keeps the same geometry.
    """
    if done:
        return "va-rail-step is-done"
    running = phase_index(phase)
    if running is None:
        return "va-rail-step"
    if index < running:
        return "va-rail-step is-done"
    if index == running:
        return "va-rail-step is-running"
    return "va-rail-step"


def rail_steps(phase: Optional[str] = None, done: bool = False) -> list[html.Div]:
    """The pipeline's phases, lit up to wherever the run has reached."""
    return [
        html.Div(
            [
                html.Span(
                    [
                        html.I(className=f"bi {step.icon}"),
                        html.Span(str(index + 1), className="va-rail-step-num"),
                    ],
                    className="va-rail-step-tile",
                ),
                html.Span(step.label, className="va-rail-step-label"),
            ],
            className=step_class(index, phase, done),
            title=step.label,  # collapsed, the tile is all that shows
        )
        for index, step in enumerate(PHASES)
    ]


def recap_rail() -> html.Aside:
    """The workspace rail: the pipeline, and where the run has got to."""
    return rail_frame(
        "Recap",
        [rail_section("Pipeline", [html.Div(rail_steps(), id="recap-rail-steps")])],
        rail_id="recap",
        className="va-recap-rail",
    )


# ── cards ─────────────────────────────────────────────────────────────────────


def _card(label: str, children: Sequence[Any], **kwargs) -> html.Section:
    return html.Section(
        [html.P(label, className="recap-card-label"), *children],
        className="recap-card",
        **kwargs,
    )


def upload_zone() -> dcc.Upload:
    """The drop target. Its children never change, so a re-render cannot empty it."""
    return dcc.Upload(
        id="recap-upload",
        children=html.Div(
            [
                html.I(className="bi bi-cloud-arrow-up"),
                html.Span("Click or drag QBR decks here", className="recap-drop-hint"),
            ],
            className="recap-drop-inner",
        ),
        className="recap-drop",
        multiple=True,
        accept=ACCEPT,
    )


def upload_card() -> html.Section:
    """The decks a run reads. One zone, because a recap may cover several quarters."""
    return _card(
        "Upload QBR decks",
        [
            html.Div(
                [
                    html.Span("Review decks", className="recap-drop-label"),
                    html.Span("PowerPoint (.pptx)", className="recap-drop-formats"),
                ],
                className="recap-drop-head",
            ),
            upload_zone(),
            html.Div(id="recap-file-status", className="recap-file-status"),
            html.P(
                "Several decks make one recap covering all of them. Dropping again "
                "replaces the set.",
                className="recap-card-note",
            ),
        ],
    )


def meta_chip(field: str, value: str) -> html.Span:
    return html.Span(
        [
            html.Span(f"{CHIP_LABELS.get(field, field)}: ", className="recap-chip-label"),
            html.Span(value),
        ],
        className="recap-chip",
    )


def meta_chips(metadata: DeckMetadata) -> html.Div:
    """What the first deck's cover slide claims — shown before the run, not after.

    Nothing here is required: the pipeline runs without it. It is shown because a
    misread client name is a wrong title on every slide of the finished recap, and
    this is the last moment it costs nothing to notice.
    """
    found = metadata.found()
    if not found:
        return html.Div(
            html.Span("Nothing detected on the cover slide", className="recap-chip is-empty"),
            className="recap-chip-row",
        )
    return html.Div(
        [meta_chip(field, value) for field, value in found],
        className="recap-chip-row",
    )


def details_card() -> html.Section:
    """Where the cover-slide reading lands. Empty until a deck is uploaded."""
    return _card(
        "What the deck says",
        [
            html.Div(
                html.Span("Upload a deck to read its cover slide.", className="recap-card-note"),
                id="recap-meta",
            )
        ],
    )


def generate_card() -> html.Section:
    """The action, and everything the run reports back into."""
    return html.Section(
        [
            html.Button(
                [html.I(className="bi bi-journal-text"), html.Span("Generate recap")],
                id="recap-generate",
                n_clicks=0,
                className="recap-generate",
                disabled=True,
            ),
            html.Div(id="recap-hint", className="recap-hint"),
            html.Div(id="recap-progress", className="recap-progress-host"),
        ],
        className="recap-card recap-card-action",
    )


# ── progress and result ───────────────────────────────────────────────────────


def progress_panel(state: dict) -> html.Div:
    """The bar, the stage, and — once there is one — the finished deck."""
    percent = int(state.get("percent") or 0)
    failed = bool(state.get("error"))
    done = bool(state.get("done")) and not failed

    blocks: list[Any] = [
        html.Div(
            [
                html.Span(state.get("step") or "Working", className="recap-progress-step"),
                html.Span(f"{percent}%", className="recap-progress-pct"),
            ],
            className="recap-progress-head",
        ),
        html.Div(
            html.Div(
                className="recap-progress-fill" + (" is-failed" if failed else ""),
                style={"width": f"{0 if failed else percent}%"},
            ),
            className="recap-progress-track",
        ),
        html.P(state.get("message") or "", className="recap-progress-msg"),
    ]

    if failed:
        blocks.append(_failure(str(state["error"])))
    elif done:
        blocks.append(_success(state))

    return html.Div(blocks, className="recap-progress")


def result_counts(state: dict) -> str:
    """The run in one line: how much was read, and how much came out of it."""
    insights = state.get("insights") or 0
    actions = state.get("action_items") or 0
    return f"{insights} insight(s) read · {actions} action item(s)"


def _success(state: dict) -> html.Div:
    takeaways = state.get("takeaways") or []
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-check-circle-fill"),
                    html.Strong("Your recap is ready."),
                ],
                className="recap-result-head",
            ),
            html.P(
                " · ".join(
                    filter(None, [state.get("client"), state.get("period"),
                                  state.get("filename")])
                ),
                className="recap-result-file",
            ),
            html.P(result_counts(state), className="recap-result-file"),
            html.Ul([html.Li(title) for title in takeaways], className="recap-result-topics")
            if takeaways
            else html.Span(),
            html.Button(
                [html.I(className="bi bi-download"), html.Span("Download (.pptx)")],
                id="recap-download-btn",
                n_clicks=0,
                className="recap-download",
            ),
        ],
        className="recap-result is-good",
    )


def _failure(message: str) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-exclamation-triangle-fill"),
                    html.Strong("The run did not finish."),
                ],
                className="recap-result-head",
            ),
            html.P(message, className="recap-result-file"),
        ],
        className="recap-result is-bad",
    )


# ── the workspace ─────────────────────────────────────────────────────────────


def recap_body() -> html.Div:
    """The whole Recap page, built once."""
    return html.Div(
        html.Div(
            [
                html.Header(
                    [
                        html.H1("New QBR recap", className="recap-title"),
                        html.P(
                            "Upload the review decks. Every point in the recap is read "
                            "out of what those slides actually say, and traces back to "
                            "the slide it came from.",
                            className="recap-blurb",
                        ),
                    ],
                    className="recap-header",
                ),
                upload_card(),
                details_card(),
                generate_card(),
            ],
            className="recap-page",
        ),
        className="recap-host",
    )
