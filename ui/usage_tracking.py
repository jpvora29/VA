"""Usage-metric callbacks: watch the stores each workspace already writes.

Nothing here changes what the app does. Each callback has no outputs; it reads a store
the workspace sets anyway (the active tab, the Studio selection, the staged Recap
decks, the started MoM job) and queues one row in that user's usage workbook.

Ask ICG is recorded where its turn finishes (``ui.callbacks._finish_job``), because
the reply only exists on the worker thread that produced it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from dash import Input, State

from core.usage_metrics import (
    actor_from_store,
    record_usage,
    studio_generate_event,
    tab_visit_event,
    upload_event,
)
from mom.modes import resolve_mode
from ui.shell.tabs import TABS, resolve_tab

_TAB_LABELS = {tab.id: tab.label for tab in TABS}


def tab_label(tab_id: str | None) -> str:
    """The navbar label for a stored tab id ("chat" -> "Ask ICG")."""
    resolved = resolve_tab(tab_id)
    return _TAB_LABELS.get(resolved, resolved)


def staged_names(files: Sequence[Mapping[str, Any]] | None) -> list[str]:
    """The user-facing names of staged uploads (``core.uploads.StagedFile.as_store``)."""
    return [str(item.get("name") or "") for item in files or [] if item]


def record_tab_visit(tab_id: str | None, user_store: dict | None) -> None:
    record_usage(actor_from_store(user_store), tab_visit_event(tab_label(tab_id)))


def record_studio_generate(selection: dict | None, user_store: dict | None) -> None:
    if selection:
        record_usage(actor_from_store(user_store), studio_generate_event(selection))


def record_recap_upload(files: list | None, user_store: dict | None) -> None:
    names = staged_names(files)
    if names:
        event = upload_event("Recap", names, action="Uploaded QBR decks")
        record_usage(actor_from_store(user_store), event)


def record_mom_generate(
    job_id: str | None,
    mode_id: str | None,
    note: dict | None,
    deck: dict | None,
    user_store: dict | None,
) -> None:
    if not job_id:
        return
    action = f"Generate ({resolve_mode(mode_id).label})"
    event = upload_event("MoM", staged_names([note or {}, deck or {}]), action=action)
    record_usage(actor_from_store(user_store), event)


def register_usage_tracking(app) -> None:
    """Wire the usage-metric watchers onto ``app`` (the merged app only)."""
    app.callback(
        Input("active-tab", "data"),
        State("user-store", "data"),
    )(record_tab_visit)
    app.callback(
        Input("qs-selection", "data"),
        State("user-store", "data"),
        prevent_initial_call=True,
    )(record_studio_generate)
    app.callback(
        Input("recap-files", "data"),
        State("user-store", "data"),
        prevent_initial_call=True,
    )(record_recap_upload)
    app.callback(
        Input("mom-job", "data"),
        State("mom-mode", "data"),
        State("mom-note-file", "data"),
        State("mom-deck-file", "data"),
        State("user-store", "data"),
        prevent_initial_call=True,
    )(record_mom_generate)
