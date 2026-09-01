"""MoM wiring: choose a mode, stage two uploads, run the pipeline, download the result.

Eight callbacks, each with one job:

    1. pick the document type          -> ``mom-mode``
    2. re-dress the note upload for it -> its accept list and the formats line
    3/4. stage an upload               -> ``mom-note-file`` / ``mom-deck-file``
    5. arm the Generate button         -> enabled only with a mode and both files
    6. start a run                     -> ``mom-job``, and the poll that follows it
    7. poll it                         -> the progress panel and the rail
    8. hand over the document          -> ``mom-download``

The run itself is a :mod:`mom.jobs` daemon thread; the poll reads its snapshot. That
is the same pattern a streaming chat turn uses, and for the same reason — a Dash
callback must return in milliseconds and a run takes minutes.

The real logic sits in module-level helpers with everything injected, so each one is
testable without a running Dash app; the callbacks below are thin.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from logger import get_logger
from mom import config, jobs
from mom.modes import DEFAULT_MODE, resolve_mode
from mom.pipeline import MoMRequest
from mom.uploads import StagedFile, UploadRejected, adopt, stage_upload
from ui.mom.render import formats_hint, mode_button, progress_panel, rail_steps

log = get_logger(__name__)


# ── helpers (no Dash state, so they test on their own) ────────────────────────


def file_status(staged: Optional[StagedFile], error: str = "") -> Any:
    """What the line under an upload zone says."""
    if error:
        return html.Span([html.I(className="bi bi-x-circle"), error], className="is-bad")
    if staged is None:
        return ""
    return html.Span(
        [html.I(className="bi bi-check-circle"), staged.name], className="is-good"
    )


def can_generate(mode_id: Optional[str], note: Optional[dict], deck: Optional[dict]) -> bool:
    """A run needs a mode and both files; anything less keeps the button disabled."""
    return bool(mode_id) and bool(note and note.get("path")) and bool(deck and deck.get("path"))


def missing_hint(note: Optional[dict], deck: Optional[dict]) -> str:
    """Which file the user still owes us, said plainly."""
    if not (note and note.get("path")):
        return "Upload the meeting note to continue."
    if not (deck and deck.get("path")):
        return "Upload the QBR deck to continue."
    return ""


def build_request(mode_id: str, note: dict, deck: dict) -> MoMRequest:
    """A fresh run directory with both staged uploads copied into it."""
    mode = resolve_mode(mode_id)
    paths = config.new_run_paths()
    staged_note = StagedFile.from_store(note)
    staged_deck = StagedFile.from_store(deck)
    if staged_note is None or staged_deck is None:
        raise ValueError("Both the meeting note and the deck are needed.")
    return MoMRequest(
        note_path=adopt(staged_note, paths),
        deck_path=adopt(staged_deck, paths),
        mode=mode,
        paths=paths,
    )


def stage(contents: Optional[str], filename: Optional[str], accept: str) -> Tuple[Any, Any]:
    """Save one upload; return ``(store value, status)`` — both no_update on no file."""
    if not contents:
        return no_update, no_update
    try:
        staged = stage_upload(contents, filename or "", accept)
    except (UploadRejected, OSError) as exc:
        log.warning("MoM: upload rejected: %s", exc)
        return None, file_status(None, str(exc))
    return staged.as_store(), file_status(staged)


# ── registration ──────────────────────────────────────────────────────────────


def register_mom(app) -> None:
    """Wire the MoM workspace onto ``app``."""

    @app.callback(
        Output("mom-mode", "data"),
        Output("mom-mode-row", "children"),
        Input({"type": "mom-mode", "mode": ALL}, "n_clicks"),
        State("mom-mode", "data"),
        prevent_initial_call=True,
    )
    def choose_mode(clicks, current):
        """Record the document type and light the chosen button."""
        if not ctx.triggered_id or not any(clicks or []):
            return no_update, no_update
        chosen = resolve_mode(ctx.triggered_id["mode"])
        if chosen.id == resolve_mode(current).id:
            return no_update, no_update
        from mom.modes import MODES

        return chosen.id, [mode_button(mode, chosen.id) for mode in MODES]

    @app.callback(
        Output("mom-upload-note", "accept"),
        Output("mom-note-formats", "children"),
        Input("mom-mode", "data"),
    )
    def note_accepts(mode_id):
        """Self notes may be .docx; an AI summary is a PDF. The zone follows the mode,
        and so does the line that tells the user which formats it takes — a zone that
        said PDF while accepting Word is a promise the page does not keep."""
        accept = resolve_mode(mode_id).accept
        return accept, formats_hint(accept)

    @app.callback(
        Output("mom-note-file", "data"),
        Output("mom-note-status", "children"),
        Input("mom-upload-note", "contents"),
        State("mom-upload-note", "filename"),
        State("mom-mode", "data"),
        prevent_initial_call=True,
    )
    def upload_note(contents, filename, mode_id):
        return stage(contents, filename, resolve_mode(mode_id).accept)

    @app.callback(
        Output("mom-deck-file", "data"),
        Output("mom-deck-status", "children"),
        Input("mom-upload-deck", "contents"),
        State("mom-upload-deck", "filename"),
        prevent_initial_call=True,
    )
    def upload_deck(contents, filename):
        return stage(contents, filename, ".pptx")

    @app.callback(
        Output("mom-generate", "disabled"),
        Output("mom-hint", "children"),
        Input("mom-mode", "data"),
        Input("mom-note-file", "data"),
        Input("mom-deck-file", "data"),
        Input("mom-job", "data"),
        # The poll switches itself off the tick a run ends, and that is the only
        # signal the run finished — without it the button would stay disabled for
        # the rest of the session and a second run would be impossible.
        Input("mom-poll", "disabled"),
    )
    def arm_generate(mode_id, note, deck, job_id, poll_off):
        """Enabled only when a run is possible, and never while one is running."""
        job = jobs.get_job(job_id)
        if job is not None and not job.done:
            return True, "A meeting note is being written."
        if not can_generate(mode_id, note, deck):
            return True, missing_hint(note, deck)
        return False, ""

    @app.callback(
        Output("mom-job", "data"),
        Output("mom-poll", "disabled"),
        Output("mom-progress", "children"),
        Input("mom-generate", "n_clicks"),
        State("mom-mode", "data"),
        State("mom-note-file", "data"),
        State("mom-deck-file", "data"),
        prevent_initial_call=True,
    )
    def start(n_clicks, mode_id, note, deck):
        """Start the pipeline in its own thread and switch the poll on."""
        if not n_clicks or not can_generate(mode_id, note, deck):
            return no_update, no_update, no_update
        try:
            job = jobs.start_run(build_request(mode_id or DEFAULT_MODE, note, deck))
        except (OSError, ValueError) as exc:
            log.exception("MoM: could not start a run")
            return None, True, progress_panel({"done": True, "error": str(exc)})
        return job.job_id, False, progress_panel(job.snapshot())

    @app.callback(
        Output("mom-progress", "children", allow_duplicate=True),
        Output("mom-rail-steps", "children"),
        Output("mom-poll", "disabled", allow_duplicate=True),
        Input("mom-poll", "n_intervals"),
        State("mom-job", "data"),
        prevent_initial_call=True,
    )
    def poll(_ticks, job_id):
        """One tick: repaint the progress panel and the rail, stop when the run ends."""
        job = jobs.get_job(job_id)
        if job is None:
            return no_update, no_update, True
        state = job.snapshot()
        finished = bool(state["done"])
        return (
            progress_panel(state),
            rail_steps(state["phase"], done=finished and not state["error"]),
            # Only WRITE the poll's own switch when the run ends. Re-writing False on
            # every tick would re-fire everything that reads it (the Generate button)
            # once a second for the length of the run.
            True if finished else no_update,
        )

    @app.callback(
        Output("mom-download", "data"),
        Input("mom-download-btn", "n_clicks"),
        State("mom-job", "data"),
        prevent_initial_call=True,
    )
    def download(n_clicks, job_id):
        """Hand the finished document to the browser."""
        job = jobs.get_job(job_id)
        path = job.docx_path() if job else None
        if not n_clicks or not path:
            return no_update
        return dcc.send_file(path)
