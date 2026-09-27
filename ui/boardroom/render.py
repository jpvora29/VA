"""Render an editable Boardroom document to Dash.

The board reads as an executive brief: a breadcrumb bar with the board's two
actions, the chapters as numbered tabs that are always in view, and on every
page an eyebrow, the question the chapter answers set as its headline, the scope
line, the widgets, and a footer that walks to the previous and next chapter.
Switching chapter is clientside (``ui.boardroom.callbacks``), so it costs no
server round trip and never re-renders a chart.

Two modes:
  * view  — clean dashboard (hidden widgets/pages dropped).
  * edit  — adds a per-widget control bar, page toolbars, an "add widget" affordance
            and page management, plus governed-grid size handles.

Layout is a governed 12-column grid (no free-form pixel positioning): each widget
spans sm/md/lg/full and is reordered with move controls — overlaps are impossible.

All interactive ids are pattern-matching and scoped by ``card_idx`` (the chat
message index) so multiple boardroom cards on screen stay independent. The
callbacks that act on these ids live in ``ui.boardroom.callbacks``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from dash import dcc, html

from ui.boardroom import catalog, widgets_generated, widgets_library
from ui.boardroom.model import GRID_COLUMNS, SIZE_SPAN, SIZES, widget_height, widget_span
from ui.boardroom.themes import theme

_SIZE_LABELS = {"sm": "S", "md": "M", "lg": "L", "full": "Full"}


def _id(t: str, card_idx: int, **kw) -> Dict[str, Any]:
    d = {"type": t, "idx": card_idx}
    d.update(kw)
    return d


def _icon_btn(t: str, card_idx: int, icon: str, title: str, cls: str = "", **kw):
    return html.Button(
        html.I(className=icon),
        id=_id(t, card_idx, **kw),
        n_clicks=0,
        className=f"bm-wbtn {cls}".strip(),
        title=title,
    )


# ───────────────────────────── widget body ──────────────────────────────


def _widget_body(widget: Dict[str, Any], figures: List[Any]):
    kind = widget.get("kind")
    content = catalog.content_of(kind)
    data = widget.get("data") or {}

    if content == "chart":
        i = data.get("spec_index")
        if isinstance(i, int) and 0 <= i < len(figures) and figures[i] is not None:
            return html.Div(
                dcc.Graph(figure=figures[i], config={"displayModeBar": False, "responsive": True}, className="bm-chart-fig"),
                className="bm-chart-panel",
            )
        return html.Div(
            [html.I(className="bi bi-bar-chart-line"), html.Span("Chart unavailable")],
            className="bm-charts-empty",
        )

    if content == "bespoke":
        return widgets_generated.render_bespoke(kind, data)

    return widgets_library.render_content(content, widget)


# ───────────────────────────── widget chrome ──────────────────────────────


def _widget_chrome(widget, card_idx, page_id, i, n):
    wid = widget["id"]
    meta = widget.get("meta", {})
    is_user = widget.get("origin") == "user"
    edited = meta.get("edited")
    hidden = not meta.get("visible_board", True)

    left = [
        # Drag handle — assets/boardroom_dnd.js listens on .bm-grip and reports
        # drops into the bm-dnd store (handled in ui.boardroom.callbacks).
        html.Span(
            html.I(className="bi bi-grip-vertical"),
            className="bm-grip",
            draggable="true",
            title="Drag to reorder",
        ),
        html.Span(catalog.meta_of(widget["kind"]).get("label", widget["kind"]), className="bm-w-kind"),
    ]
    if widget.get("title"):
        left.append(html.Span(widget["title"], className="bm-w-title"))
    if edited:
        left.append(html.Span([html.I(className="bi bi-pencil-fill"), "Edited"], className="bm-w-badge edited"))
    if hidden:
        left.append(html.Span("Hidden", className="bm-w-badge hidden"))
    if meta.get("locked"):
        left.append(html.Span([html.I(className="bi bi-lock-fill")], className="bm-w-badge locked"))

    # Inline width control = direct positioning on the governed grid.
    size_now = meta.get("size", "md")
    span_now = widget_span(widget)
    height_now = widget_height(widget)
    size_group = html.Div(
        [
            html.Button(
                _SIZE_LABELS[s],
                id=_id("bm-w-size", card_idx, wid=wid, size=s),
                n_clicks=0,
                className="bm-size-btn" + (" active" if s == size_now and meta.get("span") in (None, SIZE_SPAN[s]) else ""),
                title=f"Set width: {_SIZE_LABELS[s]}",
            )
            for s in SIZES
        ],
        className="bm-size-group",
    )
    # Fine-grained restructuring: ±1 column width, ±height, back-to-auto.
    fine_group = html.Div(
        [
            html.Button(html.I(className="bi bi-chevron-bar-left"),
                        id=_id("bm-w-span", card_idx, wid=wid, delta=-1), n_clicks=0,
                        className="bm-size-btn", title="Narrower (−1 column)",
                        disabled=span_now <= 1),
            html.Span(f"{span_now}/{GRID_COLUMNS}", className="bm-span-readout",
                      title="Current width (grid columns)"),
            html.Button(html.I(className="bi bi-chevron-bar-right"),
                        id=_id("bm-w-span", card_idx, wid=wid, delta=1), n_clicks=0,
                        className="bm-size-btn", title="Wider (+1 column)",
                        disabled=span_now >= GRID_COLUMNS),
            html.Button(html.I(className="bi bi-arrows-collapse"),
                        id=_id("bm-w-height", card_idx, wid=wid, delta=-1), n_clicks=0,
                        className="bm-size-btn", title="Shorter (−40 px)"),
            html.Span(f"{height_now}px" if height_now else "auto",
                      className="bm-span-readout", title="Current height"),
            html.Button(html.I(className="bi bi-arrows-expand"),
                        id=_id("bm-w-height", card_idx, wid=wid, delta=1), n_clicks=0,
                        className="bm-size-btn", title="Taller (+40 px)"),
            html.Button(html.I(className="bi bi-magic"),
                        id=_id("bm-w-hauto", card_idx, wid=wid), n_clicks=0,
                        className="bm-size-btn", title="Auto height (fit content)",
                        disabled=height_now is None),
        ],
        className="bm-size-group bm-fine-group",
    )

    buttons = [
        _icon_btn("bm-w-edit", card_idx, "bi bi-pencil-square", "Edit", wid=wid),
        _icon_btn("bm-w-up", card_idx, "bi bi-arrow-up", "Move earlier", wid=wid) if i > 0 else None,
        _icon_btn("bm-w-down", card_idx, "bi bi-arrow-down", "Move later", wid=wid) if i < n - 1 else None,
        _icon_btn("bm-w-dup", card_idx, "bi bi-files", "Duplicate", wid=wid),
        _icon_btn(
            "bm-w-hide", card_idx,
            "bi bi-eye-slash" if not hidden else "bi bi-eye",
            "Hide from presentation" if not hidden else "Show", wid=wid,
        ),
        _icon_btn("bm-w-reset", card_idx, "bi bi-arrow-counterclockwise", "Reset to generated", wid=wid)
        if (edited and not is_user) else None,
        _icon_btn("bm-w-src", card_idx, "bi bi-database-check", "View source evidence", wid=wid)
        if not is_user else None,
        _icon_btn("bm-w-hist", card_idx, "bi bi-clock-history", "Revision history", wid=wid),
        _icon_btn("bm-w-del", card_idx, "bi bi-trash", "Delete", cls="danger", wid=wid) if is_user else None,
    ]
    return html.Div(
        [
            html.Div(left, className="bm-w-meta"),
            html.Div(
                [size_group, fine_group,
                 html.Div([b for b in buttons if b is not None], className="bm-w-actions")],
                className="bm-w-controls",
            ),
        ],
        className="bm-w-chrome",
    )


def _render_widget(widget, figures, edit_mode, card_idx, page_id, i, n):
    meta = widget.get("meta", {})
    hidden = not meta.get("visible_board", True)
    if hidden and not edit_mode:
        return None  # view mode drops hidden widgets entirely

    span = widget_span(widget)
    height_px = widget_height(widget)
    theme_key = meta.get("theme") or "default"
    th = theme(theme_key)

    inner = [_widget_chrome(widget, card_idx, page_id, i, n)] if edit_mode else []
    body_style = {"height": f"{height_px}px", "overflowY": "auto"} if height_px else {}
    inner.append(html.Div(_widget_body(widget, figures), className="bm-gw-body", style=body_style))

    cls = (
        "bm-gw"
        + (" is-hidden" if hidden else "")
        + (" is-edit" if edit_mode else "")
        + (" is-themed" if theme_key != "default" else "")
    )
    dnd_attrs = (
        {"data-wid": widget["id"], "data-card": str(card_idx)} if edit_mode else {}
    )
    return html.Div(
        inner,
        className=cls,
        style={
            "gridColumn": f"span {span}",
            "--bm-accent": th["accent"],
            "--bm-soft": th["soft"],
            "--bm-ink": th["ink"],
        },
        **dnd_attrs,
    )


# ───────────────────────────── page ──────────────────────────────


def _size_label(s: str) -> str:
    return {"sm": "S", "md": "M", "lg": "L", "full": "Full"}.get(s, s)


def _page_toolbar(page, card_idx):
    pid = page["id"]
    return html.Div(
        [
            html.Div(
                [
                    dcc.Input(
                        id=_id("bm-page-title", card_idx, pid=pid),
                        value=page.get("title", ""),
                        debounce=True,
                        className="bm-page-title-input",
                        placeholder="Page title",
                    ),
                    dcc.Input(
                        id=_id("bm-page-caption", card_idx, pid=pid),
                        value=page.get("caption", ""),
                        debounce=True,
                        className="bm-page-caption-input",
                        placeholder="The question this step answers…",
                    ),
                ],
                className="bm-page-titles",
            ),
            html.Div(
                [
                    _icon_btn("bm-add-widget", card_idx, "bi bi-plus-square", "Add widget", cls="primary", pid=pid),
                    _icon_btn("bm-page-dup", card_idx, "bi bi-files", "Duplicate page", pid=pid),
                    _icon_btn("bm-page-up", card_idx, "bi bi-arrow-left", "Move page left", pid=pid),
                    _icon_btn("bm-page-down", card_idx, "bi bi-arrow-right", "Move page right", pid=pid),
                    _icon_btn(
                        "bm-page-lock", card_idx,
                        "bi bi-lock-fill" if page.get("locked") else "bi bi-unlock",
                        "Lock / unlock page", pid=pid,
                    ),
                    _icon_btn(
                        "bm-page-exp", card_idx,
                        "bi bi-file-earmark-slides" if page.get("visible_export", True) else "bi bi-file-earmark-x",
                        "Toggle include in export", pid=pid,
                    ),
                    _icon_btn("bm-page-del", card_idx, "bi bi-trash", "Delete page", cls="danger", pid=pid),
                ],
                className="bm-page-tools",
            ),
        ],
        className="bm-page-toolbar",
    )


def _scope_line(doc):
    """"Zurich — Canada / Canada / Property": who the board is about, then its scope.

    Plain text rather than pills — the chapter headline is the loudest thing on
    the page and the scope is its caption. Each value keeps where it came from
    as a tooltip, which is what the pills used to say.
    """
    parts = [html.Span(doc.get("title", ""), className="bm-scope-subject")] if doc.get("title") else []
    for chip in doc.get("scope") or []:
        value = str((chip or {}).get("value") or "").strip()
        if not value:
            continue
        label = str(chip.get("label") or "").strip()
        source = str(chip.get("source") or "").strip()
        tip = f"{label}: {value}" + (f" ({source})" if source else "")
        parts.append(html.Span(value, className="bm-scope-value", title=tip))
    if not parts:
        return None
    joined: List[Any] = []
    for i, part in enumerate(parts):
        if i:
            joined.append(html.Span("/", className="bm-scope-sep", **{"aria-hidden": "true"}))
        joined.append(part)
    return html.Div(joined, className="bm-scope-line")


def _page_heading(doc, page):
    """The chapter's eyebrow, its question set as the headline, and the scope.

    The question is the headline because it is what every widget below answers —
    a page seen on its own then says where in the argument it sits. The scope
    line repeats on every chapter so no page can be read out of scope.
    """
    title = (page.get("title") or "").strip()
    caption = (page.get("caption") or "").strip()
    return html.Div(
        [
            html.Div(
                [html.I(className=page.get("icon") or "bi bi-file-earmark"), html.Span(title)],
                className="bm-brief-eyebrow",
            ),
            html.H2(caption or title, className="bm-brief-headline"),
            _scope_line(doc),
        ],
        className="bm-brief-head",
    )


def _page_footer(pages, card_idx, page_index):
    """"2 of 4 — Pain points", with the way back and the way on, both named."""
    total = len(pages)
    if total <= 1:
        return None
    title = pages[page_index].get("title", "")
    steps = []
    if page_index > 0:
        steps.append(
            html.Button(
                [html.I(className="bi bi-arrow-left"),
                 html.Span(pages[page_index - 1].get("title", "Previous"))],
                id=_id("bm-goto", card_idx, page=page_index - 1, src=page_index),
                n_clicks=0,
                className="bm-foot-step prev",
                title="Previous chapter",
            )
        )
    if page_index < total - 1:
        steps.append(
            html.Button(
                [html.Span(f"Next: {pages[page_index + 1].get('title', '')}"),
                 html.I(className="bi bi-arrow-right")],
                id=_id("bm-goto", card_idx, page=page_index + 1, src=page_index),
                n_clicks=0,
                className="bm-foot-step next",
                title="Next chapter",
            )
        )
    return html.Div(
        [
            html.Div(f"{page_index + 1} of {total} — {title}", className="bm-foot-where"),
            html.Div(steps, className="bm-foot-steps"),
        ],
        className="bm-brief-foot",
    )


def _render_page(doc, page, figures, edit_mode, card_idx, page_index, active_page=0):
    # Filtered to dicts: an empty board saved before `build()` was fixed holds an
    # icon STRING where its widget list belongs, and iterating that hands each
    # character to `_render_widget` — which takes the whole transcript down.
    widgets = [w for w in (page.get("widgets") or []) if isinstance(w, dict)]
    n = len(widgets)
    grid_items = [
        _render_widget(w, figures, edit_mode, card_idx, page["id"], i, n) for i, w in enumerate(widgets)
    ]
    grid_items = [g for g in grid_items if g is not None]

    # `data-bm-grid` marks the grid for assets/boardroom_ui.js, which watches its
    # width and collapses the 12-column spans on narrow screens (a widget's span
    # is an inline style, so only the observer can override it responsively).
    body = [html.Div(grid_items, className="bm-grid", **{"data-bm-grid": "1"})]
    if not grid_items:
        body = [html.Div([html.I(className="bi bi-grid-3x3-gap"), html.Span("Empty page — add a widget")], className="bm-charts-empty")]

    children = [_page_heading(doc, page)]
    if edit_mode:
        children.append(_page_toolbar(page, card_idx))
    children.extend(body)
    if edit_mode:
        children.append(
            dcc.Textarea(
                id=_id("bm-page-notes", card_idx, pid=page["id"]),
                value=page.get("notes", ""),
                placeholder="Speaker notes (not shown on the board)…",
                className="bm-page-notes",
            )
        )
    children.append(_page_footer(doc.get("pages") or [], card_idx, page_index))

    return html.Div(
        children,
        id=_id("bm-page", card_idx, page=page_index),
        className="bm-page",
        style=({} if page_index == active_page else {"display": "none"}),
    )


# ───────────────────────────── header + pager ──────────────────────────────


def _header(doc, edit_mode, card_idx):
    """The breadcrumb bar: where you are, and the board's two actions.

    The breadcrumb names the review (the subtitle, e.g. "Q2 2026 premium
    performance"); the subject and its scope are stated on every chapter by the
    scope line, so they are not repeated up here.
    """
    crumb = (doc.get("subtitle") or "").strip() or doc.get("title", "")
    title_block = html.Div(
        [
            html.Span([html.I(className="bi bi-grid-1x2-fill"), html.Span("Boardroom")], className="bm-eyebrow"),
            html.Span("/", className="bm-crumb-sep", **{"aria-hidden": "true"}),
            html.Span(crumb, className="bm-crumb"),
        ],
        className="bm-title-block bm-breadcrumb",
    )
    actions = [
        html.Button(
            [html.I(className="bi bi-pencil-square" if not edit_mode else "bi bi-check2-circle"),
             "Edit" if not edit_mode else "Done"],
            id=_id("bm-edit-mode", card_idx),
            n_clicks=0,
            className="bm-export-btn" + (" active" if edit_mode else ""),
        ),
        html.Button(
            [html.I(className="bi bi-file-earmark-slides"), "Export to PPT"],
            id={"type": "boardroom-export", "idx": card_idx},
            n_clicks=0,
            className="bm-export-btn",
            title="Download this board as an editable PowerPoint deck",
        ),
    ]
    return html.Div([title_block, html.Div(actions, className="bm-actions")], className="bm-header")


def _chapters(pages, card_idx, active_page=0):
    """The chapters as numbered tabs, always in view above the page.

    They replace a slider that sat BELOW the pages, where a reader only found it
    after scrolling past the whole first chapter. The store beside them holds
    the open chapter for ``track_active_page``, so an edit-driven re-render
    reopens the same one.
    """
    if len(pages) <= 1:
        return None
    tabs = [
        html.Button(
            [html.Span(f"{p + 1}.", className="bm-chapter-n"), html.Span(pg.get("title", f"Page {p + 1}"))],
            id=_id("bm-chapter", card_idx, page=p),
            n_clicks=0,
            className="bm-chapter" + (" is-active" if p == active_page else ""),
            title=pg.get("caption") or pg.get("title", ""),
        )
        for p, pg in enumerate(pages)
    ]
    return html.Div(
        [
            html.Nav(tabs, className="bm-chapters", **{"aria-label": "Board chapters"}),
            dcc.Store(id=_id("bm-nav", card_idx), data=active_page),
        ],
        className="bm-chapter-bar",
    )


def render_document(
    doc: Dict[str, Any],
    figures: Optional[List[Any]] = None,
    *,
    edit_mode: bool = False,
    card_idx: int = 0,
    active_page: int = 0,
):
    """Render a whole document to a Dash card. `active_page` keeps the viewer on the
    page they were on across edit-driven re-renders (no jump back to page 0)."""
    doc = doc or {}
    figures = figures or []
    pages = doc.get("pages", []) or []
    # Clamp the remembered page (a page may have been deleted since).
    active_page = max(0, min(active_page or 0, max(0, len(pages) - 1)))

    page_divs = [
        _render_page(doc, pg, figures, edit_mode, card_idx, p, active_page)
        for p, pg in enumerate(pages)
    ]

    children = [_header(doc, edit_mode, card_idx)]
    chapters = _chapters(pages, card_idx, active_page)
    if chapters is not None:
        children.append(chapters)
    children.append(html.Div(page_divs, className="bm-pages"))

    if edit_mode:
        children.append(
            html.Div(
                _icon_btn("bm-page-add", card_idx, "bi bi-plus-lg", "Add a blank page", cls="primary"),
                className="bm-addpage-bar",
            )
        )

    cls = "message boardroom-card bm-brief" + (" is-editing" if edit_mode else "")
    # `data-bm-card` lets the chapter switch scroll THIS card back to its top.
    return html.Div(children, className=cls, **{"data-bm-card": str(card_idx)})
