"""The frame around every mode: the left mode rail and the top bar."""
from __future__ import annotations

from typing import Any, Mapping, Optional

from dash import html

from studio.deck.model import DeckSpec

from ui.shell.rail import rail_frame, rail_section

from studio.page.authoring.constants import MODES
from studio.page.authoring.derive import deck_counts


def mode_rail(active: str, counts: Mapping[str, int]) -> html.Aside:
    """Studio's left rail, in the shared ``va-rail`` frame (``ui.shell.rail``).

    The modes ARE a sequence (Setup -> Data -> Canvas -> Review), so they render as a
    numbered stepper: tile, step numeral, label. The brand block that used to head this
    rail is gone — the merged application names itself once, in the navbar.
    """
    items = [
        html.Button(
            [
                html.Span(
                    [html.I(className=f"bi {m['icon']}"),
                     html.Span(str(i), className="qs-step-num")],
                    className="qs-mode-tile",
                ),
                html.Span(
                    [
                        html.Span(m["label"], className="qs-mode-label"),
                        html.Span(m["hint"], className="qs-mode-hint"),
                    ],
                    className="qs-mode-text",
                ),
            ],
            id={"type": "qs-mode", "mode": m["id"]},
            className="qs-mode-btn" + (" active" if m["id"] == active else ""),
            title=m["hint"],
        )
        for i, m in enumerate(MODES, 1)
    ]
    return rail_frame(
        "Studio",
        [
            rail_section("Build", [html.Div(items, className="qs-mode-list")]),
            html.Div(
                [
                    html.Div(str(counts.get("total", 0)), className="qs-rail-count-num"),
                    html.Div("pages", className="qs-rail-count-lbl"),
                ],
                className="qs-rail-count",
            ),
        ],
        rail_id="studio",
        className="qs-mode-rail",
    )


def top_bar(deck: DeckSpec, doc: Optional[Mapping[str, Any]] = None) -> html.Header:
    meta = dict(deck.meta or {})
    carrier = meta.get("carrier") or "Carrier"
    country = meta.get("country") or "Market"
    year = meta.get("year") or ""
    report = "Executive Summary" if meta.get("report") == "exec" else "QBR"
    counts = deck_counts(deck, doc)
    ready = counts["needs_review"] == 0 and counts["total"] > 0
    return html.Header(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f"{carrier} · {country}", className="qs-deck-name"),
                            html.Span(f"{year} · {report}", className="qs-deck-period"),
                        ],
                        className="qs-deck-id",
                    ),
                    html.Span(
                        [html.I(className="bi bi-cloud-check"), "Saved in browser"],
                        className="qs-autosave",
                        title="The editable document persists in local storage and survives a refresh.",
                    ),
                ],
                className="qs-top-left",
            ),
            html.Div(
                [
                    html.Span(
                        [
                            html.I(className=f"bi {'bi-patch-check-fill' if ready else 'bi-clock-history'}"),
                            "Client-ready" if ready else f"{counts['needs_review']} to review",
                        ],
                        className="qs-ready-badge" + (" ok" if ready else " warn"),
                    ),
                    html.Button([html.I(className="bi bi-easel"), "Present"], className="qs-btn-ghost"),
                    html.Button(
                        [html.I(className="bi bi-filetype-pptx"), "Export PPTX"],
                        id={"type": "qs-export", "loc": "top"},
                        className="qs-btn-primary",
                    ),
                ],
                className="qs-top-right",
            ),
        ],
        className="qs-topbar",
    )


def _placeholder_topbar(enabled: bool = False) -> html.Header:
    return html.Header(
        [
            html.Div(
                [
                    html.Div(
                        [html.Span("New QBR deck", className="qs-deck-name"), html.Span("Not generated", className="qs-deck-period")],
                        className="qs-deck-id",
                    ),
                ],
                className="qs-top-left",
            ),
            html.Div(
                [html.Button([html.I(className="bi bi-filetype-pptx"), "Export PPTX"], id={"type": "qs-export", "loc": "top"}, className="qs-btn-primary", disabled=not enabled)],
                className="qs-top-right",
            ),
        ],
        className="qs-topbar",
    )
