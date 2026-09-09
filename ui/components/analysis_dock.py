"""The analysis panel: the evidence stays on screen while the conversation moves on.

A chart lives inside the answer that produced it, which is right until the reader
asks the obvious next question — at which point the chart they were reading
scrolls away and they are typing about something they can no longer see. The dock
is the fix: one panel, always showing an answer's evidence, that does not move
when the transcript does.

Which answer it shows:

    the newest answer that produced evidence   <- by default, so it follows along
    whichever answer the reader pinned         <- until they unpin it

Pinning is per-answer and explicit (the pin in an answer's footer), so the panel
never silently changes what it is showing while the reader is using it.

The panel re-renders the SAME components the card does — :func:`evidence_panel`
and :func:`contribution_panel` — under a separate id namespace (see
:data:`DOCK_NS`), so the Chart/Data switches and the view tabs work in both places
without either knowing the other exists.

Pure presentation. :mod:`ui.callbacks` decides the target and fills the body.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from dash import html

from ui.components.contribution import contribution_panel
from ui.components.evidence import evidence_panel
from ui.components.scope_bar import scope_bar

#: Prefix for every id the dock mints. The transcript keys its Chart/Data switch
#: and view tabs on plain integers, so a prefixed string can never collide with
#: one — which is what lets the same evidence render twice on one page.
DOCK_NS = "dock"


@dataclass(frozen=True)
class DockTarget:
    """The one answer the panel is showing."""

    idx: int
    question: str = ""
    scope: List[dict] = field(default_factory=list)
    views: List[Any] = field(default_factory=list)
    contribution: Optional[dict] = None
    pinned: bool = False

    @property
    def has_analysis(self) -> bool:
        return bool(self.views) or bool(self.contribution)


def dock_pane_ids(idx: Any, count: int) -> List[str]:
    """Ids for a target's per-view Chart/Data switches, in the dock's namespace."""
    return [f"{DOCK_NS}-{idx}-{i}" for i in range(count)]


def _empty_body():
    """What the panel says before there is anything to keep in view."""
    return html.Div(
        [
            html.I(className="bi bi-graph-up-arrow dock-empty-icon"),
            html.Div("No analysis yet", className="dock-empty-title"),
            html.Div(
                "Ask a question that returns data and its chart stays here while "
                "you follow up.",
                className="dock-empty-note",
            ),
        ],
        className="dock-empty",
    )


def _pin_state(target: DockTarget):
    """Whether the panel is following the conversation or held on one answer."""
    if target.pinned:
        return html.Button(
            [html.I(className="bi bi-pin-angle-fill"), html.Span("Pinned")],
            id="analysis-unpin",
            n_clicks=0,
            className="dock-pin is-pinned",
            title="Unpin — follow the newest analysis again",
        )
    return html.Span(
        [html.I(className="bi bi-arrow-down-circle"), html.Span("Latest")],
        className="dock-pin",
        title="Showing the newest answer that produced evidence",
    )


def dock_body(target: Optional[DockTarget]) -> Any:
    """The panel's contents for one target, or the empty state."""
    if target is None or not target.has_analysis:
        return _empty_body()

    views = list(target.views)
    panel = (
        evidence_panel(views, f"{DOCK_NS}-{target.idx}", dock_pane_ids(target.idx, len(views)))
        if views
        else None
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(target.question or "This analysis", className="dock-question"),
                    _pin_state(target),
                ],
                className="dock-target-head",
            ),
            scope_bar(target.scope, compact=True),
            panel,
            contribution_panel(target.contribution),
        ],
        className="dock-target",
    )


def analysis_dock() -> html.Div:
    """The mounted panel. Its body is filled by ``ui.callbacks.render_analysis_dock``."""
    return html.Aside(
        [
            html.Div(
                [
                    html.I(className="bi bi-columns-gap dock-title-icon"),
                    html.Span("Analysis", className="dock-title"),
                    html.Button(
                        html.I(className="bi bi-chevron-double-right"),
                        id="analysis-collapse",
                        n_clicks=0,
                        className="dock-collapse",
                        title="Hide the analysis panel",
                    ),
                ],
                className="dock-head",
            ),
            html.Div(id="analysis-dock-body", className="dock-body"),
        ],
        id="analysis-dock",
        className="analysis-dock",
    )


def dock_reopen_button() -> html.Button:
    """The way back to a hidden panel, parked at the edge of the conversation."""
    return html.Button(
        [html.I(className="bi bi-columns-gap"), html.Span("Analysis", className="dock-reopen-label")],
        id="analysis-reopen",
        n_clicks=0,
        className="dock-reopen",
        title="Show the analysis panel",
    )


def view_switch() -> html.Div:
    """Conversation / Analysis, for screens too narrow to show both at once.

    Both columns stay mounted and one is hidden, so switching keeps every chart,
    every open drawer and the half-typed question exactly as they were.
    """
    return html.Div(
        [
            html.Button(
                [html.I(className="bi bi-chat-left-text"), html.Span("Conversation")],
                id={"type": "chat-view-btn", "view": "chat"},
                n_clicks=0,
                className="chat-view-tab active",
            ),
            html.Button(
                [html.I(className="bi bi-columns-gap"), html.Span("Analysis")],
                id={"type": "chat-view-btn", "view": "analysis"},
                n_clicks=0,
                className="chat-view-tab",
            ),
        ],
        id="chat-view-switch",
        className="chat-view-switch-band",
    )


def workspace_class(*, dock_open: bool, mode: str) -> str:
    """The one class that says how the two columns are arranged right now."""
    classes = ["chat-workspace"]
    if not dock_open:
        classes.append("dock-hidden")
    classes.append("show-analysis" if mode == "analysis" else "show-chat")
    return " ".join(classes)


def view_tab_classes(mode: str, views: Sequence[Any]) -> List[str]:
    """Active state for the narrow-screen switch, in the order Dash gives them."""
    return [
        "chat-view-tab" + (" active" if (v or {}).get("view") == mode else "")
        for v in views
    ]
