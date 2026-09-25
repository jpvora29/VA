"""Decision Board interaction callbacks (registered on import, like boardroom).

Everything here is plain CRUD against ``core.store.decisions`` plus a tiny
view-router that toggles the chat / board panes. No LLM is involved. A single
``decisions-version`` counter is bumped after any mutation to repaint the board;
the brief beside the queue is driven by ``decision-selected``.

Each callback is thin on purpose: what the board *shows* is
``ui.decisions.board``, and what it *looks like* is ``render`` / ``queue`` /
``brief``. A callback resolves inputs, calls one of those, and returns.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from dash import ALL, Input, Output, State, callback, ctx, no_update

from core.store import decisions as store
from ui.decisions import board, brief, evidence, model, render

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


# ── The three controls that only change what is shown ───────────────────────


@callback(
    Output("decision-view", "data"),
    Input({"type": "decision-view", "view": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def choose_view(_clicks):
    """Board / List / Agenda. A view, so nothing about the records changes."""
    if not _clicked():
        return no_update
    return ctx.triggered_id["view"]


@callback(
    Output("decision-week", "data"),
    Input("decision-week-prev", "n_clicks"),
    Input("decision-week-next", "n_clicks"),
    Input("decision-week-today", "n_clicks"),
    Input("decision-view", "data"),
    State("decision-week", "data"),
    prevent_initial_call=True,
)
def step_week(_prev, _next, _today, _view, offset):
    """Page the agenda's week ribbon, and snap back to today's week on a switch.

    Snapping on a view change is deliberate: coming back to the Agenda three
    weeks out from where you last left it reads as a bug, not as memory.
    """
    steps = {"decision-week-prev": -1, "decision-week-next": 1}
    trigger = ctx.triggered_id
    if trigger in ("decision-week-today", "decision-view"):
        return 0
    if trigger not in steps or not _clicked():
        return no_update
    return (offset or 0) + steps[trigger]


@callback(
    Output("decision-scope", "data"),
    Input("decision-archive-toggle", "n_clicks"),
    State("decision-scope", "data"),
    prevent_initial_call=True,
)
def toggle_archive(_n, scope):
    """One click into the archive, one click back — never a filter to remember."""
    if not _clicked():
        return no_update
    return "active" if scope == "archived" else "archived"


# ── Board painting ──────────────────────────────────────────────────────────


@callback(
    Output("decision-board", "children"),
    Output("decision-ribbon", "className"),
    Output("decision-week-label", "children"),
    Output("decision-week-days", "children"),
    Output("decision-week-today", "disabled"),
    Output("decision-counts", "children"),
    Output("decision-archive-toggle", "children"),
    Output("decision-filter-owner", "options"),
    Output("decision-view-switch", "children"),
    Input("active-view", "data"),
    Input("decision-view", "data"),
    Input("decision-scope", "data"),
    Input("decision-week", "data"),
    Input("decision-search", "value"),
    Input("decision-filter-owner", "value"),
    Input("decision-filter-status", "value"),
    Input("decision-filter-priority", "value"),
    Input("decision-sort", "value"),
    Input("decisions-version", "data"),
    Input("decision-selected", "data"),
    State("user-store", "data"),
)
def paint_board(
    pane, view, scope, week, search, owners, statuses, priorities, sort,
    _version, selected, user_store,
):
    """Repaint every region of the board from one resolved request."""
    uid = _uid(user_store)
    if uid is None or pane != "board":
        return (no_update,) * 9
    request = board.build_board_request(
        user_id=uid,
        view=view,
        scope=scope,
        week_offset=week,
        selected=selected,
        search=search,
        statuses=statuses,
        priorities=priorities,
        owners=owners,
        sort=sort,
    )
    painted = board.build_board_view(request)
    return (
        painted.queue,
        painted.ribbon_class,
        painted.week_label,
        painted.week_days,
        painted.at_this_week,
        painted.counts,
        painted.archive,
        painted.owner_options,
        painted.switch,
    )


# ── Selecting a decision into the brief ─────────────────────────────────────


@callback(
    Output("decision-selected", "data"),
    Input({"type": "decision-row", "id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_decision(_clicks):
    """A row or a card selects; the brief beside the queue does the rest."""
    return ctx.triggered_id["id"] if _clicked() else no_update


@callback(
    Output("decision-brief-content", "children"),
    Output("decision-move", "value"),
    Output("decision-move", "disabled"),
    Output("decision-detail-edit", "disabled"),
    Output("decision-detail-delete", "disabled"),
    Output("decision-detail-reopen", "disabled"),
    Input("decision-selected", "data"),
    Input("decisions-version", "data"),
    State("user-store", "data"),
)
def paint_brief(selected, _version, user_store):
    """Repaint the brief for the selected record — also after any edit to it.

    With nothing selected every action is disabled rather than merely inert. A
    live-looking Delete beside an empty panel is a question about what it would
    delete, and the answer "nothing" is not one the button should have to give.
    """
    uid = _uid(user_store)
    d = store.get_decision(uid, selected) if (uid is not None and selected) else None
    if d is None:
        return brief.empty_brief(), None, True, True, True, True
    return (
        brief.decision_brief(d, store.list_revisions(uid, selected), date.today()),
        d["status"],
        False,
        False,
        False,
        brief.reopen_disabled(d["status"]),
    )


# ── Mutations ───────────────────────────────────────────────────────────────


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


@callback(
    Output("decisions-version", "data", allow_duplicate=True),
    Input("decision-move", "value"),
    State("decision-selected", "data"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def move_status(status, selected, version, user_store):
    """The brief's "Move to" control — a status change without dragging anything.

    No-ops when the value already matches the record, because painting the brief
    sets this control to the record's current status and that must not be read
    back as an edit.
    """
    uid = _uid(user_store)
    if uid is None or not selected or status not in store.STATUSES:
        return no_update
    current = store.get_decision(uid, selected)
    if current is None or current["status"] == status:
        return no_update
    store.change_status(uid, selected, status)
    return (version or 0) + 1


@callback(
    Output("decisions-version", "data", allow_duplicate=True),
    Input("decision-detail-reopen", "n_clicks"),
    State("decision-selected", "data"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def reopen_decision(n, target, version, user_store):
    if not n or not target:
        return no_update
    store.reopen_decision(
        _uid(user_store), target, status=model.REOPEN_TARGET, note="Reopened from board"
    )
    return (version or 0) + 1


@callback(
    Output("decisions-version", "data", allow_duplicate=True),
    Output("decision-selected", "data", allow_duplicate=True),
    Input("decision-detail-delete", "n_clicks"),
    State("decision-selected", "data"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def delete_decision(n, target, version, user_store):
    if not n or not target:
        return no_update, no_update
    store.delete_decision(_uid(user_store), target)
    return (version or 0) + 1, None


# ── Raising a decision from a chat answer ───────────────────────────────────


def seed_from_answer(
    chat_history: dict[str, Any] | None, idx: Any
) -> Optional[dict[str, Any]]:
    """A decision draft seeded from one chat answer.

    Deliberately fills only the fields the answer can honestly supply: the
    question becomes the title (it is what the reader was asking about), the
    answer becomes the rationale (it is the reasoning), and the turn's scope,
    dataset and one verified figure become the evidence snapshot the decision is
    taken on. Owner, status, priority and the dates are business judgements the
    answer does not contain, so they keep their blank defaults.

    Returns ``None`` for a stale index, which `render.form_values` already reads
    as "blank new decision".
    """
    messages = (chat_history or {}).get("messages", [])
    if not isinstance(idx, int) or not 0 <= idx < len(messages):
        return None
    answer = messages[idx] or {}
    question = (answer.get("question") or "").strip()
    snapshot = evidence.snapshot_from_answer(answer)
    return {
        "title": _title_from(question),
        "rationale": (answer.get("content") or "").strip(),
        "evidence": [snapshot.as_dict()] if snapshot else [],
    }


def _title_from(question: str) -> str:
    """A short decision title from the question that produced the answer."""
    text = " ".join((question or "").split()).rstrip("?").strip()
    if not text:
        return "Decision from analysis"
    return text if len(text) <= _TITLE_MAX else text[: _TITLE_MAX - 1].rstrip() + "…"


#: Titles are a row heading on the board; a full sentence overflows it.
_TITLE_MAX = 80


# ── Create / edit modal ─────────────────────────────────────────────────────


# Value outputs for the statically-mounted form fields, in render.FORM_VALUE_ORDER.
_FORM_VALUE_OUTPUTS = [
    Output(f"decision-f-{f.replace('_', '-')}", "value") for f in render.FORM_VALUE_ORDER
]
_N_OPEN_OUTPUTS = 5 + len(_FORM_VALUE_OUTPUTS)  # 5 control outputs + field values


@callback(
    Output("decision-edit-modal", "is_open"),
    Output("decision-edit-title", "children"),
    Output("decision-edit-target", "data"),
    Output("decision-draft-evidence", "data"),
    Output("decision-form-evidence", "children"),
    *_FORM_VALUE_OUTPUTS,
    Input("decision-new-btn", "n_clicks"),
    Input("decision-detail-edit", "n_clicks"),
    Input({"type": "answer-action", "idx": ALL, "action": "decision"}, "n_clicks"),
    State("decision-selected", "data"),
    State("chat-store", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def open_editor(_new, _edit, _from_answer, target, chat_history, user_store):
    """Open the editor and push values into the (static) form fields.

    New button → blank defaults; Edit → the selected decision's values; the
    "Create decision" action under a chat answer → a draft seeded from that
    answer, which is the whole point of the action: the finding, its numbers and
    the scope it was measured under arrive with it instead of being retyped from
    the transcript.
    """
    if not _clicked():
        return (no_update,) * _N_OPEN_OUTPUTS
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("action") == "decision":
        return _open_draft(seed_from_answer(chat_history, triggered.get("idx")))
    if triggered == "decision-new-btn":
        return _open_draft(None)
    d = store.get_decision(_uid(user_store), target)
    if d is None:
        return (no_update,) * _N_OPEN_OUTPUTS
    return (
        True,
        "Edit decision",
        target,
        no_update,
        render.evidence_preview(evidence.snapshots(d.get("evidence"))),
        *render.form_values(d),
    )


def _open_draft(seed: dict[str, Any] | None) -> tuple[Any, ...]:
    """Open the editor on a new decision, carrying any captured evidence with it."""
    items = evidence.snapshots((seed or {}).get("evidence"))
    return (
        True,
        "New decision",
        _NEW,
        [item.as_dict() for item in items],
        render.evidence_preview(items),
        *render.form_values(seed),
    )


@callback(
    Output("active-view", "data", allow_duplicate=True),
    Input({"type": "answer-action", "idx": ALL, "action": "decision"}, "n_clicks"),
    prevent_initial_call=True,
)
def show_board_for_new_decision(_clicks):
    """Switch to the board so the editor the action just opened is visible.

    The two views are both mounted and toggled with ``display: none``, so opening
    the modal from the chat pane would otherwise put it inside a hidden subtree.
    """
    return "board" if _clicked() else no_update


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
    Output("decision-selected", "data", allow_duplicate=True),
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
    State("decision-draft-evidence", "data"),
    State("decisions-version", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def save_editor(
    n, target, title, statement, rationale, discussion, owner, stakeholders,
    status, priority, decision_date, due_date, draft_evidence, version, user_store,
):
    """Write the form, and select what was written so the brief shows the result."""
    uid = _uid(user_store)
    if not n or uid is None:
        return no_update, no_update, no_update
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
        # Evidence is written only on create. An edit must not touch it: the
        # snapshot is what the decision was taken on, and the editor has no
        # control that could have changed it.
        fields["evidence"] = list(draft_evidence or [])
        selected = store.create_decision(uid, fields)
    else:
        store.update_decision(uid, target, fields)
        selected = target
    return False, (version or 0) + 1, selected or no_update
