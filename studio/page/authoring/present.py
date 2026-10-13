"""Present mode — the full-screen slideshow laid over Studio.

Every page is in the markup from the start and only the current one is shown, so
turning a page is a class change in the browser (assets/studio_present.js), not a
server round trip. The server only builds the show and takes it down again.
"""
from __future__ import annotations

from dash import html

from studio.page.slideshow import ShowSlide, Slideshow

# The pattern id both ends of the show share: ``open`` on the top bar, ``close`` here.
PRESENT_TYPE = "qs-present"


def present_button(enabled: bool) -> html.Button:
    """The top bar's Present button — live only once there is a delivered deck."""
    return html.Button(
        [html.I(className="bi bi-easel"), "Present"],
        id={"type": PRESENT_TYPE, "op": "open"},
        className="qs-btn-ghost qs-present-open",
        disabled=not enabled,
        title="Present the deck full screen" if enabled else "Generate a deck to present it",
    )


def slideshow_overlay(show: Slideshow) -> html.Div:
    total = len(show.slides)
    return html.Div(
        [
            html.Div(
                [_slide(slide, n, total, current=n == show.start)
                 for n, slide in enumerate(show.slides)],
                className="qs-present-stage",
            ),
            html.Button(
                html.I(className="bi bi-x-lg"),
                id={"type": PRESENT_TYPE, "op": "close"},
                className="qs-present-close",
                title="End the slideshow (Esc)",
            ),
            html.Div("← → to move · Esc to end", className="qs-present-hint"),
        ],
        className="qs-present",
        role="dialog",
        **{"aria-modal": "true", "aria-label": "Slideshow"},
    )


def _slide(slide: ShowSlide, n: int, total: int, *, current: bool) -> html.Figure:
    return html.Figure(
        [
            _face(slide),
            html.Figcaption(
                [
                    html.Span(f"{n + 1} / {total}", className="qs-present-count"),
                    html.Span("Edits on this page show in the exported PPTX",
                              className="qs-present-note") if slide.edits_not_shown else None,
                ],
                className="qs-present-caption",
            ),
        ],
        className="qs-present-slide" + (" is-current" if current else ""),
    )


def _face(slide: ShowSlide):
    if slide.image_url:
        return html.Img(src=slide.image_url, alt=slide.title, className="qs-present-img")
    return html.Div(
        [
            html.Div(slide.title, className="qs-present-missing-title"),
            html.P("This page could not be drawn here. It is in the exported PPTX.",
                   className="qs-present-missing-sub"),
        ],
        className="qs-present-missing",
    )
