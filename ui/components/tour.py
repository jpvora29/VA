"""The tour dialog — one step on screen at a time, with its illustration.

Every step is rendered once and shown or hidden by a clientside callback, so
moving through the tour costs no server round trip and no re-render. The
illustration for each step is drawn from the app's own tokens (see
:mod:`ui.shell.tour`), so it cannot go stale the way a screenshot does.
"""
from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import html

from ui.shell.tour import STEPS


def _step_panel(index: int, step: Any):
    return html.Div(
        [
            step.art(),
            html.Div(
                [
                    html.Div(f"Step {index + 1} of {len(STEPS)}", className="tour-step-count"),
                    html.H3(step.title, className="tour-step-title"),
                    html.P(step.body, className="tour-step-body"),
                ],
                className="tour-copy",
            ),
        ],
        id={"type": "tour-step", "index": index},
        className="tour-step",
        style={} if index == 0 else {"display": "none"},
    )


def tour_dialog():
    """The whole dialog, mounted once in the app shell."""
    return dbc.Modal(
        [
            dbc.ModalBody(
                [
                    html.Button(
                        html.I(className="bi bi-x-lg"),
                        id="tour-close",
                        n_clicks=0,
                        className="tour-close",
                        title="Close",
                    ),
                    html.Div(
                        [_step_panel(i, step) for i, step in enumerate(STEPS)],
                        className="tour-stage",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Button(
                                        className="tour-dot" + (" active" if i == 0 else ""),
                                        id={"type": "tour-dot", "index": i},
                                        n_clicks=0,
                                        title=step.title,
                                    )
                                    for i, step in enumerate(STEPS)
                                ],
                                className="tour-dots",
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Back",
                                        id="tour-back",
                                        n_clicks=0,
                                        className="tour-btn ghost",
                                        disabled=True,
                                    ),
                                    html.Button(
                                        "Next",
                                        id="tour-next",
                                        n_clicks=0,
                                        className="tour-btn primary",
                                    ),
                                ],
                                className="tour-nav",
                            ),
                        ],
                        className="tour-footer",
                    ),
                ],
                className="tour-body",
            )
        ],
        id="tour-modal",
        is_open=False,
        centered=True,
        size="lg",
        backdrop=True,
        className="tour-modal",
    )


def tour_button():
    """The navbar entry point."""
    return html.Button(
        [html.I(className="bi bi-compass"), html.Span("Take a tour", className="va-tour-label")],
        id="tour-open",
        n_clicks=0,
        className="va-tour-btn",
        title="A quick guided tour of what this app can do",
    )
