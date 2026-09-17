"""Inline canvas text editing — what a user may retype on the canvas itself.

The canvas renders authored prose as ``contentEditable`` nodes tagged with a
dotted **path** into the owning widget's props (``text``, ``points.0.text``).
``assets/studio_canvas.js`` reads that path back on blur, and one Dash callback
commits it through :func:`studio.page.document.set_widget_text`.

This module owns the two pure rules that keep the surface safe:

* only *authored prose* leaves carry a path — numbers, series and table rows are
  data-bound, get no path, and therefore cannot be retyped on the canvas;
* a path resolves against a props mapping in exactly one way.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional, Tuple, Union

# Leaf prop names that hold prose a user authors rather than a number we derive.
EDITABLE_LEAVES = frozenset(
    {
        "action",
        "body",
        "due",
        "eyebrow",
        "heading",
        "label",
        "owner",
        "subtitle",
        "task",
        "text",
        "title",
    }
)

# Props that hold a list of entries whose fields are individually editable.
ITEM_LISTS = frozenset({"items", "points", "tasks"})

ScalarPath = Tuple[str]
ItemPath = Tuple[str, int, str]
TextPath = Union[ScalarPath, ItemPath]

_EMPTY_POINT = {"label": "", "text": "", "tone": "neutral"}


def path_for(leaf: str) -> str:
    """The path naming a top-level prop, e.g. ``"title"``."""
    return leaf


def item_path(container: str, index: int, leaf: str) -> str:
    """The path naming one field of one list entry, e.g. ``"points.2.text"``."""
    return f"{container}.{index}.{leaf}"


def parse_path(path: Any) -> Optional[TextPath]:
    """``"points.0.text"`` → ``("points", 0, "text")``; anything else → ``None``."""
    parts = str(path or "").split(".")
    if len(parts) == 1:
        return (parts[0],) if parts[0] in EDITABLE_LEAVES else None
    if len(parts) != 3:
        return None
    container, index, leaf = parts
    if container not in ITEM_LISTS or leaf not in EDITABLE_LEAVES:
        return None
    if not index.isdigit():
        return None
    return (container, int(index), leaf)


def is_commentary_text(path: TextPath) -> bool:
    """True for the body of a commentary bullet — the one leaf that may be blanked away."""
    return len(path) == 3 and path[0] == "points" and path[2] == "text"


def apply_text(props: Mapping[str, Any], path: TextPath, value: Any) -> Dict[str, Any]:
    """Return ``props`` with the leaf at ``path`` replaced by ``value``.

    Emptying a commentary bullet deletes it — that is how a bullet is removed
    without leaving the canvas.
    """
    out = copy.deepcopy(dict(props))
    text = " ".join(str(value or "").split())
    if len(path) == 1:
        out[path[0]] = text
        return out
    container, index, leaf = path
    items = [dict(item) for item in (out.get(container) or []) if isinstance(item, Mapping)]
    if not 0 <= index < len(items):
        return out
    if is_commentary_text(path) and not text:
        del items[index]
    else:
        items[index][leaf] = text
    out[container] = items
    return out


def add_point(props: Mapping[str, Any], after_index: int) -> Dict[str, Any]:
    """Return ``props`` with an empty commentary bullet inserted after ``after_index``."""
    out = copy.deepcopy(dict(props))
    points = [dict(p) for p in (out.get("points") or []) if isinstance(p, Mapping)]
    at = max(0, min(len(points), after_index + 1))
    points.insert(at, dict(_EMPTY_POINT))
    out["points"] = points
    return out
