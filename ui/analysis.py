"""The analysis panel's wiring: what it shows, and how the two columns arrange.

Three decisions, each triggered by something different, so each gets its own
callback:

* **which answer** the panel is holding — the newest one that produced evidence,
  or whichever the reader pinned;
* **whether the panel is open** — it can be collapsed out of the way and brought
  back from the tab parked at the edge of the conversation;
* **which column is on screen** below the split breakpoint, where the two do not
  fit side by side and become two views of one workspace.

The last two are one *store* and one *class*, so they are decided together
(``set_analysis_view``) and painted together (``paint_analysis_view``) — which is
what keeps "collapsed" and "showing the analysis" from ever contradicting each
other on screen.

The panel's *contents* are built by :mod:`ui.components.analysis_dock`; nothing
here knows what a chart looks like.

Registered on import, like the boardroom and decision packages.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from dash import ALL, Input, Output, State, callback, ctx, no_update

from ui.components.analysis_dock import (
    DockTarget,
    dock_body,
    view_tab_classes,
    workspace_class,
)
from ui.evidence import build_views


def _clicked() -> bool:
    """True only for a real click, not a component arriving with ``n_clicks=0``."""
    return bool(ctx.triggered and ctx.triggered[0].get("value"))


def _evidence_specs(messages: List[Dict[str, Any]], idx: int) -> List[Dict[str, Any]]:
    """The evidence an answer owns: everything up to the next turn.

    The same rule the transcript card uses (``ui.callbacks._evidence_after``),
    restated rather than imported to keep this module free of a cycle — the two
    are checked against each other by ``tests/test_chat_prism_surface.py``.
    """
    specs: List[Dict[str, Any]] = []
    for message in messages[idx + 1:]:
        kind = message.get("type")
        if kind in ("HumanMessage", "AIMessage", "Boardroom", "ClarifyCard"):
            break
        if kind in ("Evidence", "SQLOutputForCharts"):
            specs.extend(
                message.get("views")
                or [{"rows": message.get("updated_query"),
                     "chart_data": message.get("chart_data")}]
            )
    return specs


def _target_at(messages: List[Dict[str, Any]], idx: int, *, pinned: bool) -> Optional[DockTarget]:
    """Build the panel's target from one answer, or ``None`` if it has no evidence."""
    if not 0 <= idx < len(messages):
        return None
    message = messages[idx]
    if message.get("type") != "AIMessage":
        return None
    target = DockTarget(
        idx=idx,
        question=message.get("question") or "",
        scope=[c for c in (message.get("scope") or []) if c.get("key") != "peers"],
        views=build_views(_evidence_specs(messages, idx)),
        contribution=message.get("contribution"),
        pinned=pinned,
    )
    return target if target.has_analysis else None


def dock_target(chat_history: Dict[str, Any] | None, pin: Any) -> Optional[DockTarget]:
    """The answer the panel should be showing.

    A pin wins while it still points at an answer with evidence; a pin left on a
    conversation that has since been replaced falls back to the newest rather
    than emptying the panel.
    """
    messages = (chat_history or {}).get("messages") or []
    if pin is not None:
        pinned = _target_at(messages, int(pin), pinned=True)
        if pinned is not None:
            return pinned
    for idx in range(len(messages) - 1, -1, -1):
        target = _target_at(messages, idx, pinned=False)
        if target is not None:
            return target
    return None


@callback(
    Output("analysis-dock-body", "children"),
    Output("analysis-dock", "className"),
    Input("chat-store", "data"),
    Input("analysis-pin", "data"),
)
def render_analysis_dock(chat_history: Dict[str, Any] | None, pin: Any):
    """Fill the panel with the target's evidence, or fold it away.

    An empty panel is not a smaller panel: before the first chart there is
    nothing to keep in view, and holding 460px open to say so takes the width
    from the one thing on that screen worth reading. So the panel has no width
    until there is evidence, and appears with the first answer that produces
    some. Its empty state still exists for the narrow layout, where the reader
    can switch to it deliberately and deserves an explanation rather than a
    blank column.
    """
    target = dock_target(chat_history, pin)
    return dock_body(target), "analysis-dock" + ("" if target else " is-empty")


@callback(
    Output("analysis-pin", "data"),
    Input({"type": "answer-pin", "idx": ALL}, "n_clicks"),
    Input("analysis-unpin", "n_clicks", allow_optional=True),
    State("analysis-pin", "data"),
    prevent_initial_call=True,
)
def set_analysis_pin(_pins: List[Any], _unpin: Any, current: Any) -> Any:
    """Hold the panel on one answer, or release it back to following the newest.

    Pressing the pin on the answer already pinned unpins it, so the control is
    its own undo.
    """
    if not _clicked():
        return no_update
    triggered = ctx.triggered_id
    if triggered == "analysis-unpin":
        return None
    if isinstance(triggered, dict) and triggered.get("type") == "answer-pin":
        idx = triggered.get("idx")
        return None if current == idx else idx
    return no_update


@callback(
    Output("analysis-view", "data"),
    Input("analysis-collapse", "n_clicks"),
    Input("analysis-reopen", "n_clicks"),
    Input({"type": "chat-view-btn", "view": ALL}, "n_clicks"),
    State("analysis-view", "data"),
    prevent_initial_call=True,
)
def set_analysis_view(_collapse: Any, _reopen: Any, _tabs: List[Any], view: Any) -> Any:
    """One store holds both arrangement facts, because one class expresses them."""
    if not _clicked():
        return no_update
    state = dict(view or {"open": True, "mode": "chat"})
    triggered = ctx.triggered_id
    if triggered == "analysis-collapse":
        state["open"] = False
    elif triggered == "analysis-reopen":
        state["open"] = True
    elif isinstance(triggered, dict) and triggered.get("type") == "chat-view-btn":
        state["mode"] = triggered.get("view") or "chat"
        # Switching to the analysis view on a narrow screen has to un-collapse
        # the panel, or the tab leads to a blank column.
        if state["mode"] == "analysis":
            state["open"] = True
    return state


@callback(
    Output("chat-workspace", "className"),
    Output({"type": "chat-view-btn", "view": ALL}, "className"),
    Input("analysis-view", "data"),
    State({"type": "chat-view-btn", "view": ALL}, "id"),
)
def paint_analysis_view(view: Any, tab_ids: List[Any]):
    """The arrangement, expressed as one class on the workspace plus the tab states."""
    state = view or {}
    mode = str(state.get("mode") or "chat")
    return (
        workspace_class(dock_open=bool(state.get("open", True)), mode=mode),
        view_tab_classes(mode, tab_ids),
    )
