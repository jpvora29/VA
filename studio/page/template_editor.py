"""The canvas's editing surface for a delivered deck: the edit bar and the Fields drawer.

Focus & finish: the slide gets the room, and editing appears where it is needed.

* the **edit panel** appears only when a text box on the slide is clicked. It names the box
  ("Editing: Slide headline"), holds one field per paragraph, and commits them together with
  Apply (or Ctrl/⌘+Enter). The slide shows the new words as they are typed
  (assets/studio_v6.js). Nothing else is listed: the slide is how a box is chosen.

Presentation only: the address of a box is ``slide:shape`` (or ``slide:shape:row:col``),
from :mod:`studio.template_fill.text_edits`, which is also where every edit is folded in.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from dash import dcc, html

from studio.template_fill import text_edits as TE

# Shape names PowerPoint makes up ("TextBox 12", "Rectangle 3", "Google Shape;41;p7") say
# nothing to an author, so they are not used as labels.
_GENERIC_NAME = re.compile(
    r"^(text ?box|rectangle|rounded rectangle|oval|shape|google shape|content placeholder|"
    r"text placeholder|subtitle|footer|slide number|date placeholder|group|object|"
    r"freeform|table)\b[\s;\d\w]*$",
    re.IGNORECASE,
)


def _is_generic_name(name: str) -> bool:
    """A name PowerPoint made up rather than one an author chose.

    Its own names end in a counter ("TextBox 12", "Rectangle: Single Corner Snipped 17") or
    carry an importer's separators ("Google Shape;41;p7"); an author's ("Key Messages") do not.
    """
    return bool(_GENERIC_NAME.match(name) or re.search(r"\d+\s*$", name) or ";" in name
                or ":" in name)


def _snippet(text: str, words: int = 6) -> str:
    parts = str(text or "").split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def block_label(shape: Any, slide: Any, block: TE.EditableText) -> str:
    """What the edit bar calls a box: "Slide headline", "Key Highlights · row 2", "“Premium grew…”"."""
    if block.address.is_cell:
        table = getattr(shape, "table", None) or []
        row, col = block.address.row, block.address.col
        header = str(table[0][col]).strip() if table and row > 0 and col < len(table[0]) else ""
        return f"{header} · row {row}" if header else f"Table cell · row {row + 1}, column {col + 1}"
    name = str(getattr(shape, "name", "") or "").strip()
    first = block.original[0] if block.original else ""
    title = ""
    try:
        title = str(slide.title() or "").strip()
    except Exception:  # noqa: BLE001 — a slide without a title is still editable
        title = ""
    if name.lower().startswith("title") or (title and first.strip() == title):
        return "Slide headline"
    if name and not _is_generic_name(name):
        return name
    if len(block.original) > 1:
        return f"Commentary · {len(block.original)} points"
    return f"“{_snippet(first, 4)}”"


def text_blocks(slide: Any, slide_idx: int, edits) -> List[Tuple[TE.EditableText, str]]:
    """Every editable piece of text on the page, in reading order, with its label."""
    found: List[Tuple[Any, TE.EditableText]] = []
    for shape in getattr(slide, "shapes", []) or []:
        if getattr(shape, "kind", "") == "table":
            found.extend((shape, b) for b in TE.editable_cells(shape, slide_idx, edits))
            continue
        block = TE.editable_text(shape, slide_idx, edits)
        if block is not None:
            found.append((shape, block))

    def reading_order(item):
        shape, _ = item
        return (int(getattr(shape, "y", 0) or 0) // 200000, int(getattr(shape, "x", 0) or 0))

    found.sort(key=reading_order)
    return [(block, block_label(shape, slide, block)) for shape, block in found]


# ── the edit bar ─────────────────────────────────────────────────────────────


def _rows_for(line: str, *, per_row: int = 72) -> int:
    return max(1, min(6, len(str(line or "")) // per_row + 1))


def _line_field(block: TE.EditableText, index: int, line: str, *, many: bool) -> html.Div:
    return html.Div(
        [
            html.Span(str(index + 1), className="qs7-ln-num") if many else None,
            dcc.Textarea(
                id={"type": "qs-tf-line", "at": block.address.key, "i": index},
                value=line, rows=_rows_for(line), placeholder="Write this line…",
                className="qs7-ln-input", spellCheck=True,
            ),
            html.Button(
                html.I(className="bi bi-x-lg"),
                id={"type": "qs-tf-linedel", "at": block.address.key, "i": index},
                n_clicks=0, className="qs7-icon-btn qs7-ln-del", title="Delete this line",
                **{"aria-label": f"Delete line {index + 1}"},
            ) if many else None,
        ],
        className="qs7-ln",
    )


def edit_bar_empty() -> html.Div:
    """No box selected: the panel is hidden (CSS reads ``is-empty``); the hint is for the
    moment before the first click, when a screen reader lands here."""
    return html.Div(
        html.Span([html.I(className="bi bi-cursor-text"),
                   html.Span("Click any text on the slide to edit it")],
                  className="qs7-edit-hint"),
        className="qs7-editbar is-empty", **{"data-at": ""},
    )


def edit_bar(block: Optional[TE.EditableText], label: str = "") -> html.Div:
    """The contextual editor for the selected box, or the prompt to pick one."""
    if block is None:
        return edit_bar_empty()
    many = len(block.lines) > 1
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [html.Span("Editing", className="qs7-edit-kicker"),
                         html.Span(label or "Text", className="qs7-edit-label", title=label),
                         html.Span("edited", className="qs7-tag ok") if block.edited else None],
                        className="qs7-edit-title",
                    ),
                    html.Button(html.I(className="bi bi-x-lg"),
                                id={"type": "qs7-close", "at": block.address.key}, n_clicks=0,
                                className="qs7-icon-btn qs7-close", title="Close",
                                **{"aria-label": "Close the editor"}),
                ],
                className="qs7-edit-head",
            ),
            html.Div([_line_field(block, i, line, many=many) for i, line in enumerate(block.lines)],
                     className="qs7-ln-list" + (" is-many" if many else "")),
            html.Div(
                [
                    html.Button([html.I(className="bi bi-check2"), html.Span("Apply")],
                                id={"type": "qs-tf-apply", "at": block.address.key}, n_clicks=0,
                                className="qs7-btn primary qs-v5-ripple",
                                title="Apply (Ctrl+Enter)"),
                    html.Button(html.I(className="bi bi-plus-lg"),
                                id={"type": "qs-tf-lineadd", "at": block.address.key}, n_clicks=0,
                                className="qs7-icon-btn", title="Add a line"),
                    html.Button(html.I(className="bi bi-arrow-counterclockwise"),
                                id={"type": "qs-tf-reset", "at": block.address.key}, n_clicks=0,
                                className="qs7-icon-btn", disabled=not block.edited,
                                title="Put this text back to what the deck says"),
                ],
                className="qs7-edit-actions",
            ),
        ],
        className="qs7-editbar" + (" is-edited" if block.edited else ""),
        **{"data-at": block.address.key},
    )


# ── the panel ────────────────────────────────────────────────────────────────


def edit_panel(editor: Any, slot_panel: Any = None) -> html.Aside:
    """The floating panel around the editor. Shown only while a box is selected."""
    return html.Aside([editor, slot_panel], className="qs7-drawer qs7-panel",
                      **{"aria-label": "Edit text"})
