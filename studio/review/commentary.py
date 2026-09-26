"""Diagnose the deck's prose: which commentary boxes were written, and what they lost.

Two findings live here, and they are not the same thing.

The first is a *failure*: a prose box that got no text at all. Prose boxes are replaced
wholesale, so an unwritten one keeps whatever the template was authored with — and these
templates are authored with example commentary about a different carrier. That has to be
an error on the Review page, never a quiet blank.

The second is a *narrowing*: commentary is written from the same resolved facts the
figures come from, so a capability the data cannot support is also a claim the writing
cannot make. When there is no prior year, no column anywhere in the deck can describe
growth — not because the writer failed, but because the deck refuses to state a
comparison it cannot evidence. Saying so is the difference between "the commentary reads
thin" and "the commentary reads thin *because* the period is one year".
"""
from __future__ import annotations

from typing import Any, List, Mapping, Tuple

from studio.review import causes as K
from studio.review.model import Capability, CommentaryFinding

#: The role prefix ``studio.template_fill.commentary`` gives every prose box.
COMMENTARY_PREFIX = "note:"

#: capability id -> what the commentary can no longer say without it. Written as the
#: claim family, because that is what an author notices missing on the page.
CLAIM_FAMILIES: Mapping[str, str] = {
    "prior_year": "growth, movement and any year-on-year comparison",
    "peer_benchmark": "how the book compares with the peer average",
    "market_rank": "where the carrier places in the market, and whether it moved",
    "survey_score": "anything drawn from the broker survey",
    "spotlight": "a named country or product to lead a paragraph with",
    "country_breakdown": "where inside the scope the book actually sits",
}


def diagnose_commentary(
    fields: Mapping[str, Mapping[str, Any]], doc: Mapping[str, Any]
) -> List[CommentaryFinding]:
    """One finding per prose box on a page the deck ships."""
    hidden = {int(i) for i in (doc.get("hidden") or [])}
    out: List[CommentaryFinding] = []
    for key, fld in fields.items():
        if not str(fld.get("role") or "").startswith(COMMENTARY_PREFIX):
            continue
        if int(fld.get("slide_idx", 0)) in hidden:
            continue
        text = str(fld.get("text") or "") if fld.get("filled") else ""
        lines = len([ln for ln in text.splitlines() if ln.strip()])
        out.append(CommentaryFinding(
            slot_key=key,
            slide_no=int(fld.get("slide_idx", 0)) + 1,
            lines=lines,
            filled=bool(fld.get("filled")) and lines > 0,
            cause_id="" if lines else K.COMMENTARY_EMPTY,
        ))
    return sorted(out, key=lambda f: (f.slide_no, f.slot_key))


def lost_claim_families(capabilities: Tuple[Capability, ...]) -> Tuple[str, ...]:
    """What the commentary could not argue, given what the data does not support.

    Ordered by the probe order rather than alphabetically, so the root cause of a thin
    deck is named before its consequences.
    """
    return tuple(
        CLAIM_FAMILIES[cap.id]
        for cap in capabilities
        if not cap.available and cap.id in CLAIM_FAMILIES
    )


def field_reason(outcome: Any, lost: Tuple[str, ...] = ()) -> str:
    """Why one commentary field reads the way it does -- for the Review list.

    ``outcome`` is a ledger entry (:mod:`studio.template_fill.commentary_ledger`). An empty
    field is one of three different things, and the fix differs for each: a qualitative page
    that is written by hand, a field the data gave nothing to say about, and a field whose
    sentences the verifiers dropped rather than ship them unverified.
    """
    from studio.template_fill import commentary_ledger as L

    if outcome.status == L.EMPTY:
        if outcome.section == "feedback":
            return ("Qualitative page, written by hand from the meeting. Add the carrier's "
                    "feedback on the Canvas before sending.")
        if not outcome.had_draft:
            gap = f" This scope cannot support {lost[0]}." if lost else ""
            return ("Not written: the data gave this field nothing to say." + gap
                    + " Write it on the Canvas, or widen the scope.")
        return ("Not written: no sentence for this field could be traced to a fact, so the "
                "box ships blank rather than unverified. Write it on the Canvas.")
    if outcome.status == L.DRAFT:
        return ("Written from the standard wording, not by the model: the model was "
                "unavailable or its draft did not pass the checks.")
    return "Written from this run's facts and verified."


__all__ = ["diagnose_commentary", "lost_claim_families", "field_reason",
           "COMMENTARY_PREFIX", "CLAIM_FAMILIES"]
