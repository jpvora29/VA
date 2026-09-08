"""Diagnose the ASSEMBLED deck — the merged file the author is about to send.

The two documents Studio holds are not the same thing, and Review has to read them
differently.

The editable template doc is a *plan*: a manifest of every slot with the value each one
resolved to, so "how much of this template carries our data" is a meaningful percentage.

The assembled deck is the *outcome*: overall plus a sub-deck per product and per country,
already written into one ``.pptx``. Nothing in it is a plan any more — so the question
changes from "how much filled" to the one that actually matters at the point of sending:
**what is still a placeholder in the file itself.** Slot detection run over the delivered
deck answers exactly that, because a slot is only detected where a placeholder token
survived (:mod:`studio.template_fill.slots`). Anything that filled is a number now and is
not a slot at all.

So every finding here is by construction unfilled, and the causes come from the same
capability probe as everywhere else — the run's data is the run's data, whichever
document is describing it.
"""
from __future__ import annotations

import re
from typing import Any, List, Mapping, Tuple

from studio.review import causes as K
from studio.review.capability import cause_for_role
from studio.review.model import Capability, CommentaryFinding, SlotFinding

#: A prose box that still shows its "fill me" mark. In the delivered deck this is the
#: most dangerous thing on the page: the commentary writer replaces a box wholesale, so
#: one left like this is shipping the template's example narrative about another carrier.
_ELLIPSIS = re.compile(r"(?:…+|\.{3,})")


def is_assembled(doc: Mapping[str, Any]) -> bool:
    """Whether ``doc`` is the merged deliverable rather than the editable plan."""
    return bool((doc or {}).get("assembled"))


def diagnose_assembled(
    doc: Mapping[str, Any], capabilities: Tuple[Capability, ...]
) -> List[SlotFinding]:
    """Every placeholder that SURVIVED the fill, with the reason it did."""
    out: List[SlotFinding] = []
    for slot in _slots(doc):
        if _is_prose(slot):
            continue                       # reported as commentary, not as a blank figure
        if _chart_that_says_nothing(slot, capabilities):
            continue
        out.append(SlotFinding(
            slot_key=_key(slot),
            slide_no=int(slot.get("slide_idx", 0)) + 1,
            role=slot.get("role"),
            token=str(slot.get("token") or ""),
            context=_trim(str(slot.get("context") or "")),
            value_kind=str(slot.get("value_kind") or "text"),
            cause_id=_cause(slot, capabilities),
        ))
    return out


def assembled_commentary(doc: Mapping[str, Any]) -> List[CommentaryFinding]:
    """The prose boxes still showing their "fill me" mark in the delivered deck.

    Only the unwritten ones can be seen from here — a box the writer filled is ordinary
    text in the file and indistinguishable from the template's own copy. That is the
    right way round: the count is a floor on what is wrong, never a claim about what is
    right.
    """
    return [
        CommentaryFinding(slot_key=_key(slot), slide_no=int(slot.get("slide_idx", 0)) + 1,
                          lines=0, filled=False, cause_id=K.COMMENTARY_EMPTY)
        for slot in _slots(doc) if _is_prose(slot)
    ]


def _slots(doc: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """The manifest entries on pages the deck ships, flattened to slot dicts."""
    hidden = {int(i) for i in (doc.get("hidden") or [])}
    out = []
    for item in doc.get("manifest") or []:
        slot = dict((item or {}).get("slot") or {})
        if not slot or int(slot.get("slide_idx", 0)) in hidden:
            continue
        slot["role"] = (item or {}).get("role")
        out.append(slot)
    return out


def _is_prose(slot: Mapping[str, Any]) -> bool:
    return str(slot.get("value_kind") or "") == "text" and bool(
        _ELLIPSIS.search(str(slot.get("token") or ""))
    )


def _chart_that_says_nothing(
    slot: Mapping[str, Any], capabilities: Tuple[Capability, ...]
) -> bool:
    """True for a chart whose presence in the manifest proves nothing.

    The "a placeholder survived" reasoning does not hold for charts. A text or number
    slot is detected only where a placeholder token is still there, so finding one IS
    the finding — but a chart is detected because it is a chart, filled or not, and the
    detector has no way to tell a refilled series from the template's authored one.

    So a chart is worth reporting only when the DATA behind it is missing, which the
    capability probe does know. Reporting the rest would have listed every quadrant on
    every page of a finished deck as an open item.
    """
    if str(slot.get("value_kind") or "") != "series":
        return False
    role = slot.get("role")
    return not role or cause_for_role(str(role), capabilities) == K.NO_DATA


def _cause(slot: Mapping[str, Any], capabilities: Tuple[Capability, ...]) -> str:
    role = slot.get("role")
    if role:
        return cause_for_role(str(role), capabilities)
    kind = str(slot.get("value_kind") or "text")
    if kind == "series":
        return K.UNMAPPED_CHART
    return K.UNMAPPED_TEXT if kind == "text" else K.UNMAPPED_FIGURE


def _key(slot: Mapping[str, Any]) -> str:
    where = "-".join(str(p) for p in (slot.get("where") or []))
    return f"{slot.get('slide_idx')}:{slot.get('shape_id')}:{where}"


def _trim(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


__all__ = ["is_assembled", "diagnose_assembled", "assembled_commentary"]
