"""Export mode — a preview grid of every page plus the real download button.

The PowerPoint is produced by materializing the exact document; this view just
previews each page and marks the hidden ones as excluded.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from dash import html

from studio.deck.model import DeckSpec
from studio.page.slide import render_slide

from studio.page.authoring.derive import _hidden_ids, _is_hidden


def export_body(deck: DeckSpec, doc: Optional[Mapping[str, Any]]) -> html.Div:
    hidden_n = len(_hidden_ids(doc))
    thumbs = []
    for i, s in enumerate(deck.slides):
        hidden = _is_hidden(doc, i)
        thumbs.append(
            html.Div(
                [
                    html.Div(html.Div(render_slide(s, i + 1, len(deck.slides)), className="qs-exp-scale"), className="qs-exp-thumb-frame"),
                    html.Div(
                        [
                            html.Span(str(i + 1), className="qs-exp-num"),
                            html.Span(s.title or s.eyebrow or s.layout, className="qs-exp-name"),
                            html.Span("Excluded", className="qs-exp-excl") if hidden else None,
                        ],
                        className="qs-exp-cap",
                    ),
                ],
                className="qs-exp-card" + (" excluded" if hidden else ""),
            )
        )
    note = (
        f"{len(deck.slides) - hidden_n} of {len(deck.slides)} pages export"
        + (f" · {hidden_n} hidden page(s) excluded" if hidden_n else "")
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className="bi bi-filetype-pptx"), "Export preview"], className="qs-panel-title"),
                    html.P(
                        "The PowerPoint is produced by materializing this exact document — your "
                        "edits, page order and hidden-page choices included. Nothing is regenerated.",
                        className="qs-exp-sub",
                    ),
                    html.Div(note, className="qs-exp-note"),
                    html.Button(
                        [html.I(className="bi bi-download"), "Download .pptx"],
                        id={"type": "qs-export", "loc": "preview"},
                        className="qs-generate-btn",
                    ),
                ],
                className="qs-exp-head",
            ),
            html.Div(thumbs, className="qs-exp-grid"),
        ],
        className="qs-export",
    )
