"""Diagnose every slot in a filled TemplateDoc: filled, unmapped, or blank and why.

Reads the same materialized fields the on-screen preview and the fill engine consume
(:func:`studio.template_fill.model.materialize_fields`), so the report can never
disagree with the deck it describes.

Two questions, answered separately because they have different fixes:

  * a slot with NO role — the template says nothing about which figure belongs in the
    box, so nothing was even attempted. The fix is a label in the template or a manual
    map on the Canvas.
  * a slot WITH a role that did not fill — the figure is known and the data could not
    produce it. The fix is in the selection or the dataset, and which one is what
    :mod:`studio.review.capability` works out.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from studio.review import causes as K
from studio.review.capability import cause_for_role
from studio.review.model import Capability, SlotFinding
from studio.template_fill.slots import classify

#: Commentary boxes are diagnosed on their own terms (:mod:`studio.review.commentary`) —
#: "this column has no prose" is a different finding from "this cell has no number".
_COMMENTARY_PREFIX = "note:"


def diagnose_slots(
    fields: Mapping[str, Mapping[str, Any]],
    doc: Mapping[str, Any],
    capabilities: Tuple[Capability, ...],
) -> List[SlotFinding]:
    """One finding per slot that will NOT carry this deck's data, with its cause.

    Hidden slides are skipped: a page the deck does not ship cannot be a reason to hold
    it back, and listing its blanks buried the ones on pages that do ship.
    """
    hidden = {int(i) for i in (doc.get("hidden") or [])}
    overrides = doc.get("overrides") or {}
    values = doc.get("values") or {}
    contexts = slot_context(doc)
    out: List[SlotFinding] = []
    for key, fld in fields.items():
        if int(fld.get("slide_idx", 0)) in hidden:
            continue
        role = fld.get("role")
        if str(role or "").startswith(_COMMENTARY_PREFIX):
            continue
        cause_id = _cause_for(fld, key in overrides, values, capabilities)
        if cause_id:
            out.append(_finding(key, fld, cause_id, contexts.get(key, "")))
    return out


def _cause_for(
    fld: Mapping[str, Any],
    overridden: bool,
    values: Mapping[str, Any],
    capabilities: Tuple[Capability, ...],
) -> str:
    """The cause id for one field, or ``""`` when it is genuinely fine.

    Ordered by what the author needs to act on first: an edit that emptied a good value
    and a placeholder that survived a fill are bugs in the deck they are holding; an
    unresolved figure is a fact about the data.
    """
    role = fld.get("role")
    if role and overridden and not str(fld.get("text") or "").strip():
        return K.BLANKED
    if _empty_series(fld, values):
        return K.NO_CHART_SERIES
    if fld.get("filled"):
        return K.STALE if classify(str(fld.get("text") or "")) is not None else ""
    if role:
        return cause_for_role(str(role), capabilities)
    return _unmapped_cause(fld)


def _empty_series(fld: Mapping[str, Any], values: Mapping[str, Any]) -> bool:
    """A chart slot whose payload resolved but carries no points.

    Checked BEFORE ``filled``, because such a slot IS filled as far as the renderer is
    concerned — a payload exists — and would otherwise be counted as a value this deck
    carries when the chart on the page still shows the template's authored numbers.
    """
    if fld.get("value_kind") != "series":
        return False
    payload = values.get(str(fld.get("role") or ""))
    if not isinstance(payload, dict):
        return False
    points = payload.get("points")
    return isinstance(points, list) and not points


def _unmapped_cause(fld: Mapping[str, Any]) -> str:
    """Why no role was inferred — split by what the mapper would have had to read.

    The three kinds fail for different reasons and take different fixes, which is the
    whole reason they are not one "unmapped" bucket.
    """
    kind = str(fld.get("value_kind") or "text")
    if kind == "series":
        return K.UNMAPPED_CHART
    if kind == "text":
        return K.UNMAPPED_TEXT
    return K.UNMAPPED_FIGURE


def _finding(key: str, fld: Mapping[str, Any], cause_id: str, context: str) -> SlotFinding:
    return SlotFinding(
        slot_key=key,
        slide_no=int(fld.get("slide_idx", 0)) + 1,
        role=fld.get("role"),
        token=str(fld.get("token") or ""),
        context=_trim(context),
        value_kind=str(fld.get("value_kind") or "text"),
        cause_id=cause_id,
    )


def _trim(text: str, limit: int = 90) -> str:
    """The slot's surrounding words, short enough to sit on one line of the report."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def slot_context(doc: Mapping[str, Any]) -> Dict[str, str]:
    """``slot_key -> context`` from the manifest.

    ``materialize_fields`` folds the manifest down to what the RENDERER needs and drops
    the slot's context on the way. The report wants it back: "nothing near this box says
    which figure it wants" is only useful next to the words that were actually there.
    """
    out: Dict[str, str] = {}
    for item in doc.get("manifest") or []:
        slot = (item or {}).get("slot") or {}
        where = "-".join(str(p) for p in (slot.get("where") or []))
        key = f"{slot.get('slide_idx')}:{slot.get('shape_id')}:{where}"
        out[key] = str(slot.get("context") or "")
    return out


__all__ = ["diagnose_slots", "slot_context"]
