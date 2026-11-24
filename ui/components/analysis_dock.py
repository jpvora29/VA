"""The evidence panel: one answer's charts and tables, kept on screen.

A chart inside the answer that produced it scrolls away the moment the reader
asks the obvious next question. On a wide screen the panel is the fix: it shows
one answer's evidence beside the conversation and does not move when the
transcript does.

Evidence is shown in exactly one place at any width (the reason the first dock
was removed — it repeated the card):

    >= 1280px, panel open   the panel shows it; each card shows a small chip
                            that brings that answer's evidence into the panel
    narrower, or collapsed  the card shows it; the panel is not drawn

That split is pure CSS (``assets/va_shell_chat_v3.css``), so a resize or a
rotation never needs a round trip.

Which answer the panel shows:

    the newest answer that produced evidence   <- by default
    whichever answer's chip the reader clicked <- until the next answer arrives,
                                                  or "Back to latest"

The panel re-renders the SAME components the card does, :func:`evidence_panel`
and :func:`contribution_panel`, under a separate id namespace (:data:`DOCK_NS`),
so the Chart/Table switches and the view tabs work in both places.

Pure presentation. :mod:`ui.analysis` decides the target and fills the body.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from dash import html

from ui.components.contribution import contribution_panel
from ui.components.evidence import evidence_panel
from ui.components.scope_bar import scope_bar

#: Prefix for every id the panel mints. The transcript keys its Chart/Table
#: switch and view tabs on plain integers, so a prefixed string can never collide
#: with one, which is what lets the same evidence render twice on one page.
DOCK_NS = "dock"


@dataclass(frozen=True)
class DockTarget:
    """The one answer the panel is showing."""

    idx: int
    question: str = ""
    scope: list[dict] = field(default_factory=list)
    views: list[Any] = field(default_factory=list)
    contribution: dict | None = None
    pinned: bool = False

    @property
    def has_analysis(self) -> bool:
        return bool(self.views) or bool(self.contribution)


def dock_pane_ids(idx: Any, count: int) -> list[str]:
    """Ids for a target's per-view Chart/Table switches, in the panel's namespace."""
    return [f"{DOCK_NS}-{idx}-{i}" for i in range(count)]


def _empty_body() -> html.Div:
    """What the panel says before there is anything to keep in view."""
    return html.Div(
        [
            html.I(className="bi bi-graph-up-arrow dock-empty-icon"),
            html.Div("No evidence yet", className="dock-empty-title"),
            html.Div(
                "Ask a question that returns data and its chart stays here while "
                "you follow up.",
                className="dock-empty-note",
            ),
        ],
        className="dock-empty",
    )


def _pin_state(target: DockTarget) -> Any:
    """Whether the panel is following the conversation or held on one answer."""
    if target.pinned:
        return html.Button(
            [html.I(className="bi bi-arrow-down-circle"), html.Span("Back to latest")],
            id="analysis-unpin",
            n_clicks=0,
            className="dock-pin is-pinned",
            title="Show the newest answer's evidence again",
        )
    return html.Span(
        [html.I(className="bi bi-arrow-down-circle"), html.Span("Latest")],
        className="dock-pin",
        title="Showing the newest answer that produced evidence",
    )


def dock_body(target: DockTarget | None) -> Any:
    """The panel's contents for one target, or the empty state."""
    if target is None or not target.has_analysis:
        return _empty_body()

    views = list(target.views)
    panel = (
        evidence_panel(
            views,
            f"{DOCK_NS}-{target.idx}",
            dock_pane_ids(target.idx, len(views)),
        )
        if views
        else None
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        target.question or "This answer", className="dock-question"
                    ),
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


def analysis_dock() -> html.Aside:
    """The mounted panel. Its body is filled by ``ui.analysis.render_analysis_dock``."""
    return html.Aside(
        [
            html.Div(
                [
                    html.I(className="bi bi-bar-chart-line dock-title-icon"),
                    html.Span("Evidence", className="dock-title"),
                    html.Button(
                        html.I(className="bi bi-chevron-double-right"),
                        id="analysis-collapse",
                        n_clicks=0,
                        className="dock-collapse",
                        title="Hide the evidence panel",
                    ),
                ],
                className="dock-head",
            ),
            html.Div(id="analysis-dock-body", className="dock-body"),
        ],
        id="analysis-dock",
        className="analysis-dock is-empty",
    )


def dock_reopen_button() -> html.Button:
    """The way back to a hidden panel, parked at the edge of the conversation."""
    return html.Button(
        [
            html.I(className="bi bi-bar-chart-line"),
            html.Span("Evidence", className="dock-reopen-label"),
        ],
        id="analysis-reopen",
        n_clicks=0,
        className="dock-reopen",
        title="Show the evidence panel",
    )


def evidence_chip(idx: int, views: Sequence[Any], has_drivers: bool) -> html.Button:
    """The card's pointer to its evidence while that evidence is in the panel.

    Drawn on every answer that has evidence and shown by CSS only when the panel
    is: it says what the evidence is and brings it into the panel on a click.
    """
    charts = sum(1 for v in views if getattr(v, "has_chart", False))
    tables = len(views) - charts
    parts = [
        _count(charts, "chart"),
        _count(tables, "table"),
        "drivers" if has_drivers else "",
    ]
    summary = " · ".join(p for p in parts if p) or "Evidence"
    return html.Button(
        [
            html.I(className="bi bi-layout-sidebar-inset-reverse"),
            html.Span(summary, className="answer-evidence-chip-text"),
            html.Span("Show in panel", className="answer-evidence-chip-go"),
        ],
        id={"type": "evidence-focus", "idx": idx},
        n_clicks=0,
        className="answer-evidence-chip",
        title="Show this answer's evidence in the panel",
    )


def _count(n: int, noun: str) -> str:
    """ "2 charts" / "1 table" / ""."""
    if n <= 0:
        return ""
    return f"{n} {noun}" + ("" if n == 1 else "s")


def workspace_class(*, dock_open: bool) -> str:
    """The one class that says whether the panel is open."""
    return "chat-workspace" + ("" if dock_open else " dock-hidden")
