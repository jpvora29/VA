"""The left rail every workspace shares, and the one collapse state they share.

There is one rail *frame* — a titled head with a collapse toggle, a scrolling body,
an optional footer — and each workspace fills it with its own sections. That is what
stops the left edge of the app from changing identity when you switch tabs.

**Collapsing is app-wide, not per-tab.** The state is one class on the pane container
(``rails_class``), not a class written onto each rail, for two reasons: Studio rebuilds
its own rail from its own callback, so a class set on that rail would be wiped by the
next view change; and a rail that changed width when you switched tabs would undo the
point of sharing the frame. Collapsed is the default — the app opens with an icon column.

Pure layout: no callbacks, no state. ``ui.shell.collapse`` owns the wiring.
"""
from __future__ import annotations

from typing import Any, Sequence

from dash import html

# The shared class every rail carries.
RAIL_CLASS = "va-rail"

# Set on the pane container while the rails are collapsed. Every collapsed rule in
# assets/style.css and assets/va_shell.css hangs off this one class.
RAILS_COLLAPSED_CLASS = "va-rails-collapsed"


def rails_class(collapsed: bool) -> str:
    """The className for the pane container that holds every rail."""
    return f"va-body {RAILS_COLLAPSED_CLASS}" if collapsed else "va-body"


def rail_section(label: str | None, children: Sequence[Any]) -> html.Div:
    """A labelled group inside the rail body."""
    head = [html.Div(label, className="va-rail-label")] if label else []
    return html.Div([*head, html.Div(list(children), className="va-rail-group")],
                    className="va-rail-section")


def _collapse_toggle(rail_id: str) -> html.Button:
    """Every rail gets the same toggle, and they all write the one shared state.

    The id is per-rail only because all four rails are mounted at once and Dash needs
    distinct ids; the callback matches them with ``ALL``.
    """
    return html.Button(
        html.I(className="bi bi-layout-sidebar"),
        id={"type": "va-rail-toggle", "rail": rail_id},
        n_clicks=0,
        className="va-rail-toggle",
        title="Expand or collapse the sidebar",
    )


def rail_frame(
    title: str,
    body: Sequence[Any],
    *,
    rail_id: str,
    footer: Any | None = None,
    className: str = "",
    id: str | None = None,
) -> html.Aside:
    """Head + scrolling body + optional footer, in the shared rail chrome.

    ``rail_id`` identifies this rail's collapse toggle. ``className`` is what the
    caller adds ON TOP of ``RAIL_CLASS`` — never the whole attribute.
    """
    blocks: list[Any] = [
        html.Div(
            [html.Span(title, className="va-rail-title"), _collapse_toggle(rail_id)],
            className="va-rail-head",
        ),
        html.Div(list(body), className="va-rail-body"),
    ]
    if footer is not None:
        blocks.append(html.Div(footer, className="va-rail-foot"))
    kwargs: dict[str, Any] = {}
    if id is not None:
        kwargs["id"] = id
    return html.Aside(blocks, className=f"{RAIL_CLASS} {className}".strip(), **kwargs)
