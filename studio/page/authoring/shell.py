"""Shell assembly — pick the body for the current mode and wrap it in the frame.

``body_for`` routes each mode to its body (and to the template-faithful preview
when a filled template doc is present); ``authoring_shell`` wraps that body with
the mode rail and top bar. This is the top-level entry the app callback renders.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from dash import html

from studio.deck.model import DeckSpec

from studio.page.authoring.canvas import canvas_body
from studio.page.authoring.chrome import _placeholder_topbar, mode_rail, top_bar
from studio.page.authoring.constants import ZOOM_FIT
from studio.page.authoring.derive import deck_counts
from studio.page.authoring.export import export_body
from studio.page.authoring.review import review_body
from studio.page.authoring.setup import setup_body


def empty_canvas() -> html.Div:
    return html.Div(
        [
            html.I(className="bi bi-easel2 qs-empty-icon"),
            html.Div("No deck yet", className="qs-empty-title"),
            html.P(
                "Open Setup, choose a client and period, then Generate deck. "
                "The whole studio — narrative, canvas and review — is built from the result.",
                className="qs-empty-sub",
            ),
            html.Button(
                [html.I(className="bi bi-sliders2"), "Open Setup"],
                id="qs-empty-setup",
                className="qs-generate-btn",
            ),
        ],
        className="qs-empty",
    )


def body_for(
    mode: str,
    deck: Optional[DeckSpec],
    view: Mapping[str, Any],
    doc: Optional[Mapping[str, Any]],
    *,
    cut_groups: Sequence[Mapping[str, Any]],
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
    tdoc: Optional[Mapping[str, Any]] = None,
) -> Any:
    if mode == "setup":
        return setup_body(cut_groups, filter_options=filter_options, filter_values=filter_values)
    # Template-faithful bodies: when a template doc exists it IS the deliverable —
    # the canvas previews the filled template, Review validates it, Export fills it.
    if tdoc:
        from studio.page import template_preview as TP

        if mode == "canvas":
            return TP.template_preview_body(tdoc, view)
        if mode == "review":
            return TP.template_review_body(tdoc)
        if mode == "export":
            return TP.template_export_body(tdoc)
    if deck is None or not deck.slides:
        return empty_canvas()
    idx = int(view.get("idx", 0))
    if mode == "canvas":
        return canvas_body(
            deck,
            idx,
            doc,
            view.get("sel"),
            view.get("zoom", ZOOM_FIT),
            view.get("tab", "setup"),
            view.get("lib_category", "all"),
            view.get("lib_tab", "all"),
            view.get("lib_view", "grid"),
            view.get("lib_search", ""),
            bool(view.get("inspector_collapsed", False)),
            bool(view.get("library_collapsed", False)),
            bool(view.get("library_open", False)),
        )
    if mode == "review":
        return review_body(deck, doc)
    if mode == "export":
        return export_body(deck, doc)
    return canvas_body(deck, idx, doc, view.get("sel"), view.get("zoom", ZOOM_FIT))


def authoring_shell(
    deck: Optional[DeckSpec],
    *,
    doc: Optional[Mapping[str, Any]] = None,
    mode: str = "setup",
    view: Mapping[str, Any] | None = None,
    cut_groups: Sequence[Mapping[str, Any]],
    filter_options: Mapping[str, Any] | None = None,
    filter_values: Mapping[str, Any] | None = None,
    tdoc: Optional[Mapping[str, Any]] = None,
) -> html.Div:
    view = view or {"idx": 0, "tab": "setup"}
    counts = deck_counts(deck, doc) if deck else {"total": 0}
    # When a filled template doc is present it IS the previewed deliverable (overall +
    # per product + per country), so the rail page-count should reflect ALL its slides,
    # not just the overall deck — otherwise it reads "17" while the canvas shows 25.
    if tdoc:
        counts = {"total": int(tdoc.get("n_slides", 0))}
    top = top_bar(deck, doc) if deck else _placeholder_topbar(enabled=bool(tdoc))
    body = body_for(
        mode, deck, view, doc,
        cut_groups=cut_groups, filter_options=filter_options, filter_values=filter_values,
        tdoc=tdoc,
    )
    return html.Div(
        [
            mode_rail(mode, counts),
            html.Div(
                [top, html.Div(body, id="qs-canvas", className="qs-canvas-host")],
                className="qs-shell-main",
            ),
        ],
        className=f"qs-root mode-{mode}",
    )
