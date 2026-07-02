"""Canvas mode — the Boardroom Canvas: page rail, live surface, inspector, library.

``canvas_body`` lays out the three columns (pages panel · canvas center · widget
inspector) plus the on-demand component-library modal, and the zoom controls.
The pages panel groups slides into numbered sections split on divider pages.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional

from dash import html

from studio.deck.model import DeckSpec
from studio.page import canvas as CV
from studio.page import document as D

from studio.page.authoring.constants import ZOOM_FIT, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP
from studio.page.authoring.derive import _is_hidden, slide_status
from studio.page.authoring.inspector import _select_hint, _widget_inspector

_COMPONENTS = [
    ("bi-bar-chart-line", "Premium trend"),
    ("bi-bar-chart-steps", "Variance bridge"),
    ("bi-grid-3x3", "Portfolio heatmap"),
    ("bi-bullseye", "Opportunity matrix"),
    ("bi-trophy", "Ranking table"),
    ("bi-people", "Peer benchmark"),
    ("bi-radar", "Risk radar"),
    ("bi-card-checklist", "Decision table"),
]


def _component_library() -> html.Div:
    cards = [
        html.Div(
            [html.I(className=f"bi {icon}"), html.Span(name, className="qs-comp-name")],
            className="qs-comp-card",
            draggable="true",
        )
        for icon, name in _COMPONENTS
    ]
    return html.Div(
        [
            html.Div([html.I(className="bi bi-grid-1x2"), "Component library"], className="qs-comp-title"),
            html.Div(cards, className="qs-comp-grid"),
        ],
        className="qs-comp-lib",
    )


def _page_toolbar(idx: int, total: int, hidden: bool) -> html.Div:
    """Context toolbar — real page operations on the active slide (blueprint §Page
    Actions). Each button mutates the shared document via ``qs-pageop``."""
    def op(o, icon, label, *, disabled=False, danger=False):
        return html.Button(
            [html.I(className=f"bi {icon}"), html.Span(label, className="qs-op-lbl")],
            id={"type": "qs-pageop", "op": o, "idx": idx},
            className="qs-op-btn" + (" danger" if danger else ""),
            disabled=disabled,
            title=label,
        )

    return html.Div(
        [
            op("up", "bi-arrow-up", "Move up", disabled=idx == 0),
            op("down", "bi-arrow-down", "Move down", disabled=idx >= total - 1),
            op("hide", "bi-eye" if hidden else "bi-eye-slash", "Show" if hidden else "Hide"),
            op("duplicate", "bi-files", "Duplicate"),
            op("delete", "bi-trash3", "Delete", danger=True),
        ],
        className="qs-op-bar",
    )


def normalized_zoom(value: Any) -> int:
    try:
        zoom = int(value)
    except (TypeError, ValueError):
        zoom = ZOOM_FIT
    return max(ZOOM_MIN, min(ZOOM_MAX, zoom))


def adjusted_zoom(value: Any, operation: str) -> int:
    zoom = normalized_zoom(value)
    if operation == "in":
        return min(ZOOM_MAX, zoom + ZOOM_STEP)
    if operation == "out":
        return max(ZOOM_MIN, zoom - ZOOM_STEP)
    return ZOOM_FIT


def zoom_scale(value: Any) -> float:
    return round(normalized_zoom(value) / ZOOM_FIT, 4)


def _zoom_controls(zoom: int) -> html.Div:
    def control(operation: str, icon: str, label: str) -> html.Button:
        return html.Button(
            html.I(className=f"bi {icon}"),
            id={"type": "qs-zoom", "op": operation},
            className="qs-zoom-btn",
            title=label,
            **{"aria-label": label},
        )

    return html.Div(
        [
            html.I(className="bi bi-display qs-zoom-display"),
            control("out", "bi-dash-lg", "Zoom out"),
            html.Span(f"{zoom}%", className="qs-zoom-value"),
            control("in", "bi-plus-lg", "Zoom in"),
            control("fit", "bi-arrows-fullscreen", "Fit slide"),
        ],
        className="qs-zoom-controls",
    )


def canvas_body(
    deck: DeckSpec,
    active_idx: int,
    doc: Optional[Mapping[str, Any]],
    sel: Optional[str],
    zoom: Any = ZOOM_FIT,
    inspector_tab: str = "setup",
    library_category: str = "all",
    library_tab: str = "all",
    library_view: str = "grid",
    library_search: str = "",
    inspector_collapsed: bool = False,
    library_collapsed: bool = False,
    library_open: bool = False,
) -> html.Div:
    active_idx = max(0, min(active_idx, len(deck.slides) - 1))
    zoom = normalized_zoom(zoom)
    slide = deck.slides[active_idx]
    hidden = _is_hidden(doc, active_idx)
    sid = D.sid_at(doc, active_idx) if doc else None
    widgets = D.page_widgets(doc, sid) if (doc and sid) else []
    page_style = D.effective_page_style(doc, sid) if (doc and sid) else {}
    if sel and not any(w["id"] == sel for w in widgets):
        sel = None
    center = html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f"Page {active_idx + 1} of {len(deck.slides)}", className="qs-canvas-meta"),
                            html.Span("Hidden from export", className="qs-hidden-tag") if hidden else None,
                            html.Span(f"{len(widgets)} widgets", className="qs-canvas-chip"),
                            html.Button(
                                [html.I(className="bi bi-plus-lg"), "Add component"],
                                id={"type": "qs-lib-toggle", "op": "open"},
                                className="qs-lib-open-btn",
                            ),
                        ],
                        className="qs-canvas-meta-wrap",
                    ),
                    _page_toolbar(active_idx, len(deck.slides), hidden),
                ],
                className="qs-canvas-bar",
            ),
            html.Div(
                [
                    html.Div("16:9", className="qs-aspect-cue"),
                    html.Div(
                        CV.canvas_surface(
                            widgets,
                            sel,
                            layout=slide.layout,
                            accent=slide.accent,
                            page_style=page_style,
                        ),
                        className="qs-slide-frame canvas"
                        + (" is-hidden" if hidden else ""),
                        style={"transform": f"scale({zoom_scale(zoom)})"},
                    ),
                ],
                className="qs-canvas-viewport",
            ),
            html.Div(
                [
                    _zoom_controls(zoom),
                    html.Span("Snap guides hidden", className="qs-grid-status"),
                ],
                className="qs-canvas-footer",
            ),
        ],
        className="qs-canvas-center",
    )
    left = _pages_panel(deck, active_idx, doc)
    right = (
        _widget_inspector(doc, sid, sel, inspector_tab, inspector_collapsed)
        if (sel and sid)
        else _select_hint(doc, sid, inspector_collapsed)
    )
    canvas_classes = ["qs-canvas"]
    if inspector_collapsed:
        canvas_classes.append("inspector-collapsed")
    if library_open:
        canvas_classes.append("library-open")
    children = [left, center, right]
    if library_open:
        children.append(
            _library_modal(library_category, library_tab, library_view, library_search)
        )
    return html.Div(children, className=" ".join(canvas_classes))


def _library_modal(category: str, tab: str, view: str, search: str) -> html.Div:
    """The component library as an on-demand popup, freeing the canvas for the QBR."""
    return html.Div(
        [
            html.Button(className="qs-lib-backdrop", id={"type": "qs-lib-toggle", "op": "close-bd"}),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [html.I(className="bi bi-grid-1x2"), "Add a component"],
                                className="qs-lib-modal-title",
                            ),
                            html.Button(
                                html.I(className="bi bi-x-lg"),
                                id={"type": "qs-lib-toggle", "op": "close"},
                                className="qs-lib-modal-close",
                            ),
                        ],
                        className="qs-lib-modal-head",
                    ),
                    CV.palette(category=category, tab=tab, view=view, search=search, collapsed=False),
                ],
                className="qs-lib-modal-card",
            ),
        ],
        id="qs-lib-modal",
        className="qs-lib-modal",
    )


def _divider_label(
    deck: DeckSpec,
    idx: int,
    doc: Optional[Mapping[str, Any]],
) -> str:
    """Use the live divider headline so rail labels follow canvas edits."""
    if doc:
        sid = D.sid_at(doc, idx)
        if sid:
            headline = next(
                (w for w in D.page_widgets(doc, sid) if w.get("kind") == "headline"),
                None,
            )
            if headline:
                text = str((headline.get("props") or {}).get("text") or "").strip()
                if text:
                    return text
    slide = deck.slides[idx]
    return slide.title or slide.eyebrow or "Section"


def _page_sections(
    deck: DeckSpec,
    doc: Optional[Mapping[str, Any]] = None,
) -> List[Mapping[str, Any]]:
    """Group page indices into numbered sections split on divider pages."""
    sections: List[dict] = []
    cur: Optional[dict] = None
    for i, slide in enumerate(deck.slides):
        if slide.layout == "divider":
            cur = {"label": _divider_label(deck, i, doc), "idxs": [i]}
            sections.append(cur)
        else:
            if cur is None:
                cur = {"label": "Executive summary", "idxs": []}
                sections.append(cur)
            cur["idxs"].append(i)
    for number, section in enumerate(sections, start=1):
        section["number"] = number
    return sections


def _thumb_preview(deck: DeckSpec, idx: int, doc: Optional[Mapping[str, Any]]) -> html.Div:
    """A live read-only miniature of the page's actual canvas composition."""
    sid = D.sid_at(doc, idx) if doc else None
    widgets = D.page_widgets(doc, sid) if (doc and sid) else []
    slide = deck.slides[idx]
    page_style = D.effective_page_style(doc, sid) if (doc and sid) else {}
    return html.Div(
        CV.thumbnail_surface(
            widgets,
            layout=slide.layout,
            accent=slide.accent,
            page_style=page_style,
        ),
        className="qs-pg-thumb",
    )


def _pages_panel(deck: DeckSpec, active_idx: int, doc: Optional[Mapping[str, Any]]) -> html.Div:
    sections = _page_sections(deck, doc)
    section_groups: List[Any] = []
    for section in sections:
        page_cards: List[Any] = []
        for i in section["idxs"]:
            slide = deck.slides[i]
            hidden = _is_hidden(doc, i)
            display_title = (
                _divider_label(deck, i, doc)
                if slide.layout == "divider"
                else (slide.title or slide.eyebrow or slide.layout)
            )
            page_cards.append(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Span(str(i + 1), className="qs-pg-num"),
                                html.I(className="bi bi-eye-slash qs-pg-hidden")
                                if hidden
                                else html.Span(className=f"qs-thumb-dot {slide_status(slide)[0]}"),
                            ],
                            className="qs-pg-head",
                        ),
                        _thumb_preview(deck, i, doc),
                        html.Span(display_title, className="qs-pg-title"),
                    ],
                    id={"type": "qs-goto", "idx": i, "src": "pages"},
                    n_clicks=0,
                    role="button",
                    tabIndex=0,
                    title=f"Open page {i + 1}: {display_title}",
                    className=(
                        "qs-pg"
                        + (" active" if i == active_idx else "")
                        + (" hidden" if hidden else "")
                        + (" divider" if slide.layout == "divider" else "")
                    ),
                )
            )
        section_groups.append(
            html.Details(
                [
                    html.Summary(
                        [
                            html.I(className="bi bi-chevron-down qs-pg-section-chevron"),
                            html.Span(str(section["number"]), className="qs-pg-section-num"),
                            html.Span(section["label"], className="qs-pg-section-name"),
                            html.Span(str(len(page_cards)), className="qs-pg-section-count"),
                        ],
                        className="qs-pg-section",
                    ),
                    html.Div(page_cards, className="qs-pg-section-pages"),
                ],
                open=True,
                className="qs-pg-section-group",
            )
        )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [html.I(className="bi bi-collection"), "Pages"],
                                className="qs-panel-title",
                            ),
                            html.Div(
                                [
                                    html.Span(f"{len(deck.slides)} pages"),
                                    html.Span(f"{len(sections)} sections"),
                                ],
                                className="qs-pg-summary",
                            ),
                        ]
                    ),
                ],
                className="qs-pg-toolbar",
            ),
            html.Div(section_groups, className="qs-pg-list"),
            html.Div(
                [
                    html.Button(
                        [html.I(className="bi bi-file-earmark-plus"), "Add page"],
                        id={"type": "qs-pageop", "op": "add", "idx": active_idx},
                        className="qs-pg-footer-btn",
                    ),
                    html.Button(
                        [html.I(className="bi bi-folder-plus"), "Insert section"],
                        id={"type": "qs-pageop", "op": "section", "idx": active_idx},
                        className="qs-pg-footer-btn section",
                    ),
                ],
                className="qs-pg-footer",
            ),
        ],
        className="qs-pages-panel",
    )
