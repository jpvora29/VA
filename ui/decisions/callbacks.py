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
    Output("nav-chat-view", "className"),
    Output("nav-decision-board", "className"),
    Input("active-view", "data"),
)
def toggle_views(view: str | None) -> tuple[str, str, str, str]:
    on_board = view == "board"
    base = "sidebar-nav-item"
    active = f"{base} sidebar-nav-active"
    return (
        "view-pane view-hidden" if on_board else "view-pane",
        "view-pane" if on_board else "view-pane view-hidden",
        base if on_board else active,
        active if on_board else base,
    )


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
    Output("decision-detail-reopen", "disabled"),
    Input({"type": "decision-card", "id": ALL}, "n_clicks"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def open_detail(_clicks, user_store):
    if not _clicked():
        return no_update, no_update, no_update, no_update
    uid = _uid(user_store)
    did = ctx.triggered_id["id"]
    d = store.get_decision(uid, did)
    if d is None:
        return no_update, no_update, no_update, no_update
    body = render.detail_body(d, store.list_revisions(uid, did))
    return True, body, did, render.reopen_disabled(d["status"])


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


# Value outputs for the statically-mounted form fields, in render.FORM_VALUE_ORDER.
_FORM_VALUE_OUTPUTS = [
    Output(f"decision-f-{f.replace('_', '-')}", "value") for f in render.FORM_VALUE_ORDER
]
_N_OPEN_OUTPUTS = 4 + len(_FORM_VALUE_OUTPUTS)  # 4 control outputs + field values


@callback(
    Output("decision-edit-modal", "is_open"),
    Output("decision-edit-title", "children"),
    Output("decision-edit-target", "data"),
    Output("decision-detail", "is_open", allow_duplicate=True),
    *_FORM_VALUE_OUTPUTS,
    Input("decision-new-btn", "n_clicks"),
    Input("decision-detail-edit", "n_clicks"),
    State("decision-detail-target", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def open_editor(_new, _edit, target, user_store):
    """Open the editor and push values into the (static) form fields.

    New button → blank defaults; Edit → the selected decision's values.
    """
    if not _clicked():
        return (no_update,) * _N_OPEN_OUTPUTS
    if ctx.triggered_id == "decision-new-btn":
        return (True, "New decision", _NEW, no_update, *render.form_values(None))
    d = store.get_decision(_uid(user_store), target)
    if d is None:
        return (no_update,) * _N_OPEN_OUTPUTS
    return (True, "Edit decision", target, False, *render.form_values(d))


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
