"""Decision Board interaction callbacks (registered on import, like boardroom).

Everything here is plain CRUD against ``core.store.decisions`` plus a tiny
view-router that toggles the chat / board panes. No LLM is involved. A single
``decisions-version`` counter is bumped after any mutation to repaint the board;
the detail panel and editor modal are driven by their own target stores.
"""
from __future__ import annotations

from typing import Any, Optional

from dash import ALL, Input, Output, State, callback, ctx, no_update

from core.store import decisions as store
from ui.decisions import model, render

_NEW = "__new__"  # sentinel target meaning "create a new decision"


def _uid(user_store: dict[str, Any] | None) -> Optional[int]:
    us = user_store or {}
    try:
        return int(us.get("id")) if us.get("id") is not None else None
    except (TypeError, ValueError):
        return None


def _clicked() -> bool:
    """True only for a real click (value > 0), not a remount with n_clicks=0."""
    return bool(ctx.triggered and ctx.triggered[0].get("value"))


def _split_stakeholders(raw: str | None) -> list[str]:
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


# ── View router (chat ↔ board) ──────────────────────────────────────────────


@callback(
    Output("active-view", "data"),
    Input("nav-decision-board", "n_clicks"),
    Input("nav-chat-view", "n_clicks"),
    Input("new-chat-btn", "n_clicks"),
    Input({"type": "conv-item", "id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def set_active_view(*_: Any) -> str:
    """Board when its nav is clicked; any chat action returns to the chat view."""
    return "board" if ctx.triggered_id == "nav-decision-board" else "chat"


@callback(
    Output("view-chat", "className"),
    Output("view-board", "className"),
    Input("active-view", "data"),
)
def toggle_views(view: str | None) -> tuple[str, str]:
    if view == "board":
        return "view-pane view-hidden", "view-pane"
    return "view-pane", "view-pane view-hidden"


# ── Board painting (search / filter / sort) ─────────────────────────────────


@callback(
    Output("decision-board", "children"),
    Input("active-view", "data"),
    Input("decision-search", "value"),
    Input("decision-filter-status", "value"),
    Input("decision-filter-priority", "value"),
    Input("decision-sort", "value"),
    Input("decisions-version", "data"),
    State("user-store", "data"),
)
def paint_board(view, search, statuses, priorities, sort, _version, user_store):
    uid = _uid(user_store)
    if uid is None or view != "board":
        return no_update
    items = store.list_decisions(
        uid,
        search=search,
        statuses=statuses or None,
        priorities=priorities or None,
        sort=sort or "manual",
    )
    return render.board_columns(items)


# ── Open the detail panel ───────────────────────────────────────────────────


@callback(
    Output("decision-detail", "is_open"),
    Output("decision-detail-content", "children"),
    Output("decision-detail-target", "data"),
    Input({"type": "decision-card", "id": ALL}, "n_clicks"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def open_detail(_clicks, user_store):
    if not _clicked():
        return no_update, no_update, no_update
    uid = _uid(user_store)
    did = ctx.triggered_id["id"]
    d = store.get_decision(uid, did)
    if d is None:
        return no_update, no_update, no_update
    return True, render.detail_body(d, store.list_revisions(uid, did)), did


# ── Pin / unpin ─────────────────────────────────────────────────────────────


@callback(
    Output("decisions-version", "data", allow_duplicate=True),
    Input({"type": "decision-pin", "id": ALL}, "n_clicks"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def pin_decision(_clicks, version, user_store):
    if not _clicked():
        return no_update
    store.toggle_pin(_uid(user_store), ctx.triggered_id["id"])
    return (version or 0) + 1


# ── Create / edit modal ─────────────────────────────────────────────────────


@callback(
    Output("decision-edit-modal", "is_open"),
    Output("decision-edit-form", "children"),
    Output("decision-edit-title", "children"),
    Output("decision-edit-target", "data"),
    Output("decision-detail", "is_open", allow_duplicate=True),
    Input("decision-new-btn", "n_clicks"),
    Input("decision-detail-edit", "n_clicks"),
    State("decision-detail-target", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def open_editor(_new, _edit, target, user_store):
    """Open the editor for a new decision (New button) or an existing one (Edit)."""
    if not _clicked():
        return (no_update,) * 5
    if ctx.triggered_id == "decision-new-btn":
        return True, render.edit_form(None), "New decision", _NEW, no_update
    d = store.get_decision(_uid(user_store), target)
    if d is None:
        return (no_update,) * 5
    return True, render.edit_form(d), "Edit decision", target, False


@callback(
    Output("decision-edit-modal", "is_open", allow_duplicate=True),
    Input("decision-edit-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_editor(n):
    return False if n else no_update


@callback(
    Output("decision-edit-modal", "is_open", allow_duplicate=True),
    Output("decisions-version", "data", allow_duplicate=True),
    Input("decision-edit-save", "n_clicks"),
    State("decision-edit-target", "data"),
    State("decision-f-title", "value"),
    State("decision-f-statement", "value"),
    State("decision-f-rationale", "value"),
    State("decision-f-discussion", "value"),
    State("decision-f-owner", "value"),
    State("decision-f-stakeholders", "value"),
    State("decision-f-status", "value"),
    State("decision-f-priority", "value"),
    State("decision-f-decision-date", "value"),
    State("decision-f-due-date", "value"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def save_editor(
    n, target, title, statement, rationale, discussion, owner,
    stakeholders, status, priority, decision_date, due_date, version, user_store,
):
    uid = _uid(user_store)
    if not n or uid is None:
        return no_update, no_update
    fields = {
        "title": (title or "").strip() or "Untitled decision",
        "statement": statement or "",
        "rationale": rationale or "",
        "discussion": discussion or "",
        "owner": (owner or "").strip(),
        "stakeholders": _split_stakeholders(stakeholders),
        "status": status or "planned",
        "priority": priority or "med",
        "decision_date": (decision_date or "").strip() or None,
        "due_date": (due_date or "").strip() or None,
    }
    if target == _NEW:
        store.create_decision(uid, fields)
    else:
        store.update_decision(uid, target, fields)
    return False, (version or 0) + 1


# ── Reopen / delete from the detail panel ───────────────────────────────────


@callback(
    Output("decisions-version", "data", allow_duplicate=True),
    Output("decision-detail", "is_open", allow_duplicate=True),
    Input("decision-detail-reopen", "n_clicks"),
    State("decision-detail-target", "data"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def reopen_decision(n, target, version, user_store):
    if not n or not target:
        return no_update, no_update
    store.reopen_decision(
        _uid(user_store), target, status=model.REOPEN_TARGET, note="Reopened from board"
    )
    return (version or 0) + 1, False


@callback(
    Output("decisions-version", "data", allow_duplicate=True),
    Output("decision-detail", "is_open", allow_duplicate=True),
    Input("decision-detail-delete", "n_clicks"),
    State("decision-detail-target", "data"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def delete_decision(n, target, version, user_store):
    if not n or not target:
        return no_update, no_update
    store.delete_decision(_uid(user_store), target)
    return (version or 0) + 1, False
