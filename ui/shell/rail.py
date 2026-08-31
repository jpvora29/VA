"""The left rail every workspace shares.

There is one rail *frame* — 264px, light, hairline on the right, a titled head and a
scrolling body — and each workspace fills it with its own sections. That is what stops
the left edge of the app from changing identity when you switch tabs.

Pure layout: no callbacks, no state. The Studio rail is still assembled in
``studio.page.authoring.chrome`` (its buttons carry Studio's pattern-matching ids);
it uses these same class names so both rails render as one component.
"""
from __future__ import annotations

from typing import Any, Sequence

from dash import html

# The shared class every rail carries. Named here because the Chatbot's clientside
# collapse toggle rewrites the whole className and must rebuild it verbatim.
RAIL_CLASS = "va-rail"


def rail_section(label: str | None, children: Sequence[Any]) -> html.Div:
    """A labelled group inside the rail body."""
    head = [html.Div(label, className="va-rail-label")] if label else []
    return html.Div([*head, html.Div(list(children), className="va-rail-group")],
                    className="va-rail-section")


def rail_frame(
    title: str,
    body: Sequence[Any],
    *,
    action: Any | None = None,
    footer: Any | None = None,
    className: str = "",
    id: str | None = None,
) -> html.Aside:
    """Head + scrolling body + optional footer, in the shared rail chrome.

    ``action`` is the one control that belongs beside the title (the Chatbot puts its
    collapse toggle there); everything else belongs in a body section. ``className``
    is what the caller adds ON TOP of ``RAIL_CLASS`` — never the whole attribute.
    """
    head: list[Any] = [html.Span(title, className="va-rail-title")]
    if action is not None:
        head.append(action)
    blocks: list[Any] = [
        html.Div(head, className="va-rail-head"),
        html.Div(list(body), className="va-rail-body"),
    ]
    if footer is not None:
        blocks.append(html.Div(footer, className="va-rail-foot"))
    kwargs: dict[str, Any] = {}
    if id is not None:
        kwargs["id"] = id
    return html.Aside(blocks, className=f"{RAIL_CLASS} {className}".strip(), **kwargs)
