"""The tour dialog — a chapter rail, one step on stage, and a way to try it.

Every step is rendered once and shown or hidden by a clientside callback, so
moving through the tour costs no server round trip and no re-render. The
illustration for each step is drawn from the app's own tokens (see
:mod:`ui.shell.tour`), so it cannot go stale the way a screenshot does.

The rail down the left is the part that turns a slideshow into a guide: it shows
the whole shape of the product on the first screen, before the reader has seen
any of it, and lets someone who only came for Boardroom Mode jump there. The
progress bar under the stage answers "how much of this is left?", which a row of
twelve identical dots does not.

`try_it` is the other half. A step carrying a question renders a button that
drops that question into the composer and closes the tour, so a new user's first
act is asking something real rather than reading about asking something.
"""
from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import html

from ui.shell.tour import STEPS, Chapter, TourStep, chapters


def _rail_entry(chapter: Chapter, active: bool):
    """One chapter in the rail, which is also the way to jump to it."""
    return html.Button(
        [
            html.Span(className="tour-rail-mark"),
            html.Span(
                [
                    html.Span(chapter.name, className="tour-rail-name"),
                    html.Span(
                        f"{chapter.size} step{'s' if chapter.size != 1 else ''}",
                        className="tour-rail-count",
                    ),
                ],
                className="tour-rail-copy",
            ),
        ],
        id={"type": "tour-chapter", "index": chapter.start},
        n_clicks=0,
        className="tour-rail-item" + (" active" if active else ""),
        title=f"Jump to {chapter.name}",
    )


def _rail():
    """The map of the product, shown before any of it."""
    marks = chapters()
    return html.Div(
        [
            html.Div("The tour", className="tour-rail-title"),
            html.Div([_rail_entry(c, i == 0) for i, c in enumerate(marks)],
                     className="tour-rail-list"),
        ],
        className="tour-rail",
    )


def _points(step: TourStep):
    """What to actually do — the half that makes it a guide, not a brochure."""
    if not step.points:
        return None
    return html.Ol(
        [html.Li(point, className="tour-point") for point in step.points],
        className="tour-points",
    )


def _try_it(index: int, step: TourStep):
    """A real question, one click away, that also closes the tour."""
    if not step.try_it:
        return None
    return html.Button(
        [
            html.I(className="bi bi-play-circle-fill"),
            html.Span("Try it:", className="tour-try-label"),
            html.Span(f"“{step.try_it}”", className="tour-try-question"),
        ],
        id={"type": "tour-try", "index": index},
        n_clicks=0,
        className="tour-try",
        title=step.try_it,
    )


def _step_panel(index: int, step: Any):
    return html.Div(
        [
            step.art(),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(step.chapter, className="tour-step-chapter"),
                            html.Span(
                                f"Step {index + 1} of {len(STEPS)}",
                                className="tour-step-count",
                            ),
                        ],
                        className="tour-step-meta",
                    ),
                    html.H3(step.title, className="tour-step-title"),
                    html.P(step.body, className="tour-step-body"),
                    _points(step),
                    _try_it(index, step),
                ],
                className="tour-copy",
            ),
        ],
        id={"type": "tour-step", "index": index},
        className="tour-step",
        style={} if index == 0 else {"display": "none"},
    )


def _footer():
    """Progress, then the way forward. Dots stay, as the fine-grained control."""
    return html.Div(
        [
            html.Div(
                html.Div(
                    id="tour-progress",
                    className="tour-progress-fill",
                    style={"width": f"{100 / len(STEPS):.2f}%"},
                ),
                className="tour-progress",
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
                className="tour-footer-row",
            ),
        ],
        className="tour-footer",
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
                        [
                            _rail(),
                            html.Div(
                                [
                                    html.Div(
                                        [_step_panel(i, s) for i, s in enumerate(STEPS)],
                                        className="tour-stage",
                                    ),
                                    _footer(),
                                ],
                                className="tour-main",
                            ),
                        ],
                        className="tour-layout",
                    ),
                ],
                className="tour-body",
            )
        ],
        id="tour-modal",
        is_open=False,
        centered=True,
        size="xl",
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
