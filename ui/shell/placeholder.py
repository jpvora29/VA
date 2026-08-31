"""The workspace shape a not-yet-built tab wears.

Recap and MoM have no engine behind them yet. They still get the full shell — the
same rail width, the same content frame — so switching to them changes the *content*
and nothing about the furniture. When the real feature lands it replaces
``placeholder_body`` and inherits the frame unchanged.
"""
from __future__ import annotations

from typing import Sequence

from dash import html

from ui.shell.rail import rail_frame, rail_section


def placeholder_rail(title: str, steps: Sequence[str]) -> html.Aside:
    """A rail that names the workspace and previews the steps it will have."""
    items = [
        html.Div(
            [
                html.Span(str(i), className="va-rail-step-num"),
                html.Span(step, className="va-rail-step-label"),
            ],
            className="va-rail-step",
        )
        for i, step in enumerate(steps, 1)
    ]
    return rail_frame(
        title,
        [rail_section("Planned steps", items)],
        className="va-rail-placeholder",
    )


def placeholder_body(
    *, icon: str, title: str, blurb: str, bullets: Sequence[str]
) -> html.Div:
    """The empty state: what this workspace will do, and what it will produce."""
    return html.Div(
        html.Div(
            [
                html.Div(html.I(className=f"bi {icon}"), className="va-empty-icon"),
                html.Div("Coming soon", className="va-empty-eyebrow"),
                html.H1(title, className="va-empty-title"),
                html.P(blurb, className="va-empty-blurb"),
                html.Ul(
                    [html.Li(b) for b in bullets],
                    className="va-empty-list",
                ),
            ],
            className="va-empty-card",
        ),
        className="va-empty-host",
    )
