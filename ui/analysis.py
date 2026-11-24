"""The evidence panel's wiring: which answer it shows, and whether it is open.

Two decisions, each triggered by something different, so each has its own
callback:

* **which answer** the panel holds: the newest one that produced evidence, or
  the one whose chip the reader clicked, until the next answer arrives;
* **whether the panel is open**: it collapses out of the way and comes back from
  the tab parked at the edge of the conversation.

Where evidence is drawn at each width (panel or card) is CSS, not a callback;
see :mod:`ui.components.analysis_dock`.

Registered on import by :mod:`ui.callbacks`.
"""

from __future__ import annotations

from typing import Any

from dash import ALL, Input, Output, State, callback, ctx, no_update

from ui.components.analysis_dock import DockTarget, dock_body, workspace_class
from ui.evidence import build_views


def _clicked() -> bool:
    """True only for a real click, not a component arriving with ``n_clicks=0``."""
    return bool(ctx.triggered and ctx.triggered[0].get("value"))


def _evidence_specs(messages: list[dict[str, Any]], idx: int) -> list[dict[str, Any]]:
    """The evidence an answer owns: everything up to the next turn.

    The same rule the transcript card uses (``ui.callbacks._evidence_after``),
    restated rather than imported to keep this module free of a cycle; the two
    are checked against each other by ``tests/test_chat_prism_surface.py``.
    """
    specs: list[dict[str, Any]] = []
    for message in messages[idx + 1 :]:
        kind = message.get("type")
        if kind in ("HumanMessage", "AIMessage", "Boardroom", "ClarifyCard"):
            break
        if kind in ("Evidence", "SQLOutputForCharts"):
            specs.extend(
                message.get("views")
                or [
                    {
                        "rows": message.get("updated_query"),
                        "chart_data": message.get("chart_data"),
                    }
                ]
            )
    return specs


def _target_at(
    messages: list[dict[str, Any]], idx: int, *, pinned: bool
) -> DockTarget | None:
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


def dock_target(chat_history: dict[str, Any] | None, pin: Any) -> DockTarget | None:
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


def answer_count(chat_history: dict[str, Any] | None) -> int:
    """How many answers the conversation holds; a new one releases a pin."""
    messages = (chat_history or {}).get("messages") or []
    return sum(1 for m in messages if m.get("type") == "AIMessage")


def live_pin(focus: Any, chat_history: dict[str, Any] | None) -> int | None:
    """The pinned answer, or ``None`` once a newer answer has arrived.

    ``focus`` is ``{"idx": answer index, "answers": answer count at the click}``.
    Asking the next question is the reader moving on, so the panel follows the
    new answer rather than holding the old one.
    """
    if not isinstance(focus, dict) or focus.get("idx") is None:
        return None
    if focus.get("answers") != answer_count(chat_history):
        return None
    return int(focus["idx"])


@callback(
    Output("analysis-dock-body", "children"),
    Output("analysis-dock", "className"),
    Input("chat-store", "data"),
    Input("analysis-pin", "data"),
)
def render_analysis_dock(chat_history: dict[str, Any] | None, focus: Any):
    """Fill the panel with the target's evidence, or fold it away.

    The panel has no width until there is evidence: holding 460px open to say
    "nothing yet" takes the width from the one thing worth reading.
    """
    target = dock_target(chat_history, live_pin(focus, chat_history))
    return dock_body(target), "analysis-dock" + ("" if target else " is-empty")


@callback(
    Output("analysis-pin", "data"),
    Input({"type": "evidence-focus", "idx": ALL}, "n_clicks"),
    Input("analysis-unpin", "n_clicks", allow_optional=True),
    State("chat-store", "data"),
    prevent_initial_call=True,
)
def set_analysis_pin(_chips: list[Any], _unpin: Any, chat_history: Any) -> Any:
    """Hold the panel on one answer, or release it back to the newest."""
    if not _clicked():
        return no_update
    triggered = ctx.triggered_id
    if triggered == "analysis-unpin":
        return None
    if isinstance(triggered, dict) and triggered.get("type") == "evidence-focus":
        return {"idx": triggered.get("idx"), "answers": answer_count(chat_history)}
    return no_update


@callback(
    Output("chat-workspace", "className"),
    Input("analysis-collapse", "n_clicks"),
    Input("analysis-reopen", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_analysis_dock(_collapse: Any, _reopen: Any) -> Any:
    """Collapse the panel, or bring it back. The card shows evidence meanwhile."""
    if not _clicked():
        return no_update
    return workspace_class(dock_open=ctx.triggered_id != "analysis-collapse")
