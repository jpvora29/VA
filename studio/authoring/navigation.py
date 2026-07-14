"""Navigation callbacks: master render, mode switch, slide/tab/library moves.

Every handler here writes the ``qs-view`` store (which mode, which slide, which
tab/panel is open). The one exception is ``render``, which rebuilds the whole
shell whenever the view or the document changes.
"""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, no_update

from studio.page import authoring as A
from studio.page.sample import CUT_GROUPS

from studio.authoring.config import DEFAULT_FILTERS
from studio.authoring.generate import _deck, _friendly_options, usable_tdoc


def register_navigation(app):
    """Wire the render + view-navigation callbacks onto ``app``."""

    @app.callback(
        Output("qs-app", "children"),
        Input("qs-view", "data"),
        Input("qs-doc", "data"),
        Input("qs-tdoc", "data"),
        State("qs-selection", "data"),
    )
    def render(view, doc, tdoc, selection):
        deck = _deck(doc)
        tdoc = usable_tdoc(tdoc)   # a persisted doc whose temp .pptx is gone must not crash the app
        opts = _friendly_options()
        fvals = (selection or {}).get("filters") or DEFAULT_FILTERS
        return A.authoring_shell(
            deck,
            doc=doc,
            mode=(view or {}).get("mode", "setup"),
            view=view or {"idx": 0, "tab": "setup"},
            cut_groups=CUT_GROUPS,
            filter_options=opts,
            filter_values=fvals,
            tdoc=tdoc,
        )

    # ── mode switching ─────────────────────────────────────────────────────────

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-mode", "mode": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def switch_mode(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["mode"] = ctx.triggered_id["mode"]
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input("qs-empty-setup", "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def open_setup(n, view):
        if not n:
            return no_update
        view = dict(view or {})
        view["mode"] = "setup"
        return view

    # ── slide navigation + inspector tab ───────────────────────────────────────

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-goto", "idx": ALL, "src": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def goto(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["idx"] = int(ctx.triggered_id["idx"])
        view["sel"] = None  # changing page clears the selected widget
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-insp-tab", "tab": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def inspector_tab(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["tab"] = ctx.triggered_id["tab"]
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-zoom", "op": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def zoom_canvas(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["zoom"] = A.adjusted_zoom(view.get("zoom"), ctx.triggered_id["op"])
        return view

    # ── component library: category / tab / view / search / open / collapse ────

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-libcat", "category": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def component_category(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["lib_category"] = ctx.triggered_id["category"]
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-libtab", "tab": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def component_tab(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["lib_tab"] = ctx.triggered_id["tab"]
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-libview", "view": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def component_view(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["lib_view"] = ctx.triggered_id["view"]
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input("qs-lib-search", "value"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def component_search(value, view):
        view = dict(view or {})
        search = str(value or "")
        if search == str(view.get("lib_search") or ""):
            return no_update
        view["lib_search"] = search
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-lib-toggle", "op": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def toggle_library(_clicks, view):
        """Open/close the component-library popup (the + button / close / backdrop)."""
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        view = dict(view or {})
        view["library_open"] = ctx.triggered_id["op"] == "open"
        return view

    @app.callback(
        Output("qs-view", "data", allow_duplicate=True),
        Input({"type": "qs-panel-toggle", "panel": ALL}, "n_clicks"),
        State("qs-view", "data"),
        prevent_initial_call=True,
    )
    def toggle_canvas_panel(_clicks, view):
        if not ctx.triggered_id or not any(_clicks or []):
            return no_update
        panel = ctx.triggered_id["panel"]
        if panel not in {"inspector", "library"}:
            return no_update
        view = dict(view or {})
        key = f"{panel}_collapsed"
        view[key] = not bool(view.get(key, False))
        return view
