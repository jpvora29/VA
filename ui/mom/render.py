"""The Minutes-of-Meeting workspace: pick a document type, upload two files, generate.

Pure layout — every function here returns a component and nothing else. The wiring
lives in :mod:`ui.mom.callbacks`, and the engine in :mod:`mom`.

The body is built ONCE and never re-rendered as a whole: the upload zones, the
Generate button and the progress panel are all in the static tree and callbacks only
write into their leaves. Re-rendering an upload zone would clear the file the user had
already chosen, which is exactly the bug the standalone app was shaped to avoid.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from dash import dcc, html

from mom.modes import MODES, MoMMode, resolve_mode
from mom.progress import PHASES
from ui.shell.rail import rail_frame, rail_section

# The poll runs only while a job is in flight; ``callbacks`` enables and disables it.
POLL_INTERVAL_MS = 1500


# ── the rail ──────────────────────────────────────────────────────────────────


def step_class(index: int, phase: Optional[str], done: bool) -> str:
    """How one rail step looks for the phase a run is currently in.

    Shares ``va-rail-step`` with the placeholder workspaces on purpose: the collapsed
    icon column is sized off that class, so the live rail keeps the same geometry.
    """
    if done:
        return "va-rail-step is-done"
    running = next((i for i, p in enumerate(PHASES) if p.id == phase), None)
    if running is None:
        return "va-rail-step"
    if index < running:
        return "va-rail-step is-done"
    if index == running:
        return "va-rail-step is-running"
    return "va-rail-step"


#: An icon per pipeline phase, so the collapsed rail says WHAT each step is.
#: Collapsed, the tile is all that shows — and five bare numerals said only that
#: there are five of something, while Studio's rail beside it showed icons. Same
#: shape as `studio.page.authoring.chrome.mode_rail`: tile with the icon, the step
#: numeral as a badge on it, label alongside.
_PHASE_ICONS: dict = {
    "notes": "bi-file-earmark-text",
    "deck": "bi-easel",
    "tagging": "bi-tags",
    "verification": "bi-patch-check",
    "summary": "bi-journal-richtext",
}


def rail_steps(phase: Optional[str] = None, done: bool = False) -> list[html.Div]:
    """The five pipeline phases, lit up to wherever the run has reached."""
    return [
        html.Div(
            [
                html.Span(
                    [
                        html.I(className=f"bi {_PHASE_ICONS.get(step.id, 'bi-circle')}"),
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


def mom_rail() -> html.Aside:
    """The workspace rail: the pipeline, and where the run has got to."""
    return rail_frame(
        "MoM",
        [rail_section("Pipeline", [html.Div(rail_steps(), id="mom-rail-steps")])],
        rail_id="mom",
        className="va-mom-rail",
    )


# ── cards ─────────────────────────────────────────────────────────────────────


def _card(label: str, children: Sequence[Any], **kwargs) -> html.Section:
    return html.Section(
        [html.P(label, className="mom-card-label"), *children],
        className="mom-card",
        **kwargs,
    )


def mode_button(mode: MoMMode, active: str) -> html.Button:
    """One document-type choice. The chosen one also decides the pipeline's shape."""
    selected = mode.id == active
    return html.Button(
        [
            html.Span(mode.label, className="mom-mode-label"),
            html.Span(mode.hint, className="mom-mode-hint"),
        ],
        id={"type": "mom-mode", "mode": mode.id},
        n_clicks=0,
        className="mom-mode" + (" is-active" if selected else ""),
        title=mode.hint,
    )


def mode_card(active: str) -> html.Section:
    return _card(
        "Document type",
        [
            html.Div(
                [mode_button(mode, active) for mode in MODES],
                className="mom-mode-row",
                id="mom-mode-row",
            ),
            html.P(
                "Both shapes read the same deck; they differ in how the minutes are "
                "sectioned.",
                className="mom-card-note",
            ),
        ],
    )


def formats_hint(accept: str) -> str:
    """``.pdf,.docx`` reads as "PDF or Word" to the person choosing a file."""
    names = {".pdf": "PDF", ".docx": "Word", ".pptx": "PowerPoint"}
    extensions = [e.strip().lower() for e in accept.split(",") if e.strip()]
    return " or ".join(names.get(e, e.lstrip(".").upper()) for e in extensions)


def upload_zone(zone_id: str, accept: str) -> dcc.Upload:
    """A drop target. Its children never change — only ``accept`` does, when the mode
    does — so a file already chosen is never dropped by a re-render."""
    return dcc.Upload(
        id=zone_id,
        children=html.Div(
            [
                html.I(className="bi bi-cloud-arrow-up"),
                html.Span("Click or drag a file here", className="mom-drop-hint"),
            ],
            className="mom-drop-inner",
        ),
        className="mom-drop",
        multiple=False,
        accept=accept,
    )


def _drop_cell(label: str, formats: Any, zone: Any, status_id: str) -> html.Div:
    """One upload: what it is, which formats it takes, the zone, and its status.

    The formats line lives OUTSIDE the zone so the mode switch can change it without
    re-rendering the zone and dropping the file already in it.
    """
    return html.Div(
        [
            html.Div(
                [html.Span(label, className="mom-drop-label"),
                 html.Span(formats, className="mom-drop-formats")],
                className="mom-drop-head",
            ),
            zone,
            html.Div(id=status_id, className="mom-file-status"),
        ],
        className="mom-drop-cell",
    )


def upload_card(mode: MoMMode) -> html.Section:
    """The two files a run needs. Both zones are static; only their status text moves."""
    return _card(
        "Upload files",
        [
            html.Div(
                [
                    _drop_cell(
                        "Meeting note",
                        html.Span(formats_hint(mode.accept), id="mom-note-formats"),
                        upload_zone("mom-upload-note", mode.accept),
                        "mom-note-status",
                    ),
                    _drop_cell(
                        "QBR deck",
                        html.Span(formats_hint(".pptx")),
                        upload_zone("mom-upload-deck", ".pptx"),
                        "mom-deck-status",
                    ),
                ],
                className="mom-drop-row",
            )
        ],
    )


def generate_card() -> html.Section:
    """The action, and everything the run reports back into."""
    return html.Section(
        [
            html.Button(
                [html.I(className="bi bi-file-earmark-text"), html.Span("Generate meeting note")],
                id="mom-generate",
                n_clicks=0,
                className="mom-generate",
                disabled=True,
            ),
            html.Div(id="mom-hint", className="mom-hint"),
            html.Div(id="mom-progress", className="mom-progress-host"),
        ],
        className="mom-card mom-card-action",
    )


# ── progress and result ───────────────────────────────────────────────────────


def progress_panel(state: dict) -> html.Div:
    """The bar, the phase, and — once there is one — the finished document."""
    percent = int(state.get("percent") or 0)
    failed = bool(state.get("error"))
    done = bool(state.get("done")) and not failed

    blocks: list[Any] = [
        html.Div(
            [
                html.Span(state.get("step") or "Working", className="mom-progress-step"),
                html.Span(f"{percent}%", className="mom-progress-pct"),
            ],
            className="mom-progress-head",
        ),
        html.Div(
            html.Div(
                className="mom-progress-fill" + (" is-failed" if failed else ""),
                style={"width": f"{0 if failed else percent}%"},
            ),
            className="mom-progress-track",
        ),
        html.P(state.get("message") or "", className="mom-progress-msg"),
    ]

    if failed:
        blocks.append(_failure(str(state["error"])))
    elif done:
        blocks.append(_success(state))

    return html.Div(blocks, className="mom-progress")


def _success(state: dict) -> html.Div:
    topics = state.get("topics") or []
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-check-circle-fill"),
                    html.Strong("Your meeting note is ready."),
                ],
                className="mom-result-head",
            ),
            html.P(
                " · ".join(filter(None, [state.get("client"), state.get("filename")])),
                className="mom-result-file",
            ),
            html.Ul([html.Li(topic) for topic in topics], className="mom-result-topics")
            if topics
            else html.Span(),
            html.Button(
                [html.I(className="bi bi-download"), html.Span("Download (.docx)")],
                id="mom-download-btn",
                n_clicks=0,
                className="mom-download",
            ),
        ],
        className="mom-result is-good",
    )


def _failure(message: str) -> html.Div:
    return html.Div(
        [
            html.Div(
                [html.I(className="bi bi-exclamation-triangle-fill"),
                 html.Strong("The run did not finish.")],
                className="mom-result-head",
            ),
            html.P(message, className="mom-result-file"),
        ],
        className="mom-result is-bad",
    )


# ── the workspace ─────────────────────────────────────────────────────────────


def mom_body(mode_id: str | None = None) -> html.Div:
    """The whole MoM page, built once."""
    mode = resolve_mode(mode_id)
    return html.Div(
        html.Div(
            [
                html.Header(
                    [
                        html.H1("New meeting note", className="mom-title"),
                        html.P(
                            "Upload the note from the call and the QBR deck it was about. "
                            "The minutes are written from what both actually say.",
                            className="mom-blurb",
                        ),
                    ],
                    className="mom-header",
                ),
                mode_card(mode.id),
                upload_card(mode),
                generate_card(),
            ],
            className="mom-page",
        ),
        className="mom-host",
    )
