"""Recap wiring: stage the decks, read their cover, run the pipeline, download the deck.

Five callbacks, each with one job:

    1. stage the uploads       -> ``recap-files``, ``recap-meta-store``, the chips
    2. arm the Generate button -> enabled only with at least one deck
    3. start a run             -> ``recap-job``, and the poll that follows it
    4. poll it                 -> the progress panel and the rail
    5. hand over the deck      -> ``recap-download``

The run itself is a :mod:`recap.jobs` daemon thread; the poll reads its snapshot. That
is the same pattern MoM and a streaming chat turn use, and for the same reason — a
Dash callback must return in milliseconds and a recap run takes minutes.

The real logic sits in module-level helpers with everything passed in, so each one is
testable without a running Dash app; the callbacks below are thin.
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from dash import Input, Output, State, dcc, html, no_update

from logger import get_logger
from recap import config, jobs
from recap.metadata import DeckMetadata, read_cover
from recap.run import RecapRequest
from recap.uploads import (
    ACCEPT,
    StagedFile,
    UploadRejected,
    adopt_all,
    decode,
    stage_upload,
    staged_from_store,
)
from ui.recap.render import meta_chips, progress_panel, rail_steps

log = get_logger(__name__)


# ── helpers (no Dash state, so they test on their own) ────────────────────────


def file_status(staged: Sequence[StagedFile], errors: Sequence[str] = ()) -> Any:
    """What the line under the upload zone says: what was taken, and what was not."""
    lines: List[Any] = []
    for file in staged:
        lines.append(
            html.Div([html.I(className="bi bi-check-circle"), file.name], className="is-good")
        )
    for message in errors:
        lines.append(
            html.Div([html.I(className="bi bi-x-circle"), message], className="is-bad")
        )
    return lines or ""


def can_generate(files: Optional[Sequence[dict]]) -> bool:
    """A run needs at least one staged deck; anything less keeps the button disabled."""
    return bool(staged_from_store(files))


def missing_hint(files: Optional[Sequence[dict]]) -> str:
    """What the user still owes us, said plainly."""
    return "" if can_generate(files) else "Upload at least one QBR deck to continue."


def stage_decks(
    contents: Optional[Sequence[str]], filenames: Optional[Sequence[str]]
) -> Tuple[List[StagedFile], List[str]]:
    """Save every uploaded deck; return what was staged and what was refused.

    One bad file does not lose the good ones — a deck that cannot be read is reported
    on its own line and the rest of the drop still stages.
    """
    staged: List[StagedFile] = []
    errors: List[str] = []
    for content, filename in zip(contents or [], filenames or []):
        try:
            staged.append(stage_upload(content, filename or "", ACCEPT))
        except (UploadRejected, OSError) as exc:
            log.warning("Recap: upload rejected: %s", exc)
            errors.append(str(exc))
    return staged, errors


def read_first_cover(contents: Optional[Sequence[str]]) -> DeckMetadata:
    """The cover slide of the first deck in the drop, or nothing readable.

    The first deck decides, rather than the last one to parse cleanly: the user
    picked them in an order, and the earliest is the one whose client and period the
    others are being read alongside.
    """
    for content in contents or []:
        metadata = read_cover(decode(content))
        if not metadata.is_empty():
            return metadata
    return DeckMetadata()


def build_request(files: Sequence[dict], metadata: Optional[dict]) -> RecapRequest:
    """A fresh run directory with every staged deck copied into it."""
    staged = staged_from_store(files)
    if not staged:
        raise ValueError("The uploaded decks are no longer available. Upload them again.")
    paths = config.new_run_paths()
    return RecapRequest(
        deck_paths=tuple(adopt_all(staged, paths)),
        metadata=DeckMetadata.from_store(metadata),
        paths=paths,
    )


# ── registration ──────────────────────────────────────────────────────────────


def register_recap(app) -> None:
    """Wire the Recap workspace onto ``app``."""

    @app.callback(
        Output("recap-files", "data"),
        Output("recap-meta-store", "data"),
        Output("recap-file-status", "children"),
        Output("recap-meta", "children"),
        Input("recap-upload", "contents"),
        State("recap-upload", "filename"),
        prevent_initial_call=True,
    )
    def upload_decks(contents, filenames):
        """Stage the drop, and show what its first deck says about itself."""
        if not contents:
            return no_update, no_update, no_update, no_update
        staged, errors = stage_decks(contents, filenames)
        metadata = read_first_cover(contents)
        return (
            [file.as_store() for file in staged],
            metadata.as_store(),
            file_status(staged, errors),
            meta_chips(metadata),
        )

    @app.callback(
        Output("recap-generate", "disabled"),
        Output("recap-hint", "children"),
        Input("recap-files", "data"),
        Input("recap-job", "data"),
        # The poll switches itself off the tick a run ends, and that is the only
        # signal the run finished — without it the button would stay disabled for
        # the rest of the session and a second run would be impossible.
        Input("recap-poll", "disabled"),
    )
    def arm_generate(files, job_id, poll_off):
        """Enabled only when a run is possible, and never while one is running."""
        job = jobs.get_job(job_id)
        if job is not None and not job.done:
            return True, "A recap is being written."
        if not can_generate(files):
            return True, missing_hint(files)
        return False, ""

    @app.callback(
        Output("recap-job", "data"),
        Output("recap-poll", "disabled"),
        Output("recap-progress", "children"),
        Input("recap-generate", "n_clicks"),
        State("recap-files", "data"),
        State("recap-meta-store", "data"),
        prevent_initial_call=True,
    )
    def start(n_clicks, files, metadata):
        """Start the pipeline in its own thread and switch the poll on."""
        if not n_clicks or not can_generate(files):
            return no_update, no_update, no_update
        try:
            job = jobs.start_run(build_request(files, metadata))
        except (OSError, ValueError) as exc:
            log.exception("Recap: could not start a run")
            return None, True, progress_panel({"done": True, "error": str(exc)})
        return job.job_id, False, progress_panel(job.snapshot())

    @app.callback(
        Output("recap-progress", "children", allow_duplicate=True),
        Output("recap-rail-steps", "children"),
        Output("recap-poll", "disabled", allow_duplicate=True),
        Input("recap-poll", "n_intervals"),
        State("recap-job", "data"),
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
        Output("recap-download", "data"),
        Input("recap-download-btn", "n_clicks"),
        State("recap-job", "data"),
        prevent_initial_call=True,
    )
    def download(n_clicks, job_id):
        """Hand the finished deck to the browser."""
        job = jobs.get_job(job_id)
        path = job.pptx_path() if job else None
        if not n_clicks or not path:
            return no_update
        return dcc.send_file(path)
