"""QBR Studio authoring workspace — runnable, wired to the real DB.

A single hybrid workspace (Setup → Narrative → Canvas → Review → Export) built on
ONE shared, editable document (``studio.page.document``). Generate snapshots the
deterministic ``DeckSpec`` into a document; every edit, reorder, hide, delete and
widget-config change mutates that document; and BOTH the on-screen deck and the
PowerPoint export are produced by ``materialize(doc)`` — so what you edit is what
exports. The document lives in a persisted store, so it survives a refresh.

    python authoring_app.py   →   http://127.0.0.1:8131
"""
from __future__ import annotations

import json
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from studio.compute import FILTER_COLUMN, compute_overall
from studio.data import cached_filter_options, get_engine
from studio.deck import build_deck
from studio.deck.model import DeckSpec
from studio.export import export_document
from studio.page import authoring as A
from studio.page import document as D
from studio.page.sample import CUT_GROUPS
from studio.template_fill import fill_template, new_template_doc, registry
from studio.template_fill import validate as TV
from studio.template_fill.model import add_element, set_override

_ASSETS = str(Path(__file__).resolve().parent / "assets")
_BREAKDOWNS = ["Product_Line", "SIC_Major_Class"]
_BLANK = (None, "", [], "all", "All")
# Sensible defaults so the Setup form is pre-filled and a deck is one click away.
_DEFAULT_FILTERS = {"carrier": "Zurich", "country": ["Singapore"], "year": 2025}

engine = get_engine()  # cheap: opens the engine, runs no query


# ── selection → generated deck (cached so Generate doesn't re-query needlessly) ─


def _friendly_options() -> Dict[str, Any]:
    """DB filter options keyed back to the form's friendly ids (region, carrier…)."""
    col_opts = cached_filter_options("gpr")
    return {fid: col_opts.get(col, []) for fid, col in FILTER_COLUMN.items()}


def _one(value):
    """Unwrap a single-element multi-select list to a scalar for clean display."""
    if isinstance(value, (list, tuple)):
        return value[0] if len(value) == 1 else ", ".join(str(v) for v in value)
    return value


def _latest_year(value):
    """The reporting year passed to the content spec — MAX of a multi-select year."""
    if isinstance(value, (list, tuple)):
        years = [int(v) for v in value if str(v).strip().isdigit()]
        return max(years) if years else None
    return value


@lru_cache(maxsize=64)
def _deck_for(selection_json: str) -> Optional[DeckSpec]:
    """Build the generated deck for a frozen selection (JSON key → hashable)."""
    sel = json.loads(selection_json)
    filters = {k: v for k, v in (sel.get("filters") or {}).items() if v not in _BLANK}
    result = compute_overall(
        filters=filters,
        breakdowns=sel.get("breakdowns") or _BREAKDOWNS,
        engine=engine,
        peers=sel.get("peers") or None,
    )
    return build_deck(
        result,
        carrier=_one(filters.get("carrier")),
        country=_one(filters.get("country")),
        year=_latest_year(filters.get("year")),
        report=sel.get("report") or "qbr",
        cuts=tuple(sel.get("cuts") or ()),
        ai=bool(sel.get("ai")),
        audience=sel.get("audience") or "executive",
        meeting_length=sel.get("meeting_length") or "standard",
    )


def _generated_deck(selection: Optional[Dict[str, Any]]) -> Optional[DeckSpec]:
    if not selection or not selection.get("filters", {}).get("carrier"):
        return None
    try:
        return _deck_for(json.dumps(selection, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 — a bad selection must not white-screen the app
        from logger import get_logger

        get_logger(__name__).warning("deck build failed: %s", exc)
        return None


@lru_cache(maxsize=32)
def _tdoc_for(selection_json: str) -> Optional[Dict[str, Any]]:
    """Seed a template doc (active template, filled from the same OverallResult)."""
    sel = json.loads(selection_json)
    filters = {k: v for k, v in (sel.get("filters") or {}).items() if v not in _BLANK}
    result = compute_overall(
        filters=filters,
        breakdowns=sel.get("breakdowns") or _BREAKDOWNS,
        engine=engine,
        peers=sel.get("peers") or None,
    )
    return new_template_doc(result, template_path=sel.get("template_path") or None,
                            use_ai=bool(sel.get("ai")))


def _generated_tdoc(selection: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not selection or not selection.get("filters", {}).get("carrier"):
        return None
    try:
        return _tdoc_for(json.dumps(selection, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 — template issues must not white-screen the app
        from logger import get_logger

        get_logger(__name__).warning("template doc build failed: %s", exc)
        return None


def _deck(doc) -> Optional[DeckSpec]:
    """The on-screen deck = the document materialized (edits + page order applied)."""
    try:
        return D.materialize(doc)
    except Exception as exc:  # noqa: BLE001 — tolerate a stale persisted doc shape
        from logger import get_logger

        get_logger(__name__).warning("materialize failed: %s", exc)
        return None


# ── app ──────────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    assets_folder=_ASSETS,
    assets_ignore=r"^style\.css$|boardroom_dnd\.js|studio_deck\.js|typewriter\.js",
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="QBR Studio",
)

app.layout = html.Div(
    [
        dcc.Store(
            id="qs-view",
            data={
                "mode": "setup",
                "idx": 0,
                "tab": "setup",
                "lib_category": "all",
                "lib_tab": "all",
                "lib_view": "grid",
                "lib_search": "",
                "inspector_collapsed": False,
                "library_collapsed": False,
            },
        ),
        # The form selection (for Setup repopulate + regenerate) and the editable
        # document both persist locally so a refresh keeps your work.
        dcc.Store(id="qs-selection", data=None, storage_type="local"),
        dcc.Store(id="qs-doc", data=None, storage_type="local"),
        # The filled-template document — the actual deliverable in template mode.
        dcc.Store(id="qs-tdoc", data=None, storage_type="local"),
        dcc.Download(id="studio-pptx-download"),
        # Hidden sink: the canvas JS writes select/move/resize actions here.
        dcc.Input(id="qs-cv-sink", style={"display": "none"}),
        html.Div(id="qs-app"),
    ]
)


# ── master render: rebuild the shell from view + the shared document ──────────


@app.callback(
    Output("qs-app", "children"),
    Input("qs-view", "data"),
    Input("qs-doc", "data"),
    Input("qs-tdoc", "data"),
    State("qs-selection", "data"),
)
def _render(view, doc, tdoc, selection):
    deck = _deck(doc)
    opts = _friendly_options()
    fvals = (selection or {}).get("filters") or _DEFAULT_FILTERS
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


# ── mode switching ────────────────────────────────────────────────────────────


@app.callback(
    Output("qs-view", "data", allow_duplicate=True),
    Input({"type": "qs-mode", "mode": ALL}, "n_clicks"),
    State("qs-view", "data"),
    prevent_initial_call=True,
)
def _switch_mode(_clicks, view):
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
def _open_setup(n, view):
    if not n:
        return no_update
    view = dict(view or {})
    view["mode"] = "setup"
    return view


# ── slide navigation + inspector tab ─────────────────────────────────────────


@app.callback(
    Output("qs-view", "data", allow_duplicate=True),
    Input({"type": "qs-goto", "idx": ALL, "src": ALL}, "n_clicks"),
    State("qs-view", "data"),
    prevent_initial_call=True,
)
def _goto(_clicks, view):
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
def _insp_tab(_clicks, view):
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
def _zoom_canvas(_clicks, view):
    if not ctx.triggered_id or not any(_clicks or []):
        return no_update
    view = dict(view or {})
    view["zoom"] = A.adjusted_zoom(view.get("zoom"), ctx.triggered_id["op"])
    return view


@app.callback(
    Output("qs-view", "data", allow_duplicate=True),
    Input({"type": "qs-libcat", "category": ALL}, "n_clicks"),
    State("qs-view", "data"),
    prevent_initial_call=True,
)
def _component_category(_clicks, view):
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
def _component_tab(_clicks, view):
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
def _component_view(_clicks, view):
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
def _component_search(value, view):
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
def _toggle_library(_clicks, view):
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
def _toggle_canvas_panel(_clicks, view):
    if not ctx.triggered_id or not any(_clicks or []):
        return no_update
    panel = ctx.triggered_id["panel"]
    if panel not in {"inspector", "library"}:
        return no_update
    view = dict(view or {})
    key = f"{panel}_collapsed"
    view[key] = not bool(view.get(key, False))
    return view


# ── generate: snapshot the deterministic deck into a fresh document ──────────


@app.callback(
    Output("qs-selection", "data"),
    Output("qs-doc", "data", allow_duplicate=True),
    Output("qs-tdoc", "data", allow_duplicate=True),
    Output("qs-view", "data", allow_duplicate=True),
    Input("studio-generate", "n_clicks"),
    State("studio-report-type", "value"),
    State({"type": "studio-filter", "col": ALL}, "value"),
    State({"type": "studio-filter", "col": ALL}, "id"),
    State("studio-breakdown", "value"),
    State({"type": "studio-cut", "name": ALL}, "value"),
    State({"type": "studio-cut", "name": ALL}, "id"),
    State("studio-peer-mode", "value"),
    State("studio-peer-custom", "value"),
    State("studio-audience", "value"),
    State("studio-meeting-length", "value"),
    State("studio-ai-toggle", "value"),
    State("studio-template", "value"),
    prevent_initial_call=True,
)
def _generate(n, report, fvals, fids, breakdowns, cut_vals, cut_ids, peer_mode, custom_peers,
              audience, meeting_length, ai, template_path):
    if not n:
        return no_update, no_update, no_update, no_update
    filters = {i["col"]: v for i, v in zip(fids or [], fvals or []) if v not in _BLANK}
    cuts = [i["name"] for i, v in zip(cut_ids or [], cut_vals or []) if v]
    peers = None
    if "peer_average" in cuts and peer_mode == "custom":
        peers = [p for p in (custom_peers or []) if p]
    selection = {
        "report": report or "qbr",
        "filters": filters,
        "breakdowns": breakdowns or _BREAKDOWNS,
        "cuts": cuts,
        "peers": peers,
        "audience": audience or "executive",
        "meeting_length": meeting_length or "standard",
        "ai": bool(ai),
        "template_path": template_path or registry.active_template_path(),
    }
    deck = _generated_deck(selection)
    doc = D.new_document(deck) if deck else None
    tdoc = _generated_tdoc(selection)
    return selection, doc, tdoc, {"mode": "canvas", "idx": 0, "tab": "setup"}


# ── live scope preview: cheap headline figures as the filters change ─────────


@app.callback(
    Output("studio-scope-preview", "children"),
    Input({"type": "studio-filter", "col": ALL}, "value"),
    State({"type": "studio-filter", "col": ALL}, "id"),
)
def _scope_preview(values, ids):
    filters = {i["col"]: v for i, v in zip(ids or [], values or []) if v not in _BLANK}
    if not filters.get("carrier"):
        return A.scope_preview_empty()
    try:
        from core.analytics.library import compute_breakdown, compute_rank
        from core.analytics.types import PrimitiveArgs
        from studio.compute import _CARRIER_COL, _resolve_filters
        from studio.page.format import money

        resolved = _resolve_filters(filters)
        subject = resolved.get(_CARRIER_COL)
        total_facts = compute_breakdown(
            PrimitiveArgs(flow="gpr", metric="premium", group_by=(), filters=resolved), engine=engine
        )
        total = total_facts[0].value if total_facts else 0.0
        rank_filters = {k: v for k, v in resolved.items() if k != _CARRIER_COL}
        rank_facts = compute_rank(
            PrimitiveArgs(flow="gpr", metric="premium", group_by=(), filters=rank_filters), engine=engine
        )
        mine = next((f for f in rank_facts if str(f.dims.get("entity", "")).lower() == str(subject).lower()), None)
        country = filters.get("country")
        n_countries = len(country) if isinstance(country, (list, tuple)) else (1 if country else "All")
        items = [
            {"label": "Total GWP", "value": money(total), "sub": str(subject)},
            {"label": "Market rank", "value": (mine.rendered if mine else "—")},
            {"label": "Countries", "value": str(n_countries)},
            {"label": "Year", "value": str(filters.get("year") or "All")},
        ]
        return A.scope_preview_card(items)
    except Exception as exc:  # noqa: BLE001 — preview is best-effort, never blocks Setup
        from logger import get_logger

        get_logger(__name__).warning("scope preview failed: %s", exc)
        return A.scope_preview_empty("Preview unavailable for this scope.")


# ── editable fields (commit on blur so typing doesn't re-render mid-keystroke) ─


@app.callback(
    Output("qs-doc", "data", allow_duplicate=True),
    Input({"type": "qs-edit", "field": ALL, "idx": ALL}, "n_blur"),
    State({"type": "qs-edit", "field": ALL, "idx": ALL}, "value"),
    State({"type": "qs-edit", "field": ALL, "idx": ALL}, "id"),
    State("qs-doc", "data"),
    prevent_initial_call=True,
)
def _edit_field(_blurs, values, ids, doc):
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
def _reset_field(_clicks, doc):
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
def _set_chart(values, ids, doc):
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
def _page_op(_clicks, doc, view):
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
def _canvas_action(payload, doc, view):
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
def _add_widget(_clicks, doc, view):
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
def _widget_op(_clicks, doc, view):
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


# ── canvas: widget text props (commit on blur) + chart type ──────────────────


@app.callback(
    Output("qs-doc", "data", allow_duplicate=True),
    Input({"type": "qs-wprop", "wid": ALL, "prop": ALL}, "n_blur"),
    State({"type": "qs-wprop", "wid": ALL, "prop": ALL}, "value"),
    State({"type": "qs-wprop", "wid": ALL, "prop": ALL}, "id"),
    State("qs-doc", "data"),
    State("qs-view", "data"),
    prevent_initial_call=True,
)
def _widget_prop(_blurs, values, ids, doc, view):
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
def _widget_style(values, ids, doc, view):
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
def _text_style(values, ids, doc, view):
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


def _apply_color(doc, view, tid, value):
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
def _color_swatch(_clicks, doc, view):
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
def _custom_color(values, ids, doc, view):
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
def _widget_chart(values, ids, doc, view):
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


# ── export (real .pptx from the SAME materialized document) ──────────────────


def _assembled_export(selection: Dict[str, Any]) -> Optional[str]:
    """The real deliverable: overall + per-product + per-country, filled and merged.

    Rebuilds the ``OverallResult`` from the form selection (same as the preview) and runs
    the split-template assembly. Returns the output path, or ``None`` if it can't run.
    """
    filters = {k: v for k, v in ((selection or {}).get("filters") or {}).items() if v not in _BLANK}
    if not filters.get("carrier"):
        return None
    from studio.template_fill.assemble import assemble_deck

    result = compute_overall(
        filters=filters,
        breakdowns=selection.get("breakdowns") or _BREAKDOWNS,
        engine=engine,
        peers=selection.get("peers") or None,
    )
    subject = str(filters.get("carrier", "Carrier")).replace(" ", "_")
    out = Path(tempfile.gettempdir()) / f"{subject}_QBR.pptx"
    return assemble_deck(result, out_path=str(out))


@app.callback(
    Output("studio-pptx-download", "data"),
    Input({"type": "qs-export", "loc": ALL}, "n_clicks"),
    State("qs-selection", "data"),
    State("qs-tdoc", "data"),
    State("qs-doc", "data"),
    prevent_initial_call=True,
)
def _export(clicks, selection, tdoc, doc):
    if not any(clicks or []):
        return no_update
    # The deliverable is the ASSEMBLED deck: overall + one block per product + one per
    # country the carrier writes in (or the user's selection), filled and merged.
    try:
        assembled = _assembled_export(selection)
    except Exception as exc:  # noqa: BLE001 — fall back rather than white-screen the export
        from logger import get_logger

        get_logger(__name__).warning("assembled export failed, falling back: %s", exc)
        assembled = None
    if assembled:
        return dcc.send_file(assembled)
    # Fallback: the single filled template (pre-split behaviour) if assembly can't run.
    if tdoc and tdoc.get("template_path"):
        subject = str((tdoc.get("values") or {}).get("subject_name", "Carrier")).replace(" ", "_")
        out = Path(tempfile.gettempdir()) / f"{subject}_QBR.pptx"
        fill_template(dict(tdoc), out_path=str(out))
        return dcc.send_file(str(out))
    if not doc or not doc.get("order"):
        return no_update
    meta = dict(doc.get("meta") or {})
    carrier = str(meta.get("carrier", "Carrier")).replace(" ", "_")
    country = str(meta.get("country", "Market")).replace(" ", "_")
    suffix = "Executive_Summary" if meta.get("report") == "exec" else "QBR"
    out = Path(tempfile.gettempdir()) / f"{carrier}_{country}_{suffix}.pptx"
    # Pages composed on the canvas export by widget geometry; the rest stay polished.
    export_document(doc, out_path=str(out))
    return dcc.send_file(str(out))


# ── template editing: slot overrides, added notes, validation re-run ─────────


@app.callback(
    Output("qs-tdoc", "data", allow_duplicate=True),
    Input({"type": "qs-tf-edit", "key": ALL}, "value"),
    State({"type": "qs-tf-edit", "key": ALL}, "id"),
    State("qs-tdoc", "data"),
    prevent_initial_call=True,
)
def _edit_slot(values, ids, tdoc):
    if not tdoc or not ids:
        return no_update
    from studio.template_fill.model import materialize_fields

    fields = materialize_fields(dict(tdoc))
    overrides = dict(tdoc.get("overrides", {}))
    changed = False
    for val, ident in zip(values or [], ids or []):
        key = ident["key"]
        if val is None:
            continue
        # Only persist a genuine edit — a value that differs from what the slot
        # already renders. This stops untouched placeholder tokens from being
        # written back as spurious overrides (the false "stale" issues).
        current = str(fields.get(key, {}).get("text", ""))
        if str(val) == current:
            continue
        if overrides.get(key) != val:
            overrides[key] = val
            changed = True
    if not changed:
        return no_update
    return {**tdoc, "overrides": overrides}


@app.callback(
    Output("qs-tdoc", "data", allow_duplicate=True),
    Input({"type": "qs-tf-add", "slide": ALL}, "n_clicks"),
    State("qs-tdoc", "data"),
    prevent_initial_call=True,
)
def _add_note(clicks, tdoc):
    if not tdoc or not ctx.triggered_id or not any(clicks or []):
        return no_update
    slide_idx = int(ctx.triggered_id["slide"])
    w = int(tdoc.get("width_emu", 12192000))
    h = int(tdoc.get("height_emu", 6858000))
    el = {"x": w // 12, "y": h // 12, "w": w // 3, "h": h // 10, "text": "New note", "size": 12}
    return add_element(dict(tdoc), slide_idx, el)


@app.callback(
    Output("qs-tdoc", "data", allow_duplicate=True),
    Input({"type": "qs-tf-autofix"}, "n_clicks"),
    State("qs-tdoc", "data"),
    prevent_initial_call=True,
)
def _autofix(n, tdoc):
    if not n or not tdoc:
        return no_update
    return TV.auto_fix(dict(tdoc))


# Template upload was removed: templates are now a fixed, author-made set (assembled
# per product/country and merged), not user-uploaded. See studio/template_fill/assemble.py.


@app.callback(
    Output("studio-template-sections", "children"),
    Input("studio-template", "value"),
    prevent_initial_call=True,
)
def _template_sections(path):
    """Refresh the 'Deck sections' list when the fixed template selection changes."""
    if not path:
        return no_update
    return A.template_sections_panel(path)


@app.callback(
    Output("qs-view", "data", allow_duplicate=True),
    Input({"type": "qs-tf-revalidate"}, "n_clicks"),
    State("qs-view", "data"),
    prevent_initial_call=True,
)
def _revalidate(n, view):
    # Validation is computed live on every render; bumping a nonce forces a re-run.
    if not n:
        return no_update
    view = dict(view or {})
    view["revalidate"] = int(view.get("revalidate", 0)) + 1
    return view


if __name__ == "__main__":
    import os

    app.run(debug=True, port=int(os.environ.get("PORT", "8131")))
