"""Editing callbacks: every mutation of the shared document.

Field edits, page reorder/hide/duplicate/delete, canvas select/move/resize,
add/duplicate/delete widget, text props, styles, colors, and chart type — all
of them read the document, apply one change via ``studio.page.document`` (D),
and write it back so the deck and the export stay in sync.
"""
from __future__ import annotations

import json

from dash import ALL, Input, Output, State, ctx, no_update

from studio.page import document as D


def _apply_color(doc, view, tid, value):
    """Apply a color to a page, a widget, or a text role — whichever the swatch targets."""
    if not doc or not D.is_hex_color(value):
        return no_update
    if tid["scope"] == "page":
        current = D.effective_page_style(doc, tid["owner"]).get(tid["prop"])
        if current == str(value).upper():
            return no_update
        return D.set_page_style(doc, tid["owner"], tid["prop"], value)
    sid = D.sid_at(doc, int((view or {}).get("idx", 0)))
    if sid is None:
        return no_update
    if tid["scope"] == "text":
        wid, role = tid["owner"].split("::", 1)
        current = D.effective_text_style(doc, sid, wid, role).get(tid["prop"])
        if current == str(value).upper():
            return no_update
        return D.set_widget_text_style(doc, sid, wid, role, tid["prop"], value)
    current = D.effective_widget_style(doc, sid, tid["owner"]).get(tid["prop"])
    if current == str(value).upper():
        return no_update
    return D.set_widget_prop(doc, sid, tid["owner"], tid["prop"], value)


def register_editing(app):
    """Wire every document-editing callback onto ``app``."""

    # ── editable fields (commit on blur so typing doesn't re-render mid-keystroke) ─

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input({"type": "qs-edit", "field": ALL, "idx": ALL}, "n_blur"),
        State({"type": "qs-edit", "field": ALL, "idx": ALL}, "value"),
        State({"type": "qs-edit", "field": ALL, "idx": ALL}, "id"),
        State("qs-doc", "data"),
        prevent_initial_call=True,
    )
    def edit_field(_blurs, values, ids, doc):
        if not ctx.triggered_id or not doc:
            return no_update
        tid = ctx.triggered_id
        val = next((v for v, i in zip(values or [], ids or []) if i == tid), None)
        sid = D.sid_at(doc, int(tid["idx"]))
        if sid is None:
            return no_update
        return D.set_edit(doc, sid, tid["field"], val)

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input({"type": "qs-reset", "field": ALL, "idx": ALL}, "n_clicks"),
        State("qs-doc", "data"),
        prevent_initial_call=True,
    )
    def reset_field(_clicks, doc):
        if not ctx.triggered_id or not any(_clicks or []) or not doc:
            return no_update
        sid = D.sid_at(doc, int(ctx.triggered_id["idx"]))
        return D.reset_edit(doc, sid, ctx.triggered_id["field"]) if sid else no_update

    # ── widget config (chart type) — a real, persisted layout/config change ──────

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input({"type": "qs-chart", "idx": ALL}, "value"),
        State({"type": "qs-chart", "idx": ALL}, "id"),
        State("qs-doc", "data"),
        prevent_initial_call=True,
    )
    def set_chart(values, ids, doc):
        if not ctx.triggered_id or not doc:
            return no_update
        val = next((v for v, i in zip(values or [], ids or []) if i == ctx.triggered_id), None)
        sid = D.sid_at(doc, int(ctx.triggered_id["idx"]))
        if sid is None or not val:
            return no_update
        if D.chart_kind(doc, sid) == val:
            return no_update
        return D.set_config(doc, sid, "chart", val)

    # ── page operations (reorder / hide / duplicate / delete) ────────────────────

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-pageop", "op": ALL, "idx": ALL}, "n_clicks"),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def page_op(_clicks, doc, view):
        if not ctx.triggered_id or not any(_clicks or []) or not doc:
            return no_update, no_update
        op, pos = ctx.triggered_id["op"], int(ctx.triggered_id["idx"])
        view = dict(view or {})
        view["sel"] = None
        if op == "up":
            doc, view["idx"] = D.move(doc, pos, -1)
        elif op == "down":
            doc, view["idx"] = D.move(doc, pos, +1)
        elif op == "hide":
            doc = D.toggle_hidden(doc, pos)
        elif op == "duplicate":
            doc, view["idx"] = D.duplicate(doc, pos)
        elif op == "delete":
            doc, view["idx"] = D.delete(doc, pos)
        elif op == "add":
            doc, view["idx"] = D.add_blank_slide(doc, pos)
        elif op == "section":
            doc, view["idx"] = D.add_divider_slide(doc, pos)
        else:
            return no_update, no_update
        return doc, view

    # ── canvas: select / move / resize (from the JS via the hidden sink) ─────────

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Input("qs-cv-sink", "value"),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def canvas_action(payload, doc, view):
        if not payload or not doc:
            return no_update, no_update
        try:
            action = json.loads(payload.split("@", 1)[0])  # strip the nonce
        except (ValueError, AttributeError):
            return no_update, no_update
        view = dict(view or {})
        sid = D.sid_at(doc, int(view.get("idx", 0)))
        if sid is None:
            return no_update, no_update
        if action.get("action") == "select":
            view["sel"] = action.get("wid")
            return no_update, view
        if action.get("action") == "geo":
            doc = D.set_widget_geo(doc, sid, action["wid"], action["x"], action["y"], action["w"], action["h"])
            view["sel"] = action["wid"]
            return doc, view
        return no_update, no_update

    # ── canvas: add widget from the palette ──────────────────────────────────────

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-addw", "kind": ALL}, "n_clicks"),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def add_widget(_clicks, doc, view):
        if not ctx.triggered_id or not any(_clicks or []) or not doc:
            return no_update, no_update
        view = dict(view or {})
        sid = D.sid_at(doc, int(view.get("idx", 0)))
        if sid is None:
            return no_update, no_update
        doc, wid = D.add_widget(doc, sid, ctx.triggered_id["kind"])
        view["sel"] = wid
        view["library_open"] = False  # close the component popup after adding
        return doc, view

    # ── canvas: widget duplicate / delete ────────────────────────────────────────

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-wop", "op": ALL, "wid": ALL}, "n_clicks"),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def widget_op(_clicks, doc, view):
        if not ctx.triggered_id or not any(_clicks or []) or not doc:
            return no_update, no_update
        view = dict(view or {})
        sid = D.sid_at(doc, int(view.get("idx", 0)))
        wid, op = ctx.triggered_id["wid"], ctx.triggered_id["op"]
        if sid is None:
            return no_update, no_update
        if op == "delete":
            doc = D.delete_widget(doc, sid, wid)
            view["sel"] = None
        elif op == "duplicate":
            doc, view["sel"] = D.duplicate_widget(doc, sid, wid)
        else:
            return no_update, no_update
        return doc, view

    # ── canvas: widget text props (commit on blur), styles, colors, chart type ───

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input({"type": "qs-wprop", "wid": ALL, "prop": ALL}, "n_blur"),
        State({"type": "qs-wprop", "wid": ALL, "prop": ALL}, "value"),
        State({"type": "qs-wprop", "wid": ALL, "prop": ALL}, "id"),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def widget_prop(_blurs, values, ids, doc, view):
        if not ctx.triggered_id or not doc:
            return no_update
        tid = ctx.triggered_id
        val = next((v for v, i in zip(values or [], ids or []) if i == tid), None)
        sid = D.sid_at(doc, int((view or {}).get("idx", 0)))
        if sid is None:
            return no_update
        return D.set_widget_prop(doc, sid, tid["wid"], tid["prop"], val)

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input({"type": "qs-wstyle", "wid": ALL, "prop": ALL}, "value"),
        State({"type": "qs-wstyle", "wid": ALL, "prop": ALL}, "id"),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def widget_style(values, ids, doc, view):
        if not ctx.triggered_id or not doc:
            return no_update
        tid = ctx.triggered_id
        value = next((v for v, i in zip(values or [], ids or []) if i == tid), None)
        sid = D.sid_at(doc, int((view or {}).get("idx", 0)))
        if sid is None or value in (None, ""):
            return no_update
        current = D.effective_widget_style(doc, sid, tid["wid"]).get(tid["prop"])
        if tid["prop"] == "font_size":
            comparable = int(value)
        elif tid["prop"] in {"font_color", "background_color"}:
            comparable = str(value).upper()
        else:
            comparable = value
        if current == comparable:
            return no_update
        return D.set_widget_prop(doc, sid, tid["wid"], tid["prop"], value)

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input(
            {"type": "qs-tstyle", "wid": ALL, "role": ALL, "prop": ALL},
            "value",
        ),
        State(
            {"type": "qs-tstyle", "wid": ALL, "role": ALL, "prop": ALL},
            "id",
        ),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def text_style(values, ids, doc, view):
        if not ctx.triggered_id or not doc:
            return no_update
        tid = ctx.triggered_id
        value = next((v for v, item in zip(values or [], ids or []) if item == tid), None)
        sid = D.sid_at(doc, int((view or {}).get("idx", 0)))
        if sid is None or value in (None, ""):
            return no_update
        current = D.effective_text_style(doc, sid, tid["wid"], tid["role"]).get(
            tid["prop"]
        )
        comparable = int(value) if tid["prop"] == "font_size" else value
        if current == comparable:
            return no_update
        return D.set_widget_text_style(
            doc, sid, tid["wid"], tid["role"], tid["prop"], value
        )

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input(
            {
                "type": "qs-color-swatch",
                "scope": ALL,
                "owner": ALL,
                "prop": ALL,
                "value": ALL,
            },
            "n_clicks",
        ),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def color_swatch(_clicks, doc, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        tid = ctx.triggered_id
        return _apply_color(doc, view, tid, tid["value"])

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input(
            {
                "type": "qs-color-custom",
                "scope": ALL,
                "owner": ALL,
                "prop": ALL,
            },
            "value",
        ),
        State(
            {
                "type": "qs-color-custom",
                "scope": ALL,
                "owner": ALL,
                "prop": ALL,
            },
            "id",
        ),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def custom_color(values, ids, doc, view):
        if not ctx.triggered_id or not doc:
            return no_update
        tid = ctx.triggered_id
        value = next((v for v, item in zip(values or [], ids or []) if item == tid), None)
        return _apply_color(doc, view, tid, value)

    @app.callback(
        Output("qs-doc", "data", allow_duplicate=True),
        Input({"type": "qs-wchart", "wid": ALL}, "value"),
        State({"type": "qs-wchart", "wid": ALL}, "id"),
        State("qs-doc", "data"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def widget_chart(values, ids, doc, view):
        if not ctx.triggered_id or not doc:
            return no_update
        val = next((v for v, i in zip(values or [], ids or []) if i == ctx.triggered_id), None)
        sid = D.sid_at(doc, int((view or {}).get("idx", 0)))
        if sid is None or not val:
            return no_update
        w = D.get_widget(doc, sid, ctx.triggered_id["wid"])
        if w and w.get("props", {}).get("chart") == val:
            return no_update
        return D.set_widget_prop(doc, sid, ctx.triggered_id["wid"], "chart", val)
