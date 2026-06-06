"""Edit-mode callbacks for the editable Boardroom.

Importing this module registers the callbacks (side effect). All actions mutate the
``doc`` embedded in the relevant Boardroom chat message (located by ``idx`` = the
message's position), then write ``chat-store`` so ``render_chat`` repaints. Pure
data mutations go through ``ui.boardroom.model`` / ``builder`` so the provenance and
governed-grid rules are enforced in one place.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from ui.boardroom import builder, editor, model


# ───────────────────────── helpers ─────────────────────────


def _doc_at(chat_history: Dict[str, Any], idx: int) -> Optional[Dict[str, Any]]:
    msgs = (chat_history or {}).get("messages") or []
    if isinstance(idx, int) and 0 <= idx < len(msgs) and msgs[idx].get("type") == "Boardroom":
        return msgs[idx].get("doc")
    return None


def _triggered_value() -> Any:
    return ctx.triggered[0]["value"] if ctx.triggered else None


def _user_id(user_store: Dict[str, Any]) -> Optional[str]:
    us = user_store or {}
    uid = us.get("user_id") or us.get("id") or us.get("username")
    return str(uid) if uid is not None else None


# ───────────────────────── edit mode toggle ─────────────────────────


@callback(
    Output("boardroom-edit-mode", "data"),
    Input({"type": "bm-edit-mode", "idx": ALL}, "n_clicks"),
    State("boardroom-edit-mode", "data"),
    prevent_initial_call=True,
)
def toggle_edit_mode(clicks, current):
    if not _triggered_value():
        return no_update
    return not bool(current)


# ───────────────────────── widget actions ─────────────────────────


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Input({"type": "bm-w-dup", "idx": ALL, "wid": ALL}, "n_clicks"),
    Input({"type": "bm-w-hide", "idx": ALL, "wid": ALL}, "n_clicks"),
    Input({"type": "bm-w-del", "idx": ALL, "wid": ALL}, "n_clicks"),
    Input({"type": "bm-w-reset", "idx": ALL, "wid": ALL}, "n_clicks"),
    Input({"type": "bm-w-up", "idx": ALL, "wid": ALL}, "n_clicks"),
    Input({"type": "bm-w-down", "idx": ALL, "wid": ALL}, "n_clicks"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def widget_actions(_dup, _hide, _del, _reset, _up, _down, chat_history):
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not _triggered_value():
        return no_update
    doc = _doc_at(chat_history, tid.get("idx"))
    if doc is None:
        return no_update
    wid, typ = tid.get("wid"), tid.get("type")

    if typ == "bm-w-dup":
        model.duplicate_widget(doc, wid)
    elif typ == "bm-w-del":
        model.delete_widget(doc, wid)
    elif typ == "bm-w-up":
        model.move_widget(doc, wid, -1)
    elif typ == "bm-w-down":
        model.move_widget(doc, wid, 1)
    elif typ == "bm-w-reset":
        _, w = model.find_widget(doc, wid)
        if w:
            model.reset_widget(w)
    elif typ == "bm-w-hide":
        _, w = model.find_widget(doc, wid)
        if w:
            w["meta"]["visible_board"] = not w["meta"].get("visible_board", True)
    else:
        return no_update
    return chat_history


# ───────────────────────── editor modal ─────────────────────────


@callback(
    Output("bm-editor-modal", "is_open", allow_duplicate=True),
    Output("bm-editor-body", "children"),
    Output("boardroom-edit-target", "data"),
    Input({"type": "bm-w-edit", "idx": ALL, "wid": ALL}, "n_clicks"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def open_editor(clicks, chat_history):
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not _triggered_value():
        return no_update, no_update, no_update
    doc = _doc_at(chat_history, tid.get("idx"))
    _, w = model.find_widget(doc, tid.get("wid")) if doc else (None, None)
    if not w:
        return no_update, no_update, no_update
    return True, editor.build_editor_body(w), {"idx": tid["idx"], "wid": tid["wid"]}


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("bm-editor-modal", "is_open", allow_duplicate=True),
    Input("bm-editor-save", "n_clicks"),
    State({"type": "bm-ef", "key": ALL}, "value"),
    State({"type": "bm-ef", "key": ALL}, "id"),
    State("boardroom-edit-target", "data"),
    State("chat-store", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def save_editor(n, values, ids, target, chat_history, user_store):
    if not n or not target:
        return no_update, no_update
    doc = _doc_at(chat_history, target.get("idx"))
    _, w = model.find_widget(doc, target.get("wid")) if doc else (None, None)
    if not w:
        return no_update, False
    collected = {i["key"]: v for i, v in zip(ids, values)}
    editor.apply_editor(w, collected, _user_id(user_store))
    return chat_history, False


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("bm-editor-modal", "is_open", allow_duplicate=True),
    Input("bm-editor-reset", "n_clicks"),
    State("boardroom-edit-target", "data"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def reset_in_editor(n, target, chat_history):
    if not n or not target:
        return no_update, no_update
    doc = _doc_at(chat_history, target.get("idx"))
    _, w = model.find_widget(doc, target.get("wid")) if doc else (None, None)
    if not w:
        return no_update, False
    model.reset_widget(w)
    return chat_history, False


@callback(
    Output("bm-editor-modal", "is_open", allow_duplicate=True),
    Input("bm-editor-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_editor(n):
    return False if n else no_update


# ───────────────────────── add-widget library ─────────────────────────


@callback(
    Output("bm-library-modal", "is_open", allow_duplicate=True),
    Output("boardroom-add-target", "data"),
    Input({"type": "bm-add-widget", "idx": ALL, "pid": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def open_library(clicks):
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not _triggered_value():
        return no_update, no_update
    return True, {"idx": tid["idx"], "pid": tid["pid"]}


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Output("bm-library-modal", "is_open", allow_duplicate=True),
    Input({"type": "bm-lib-pick", "kind": ALL}, "n_clicks"),
    State("boardroom-add-target", "data"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def library_pick(clicks, target, chat_history):
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not _triggered_value() or not target:
        return no_update, no_update
    doc = _doc_at(chat_history, target.get("idx"))
    if doc is None:
        return no_update, False
    builder.add_library_widget(doc, target.get("pid"), tid["kind"])
    return chat_history, False


# ───────────────────────── page actions ─────────────────────────


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Input({"type": "bm-page-add", "idx": ALL}, "n_clicks"),
    Input({"type": "bm-page-dup", "idx": ALL, "pid": ALL}, "n_clicks"),
    Input({"type": "bm-page-del", "idx": ALL, "pid": ALL}, "n_clicks"),
    Input({"type": "bm-page-up", "idx": ALL, "pid": ALL}, "n_clicks"),
    Input({"type": "bm-page-down", "idx": ALL, "pid": ALL}, "n_clicks"),
    Input({"type": "bm-page-lock", "idx": ALL, "pid": ALL}, "n_clicks"),
    Input({"type": "bm-page-exp", "idx": ALL, "pid": ALL}, "n_clicks"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def page_actions(_add, _dup, _del, _up, _down, _lock, _exp, chat_history):
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not _triggered_value():
        return no_update
    doc = _doc_at(chat_history, tid.get("idx"))
    if doc is None:
        return no_update
    typ, pid = tid.get("type"), tid.get("pid")

    if typ == "bm-page-add":
        builder.blank_page(doc)
    elif typ == "bm-page-dup":
        model.duplicate_page(doc, pid)
    elif typ == "bm-page-del":
        model.delete_page(doc, pid)
    elif typ == "bm-page-up":
        model.move_page(doc, pid, -1)
    elif typ == "bm-page-down":
        model.move_page(doc, pid, 1)
    elif typ == "bm-page-lock":
        p = model.find_page(doc, pid)
        if p:
            p["locked"] = not p.get("locked", False)
    elif typ == "bm-page-exp":
        p = model.find_page(doc, pid)
        if p:
            p["visible_export"] = not p.get("visible_export", True)
    else:
        return no_update
    return chat_history


@callback(
    Output("chat-store", "data", allow_duplicate=True),
    Input({"type": "bm-page-title", "idx": ALL, "pid": ALL}, "value"),
    Input({"type": "bm-page-notes", "idx": ALL, "pid": ALL}, "value"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def page_text(titles, notes, chat_history):
    tid = ctx.triggered_id
    if not isinstance(tid, dict):
        return no_update
    doc = _doc_at(chat_history, tid.get("idx"))
    p = model.find_page(doc, tid.get("pid")) if doc else None
    if not p:
        return no_update
    val = _triggered_value()
    field = "title" if tid.get("type") == "bm-page-title" else "notes"
    if (p.get(field) or "") == (val or ""):
        return no_update  # no real change -> avoid a render loop
    p[field] = val or ""
    return chat_history


# ───────────────────────── source / history info ─────────────────────────


def _pretty(obj) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)


@callback(
    Output("bm-info-modal", "is_open", allow_duplicate=True),
    Output("bm-info-title", "children"),
    Output("bm-info-body", "children"),
    Input({"type": "bm-w-src", "idx": ALL, "wid": ALL}, "n_clicks"),
    Input({"type": "bm-w-hist", "idx": ALL, "wid": ALL}, "n_clicks"),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def show_info(src_clicks, hist_clicks, chat_history):
    tid = ctx.triggered_id
    if not isinstance(tid, dict) or not _triggered_value():
        return no_update, no_update, no_update
    doc = _doc_at(chat_history, tid.get("idx"))
    _, w = model.find_widget(doc, tid.get("wid")) if doc else (None, None)
    if not w:
        return no_update, no_update, no_update

    if tid.get("type") == "bm-w-src":
        body = html.Div(
            [
                html.Div("Generated evidence (immutable)", className="bm-info-h"),
                html.Pre(_pretty(w.get("generated")), className="bm-info-pre"),
                html.Div("Current display value", className="bm-info-h"),
                html.Pre(_pretty(w.get("data")), className="bm-info-pre"),
            ]
        )
        return True, "Source evidence", body

    hist = w.get("history") or []
    if not hist:
        return True, "Revision history", html.Div("No edits yet.", className="bm-info-empty")
    rows = [
        html.Div(
            [
                html.Div([html.Span(h.get("at", ""), className="bm-hist-at"),
                          html.Span(h.get("source", ""), className="bm-hist-src")], className="bm-hist-head"),
                html.Div(f"by {h.get('by') or 'system'}", className="bm-hist-by"),
                html.Div(h.get("reason") or "", className="bm-hist-reason") if h.get("reason") else None,
                html.Pre(_pretty(h.get("changes")), className="bm-info-pre") if h.get("changes") else None,
            ],
            className="bm-hist-item",
        )
        for h in reversed(hist)
    ]
    return True, "Revision history", html.Div(rows, className="bm-hist")
