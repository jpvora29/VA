"""The line-of-business icon on a product feedback page — kept only where it is true.

The product template is authored once, as "Marine Feedback", with a ship drawn in the
chevron beside the KPI band. Every product sub-deck is built from that page and renamed
("Casualty Feedback"), but the drawing cannot be renamed: a Casualty page shipped a ship.
There is no icon for the other lines in the templates, so the honest fill is to take the
authored icon off any page about a different line (the chevron it sat in stays).

Geometry decides which shape is the icon — never a slide index or a shape id: an empty
shape left of the band's brace, level with it, and drawn INSIDE another shape (the
chevron). Pure over the analysed template; the drop goes through the shared
``drop_shapes`` payload.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from studio.template_fill.analyze import Shape, Slide, Template

_PRODUCT_COL = "Product_Line"
_FEEDBACK_TITLE = re.compile(r"^\s*(?P<product>.+?)\s+Feedback\s*$", re.I)


def _pinned_product(result) -> Optional[str]:
    value = (getattr(result, "resolved_filters", None) or {}).get(_PRODUCT_COL)
    if isinstance(value, (list, tuple, set)):
        value = next(iter(value)) if len(value) == 1 else None
    return str(value).strip() if value else None


def _authored_product(slide: Slide) -> Optional[str]:
    """The line of business a feedback page was drawn for ("Marine" in "Marine Feedback")."""
    for sh in slide.shapes:
        m = _FEEDBACK_TITLE.match(sh.text or "") if sh.kind == "text" else None
        if m:
            return m.group("product")
    return None


def _inside(inner: Shape, outer: Shape) -> bool:
    return (outer.x <= inner.x and outer.y <= inner.y
            and inner.x + inner.w <= outer.x + outer.w
            and inner.y + inner.h <= outer.y + outer.h)


def _level(a: Shape, b: Shape) -> bool:
    return min(a.y + a.h, b.y + b.h) > max(a.y, b.y)


def icon_ids(slide: Slide) -> List[int]:
    """The empty shapes drawn inside another shape, left of and level with the brace."""
    brace = next((sh for sh in slide.shapes if "brace" in (sh.name or "").lower()), None)
    if brace is None:
        return []
    empty = [sh for sh in slide.shapes
             if sh is not brace and sh.kind in ("text", "other", "picture")
             and not (sh.text or "").strip()
             and sh.x + sh.w <= brace.x + brace.w / 2 and _level(sh, brace)]
    return [sh.shape_id for sh in empty
            if any(other is not sh and _inside(sh, other) for other in slide.shapes)]


def values(template: Template, result) -> Dict[str, Any]:
    """``{"drop_shapes": [...]}`` for every feedback page drawn for another line."""
    product = _pinned_product(result)
    if not product:
        return {}
    drop: List[str] = []
    for slide in template.slides:
        authored = _authored_product(slide)
        if authored and authored.casefold() != product.casefold():
            drop += [f"{slide.index}:{sid}" for sid in icon_ids(slide)]
    return {"drop_shapes": drop} if drop else {}
