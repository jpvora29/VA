"""Select citable findings for a column before asking a model to write its prose.

The evidence remains available for context, but a positive movement cannot become
the leading finding of a challenges column merely because it is a large number.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Finding:
    fact_ids: Tuple[str, ...]
    question: str
    topics: Tuple[str, ...]
    importance: float = 0.0


_GENERAL = ("thesis", "key_messages", "performance", "reflections")
_ALIASES = {"strengths": "working", "weaknesses": "challenges", "opportunities": "growth",
            "threats": "challenges"}


def catalogue(pack) -> Tuple[Finding, ...]:
    out = []

    def add(ids, question, topics, importance=0):
        present = tuple(fid for fid in ids if pack.get(fid) is not None)
        if present:
            out.append(Finding(present, question, tuple(topics), importance))

    yoy = pack.get("carrier.yoy")
    if yoy and yoy.value is not None:
        side = "working" if yoy.value > 0 else "challenges" if yoy.value < 0 else "performance"
        add(("carrier.yoy", "carrier.delta", "carrier.premium", "carrier.prior", "marsh.yoy"),
            "The carrier's premium movement, set against the Marsh book over the same period.",
            (*_GENERAL, side), 100)
    share = pack.get("sow.delta")
    if share:
        falling = "fell" in share.label.lower()
        add(("sow.delta", "sow.current", "sow.prior", "marsh.yoy", "carrier.yoy"),
            "The movement in share of Marsh placements. Keep share and premium distinct.",
            (*_GENERAL, "challenges" if falling else "working", "priorities"), 95)
    gap = pack.get("peer.gap")
    if gap:
        below = "below" in gap.label.lower()
        add(("peer.gap", "sow.current", "peer.sow", "peer.basis", "peer.gap_value"),
            "The carrier's share against the defined largest-carrier average. "
            "Any premium equivalent is a constant-denominator scenario, not winnable premium.",
            (*_GENERAL, "challenges" if below else "working", *(('growth', 'priorities') if below else ())), 80)
    for item in pack.items:
        fid = item.fact_id
        if fid.startswith("mover.") and item.unit == "currency_change":
            name = fid[len("mover."):]
            side = "working" if (item.value or 0) > 0 else "challenges"
            add((fid, fid + ".current", fid + ".prior", "pool." + name),
                f"Material premium movement in {item.entity or name}. Name it and distinguish carrier from Marsh.",
                (*_GENERAL, side, "priorities"), abs(item.value or 0))
        elif fid.startswith("segment.") and len(fid.split(".")) == 4:
            kind = fid.split(".")[2]
            topics = {"losing": ("challenges", "priorities"),
                      "strong": ("working",), "absent": ("growth", "priorities"),
                      "thin": ("growth", "challenges", "priorities"),
                      "behind": ("growth", "challenges", "priorities")}.get(kind)
            if topics:
                details = tuple(e.fact_id for e in pack.items if e.fact_id.startswith(fid + "."))
                add((fid, *details), "Explain this named segment's observed placement position. "
                    "Use the current/prior or benchmark comparison that matters; do not recite every figure. "
                    "Do not claim an operational cause or an achievable premium target.",
                    (*_GENERAL, *topics), abs(item.value or 0))
    quarter = pack.get("trend.quarter")
    if quarter:
        side = "working" if (quarter.value or 0) > 0 else "challenges" if (quarter.value or 0) < 0 else "performance"
        add(("trend.quarter", "trend.quarter_yoy", "trend.comparison_note"),
            "The latest comparable quarter against the SAME quarter last year. "
            "This is an observation, not a trend or annual run rate.", (*_GENERAL, side), 60)
    if pack.get("mix.concentration"):
        add(("mix.concentration",), "Describe material concentration without asserting future losses.", _GENERAL, 40)
    if pack.get("rank.current"):
        add(("rank.current", "rank.delta"), "State the carrier's position within Marsh placements with the field size.", _GENERAL, 20)
    if not out and pack.get("carrier.premium"):
        add(("carrier.premium", "carrier.prior"), "State the available premium position without inventing a comparison.", _GENERAL, 10)
    return tuple(out)


def for_topic(pack, topic: str, limit: int = 5) -> Tuple[Finding, ...]:
    if topic == "threats":
        # Observed declines are not forward-looking evidence by themselves.
        return ()
    resolved = _ALIASES.get(topic, topic)
    candidates = [f for f in catalogue(pack) if resolved in f.topics]
    # Start with the overall comparison on summary pages; segment pages prioritize
    # the monetary contribution. Both orderings remain stable across identical runs.
    if resolved in ("thesis", "key_messages"):
        return tuple(candidates[:limit])
    return tuple(sorted(candidates, key=lambda f: f.importance, reverse=True)[:limit])


def brief(pack, topic: str) -> str:
    findings = for_topic(pack, topic)
    if not findings:
        canonical = _ALIASES.get(topic, topic) if topic != "threats" else topic
        availability = f"assessment.{canonical}"
        return ("NO QUALIFYING FINDING was selected for this column. Do not turn a positive result "
                "into a shortfall or invent an opportunity. Write one concise statement of the "
                f"evidence limitation and cite [{availability}]. Do not claim unmeasured risks are absent."
                if pack.get(availability) else
                "No qualifying finding or availability fact: return no bullets and flag insufficient evidence.")
    # Stated as the material AVAILABLE to the column, not as a list of questions to answer.
    # Interrogatives got answered one per bullet, which is how a column of unrelated replies
    # reached the slide; the writer's job is to choose among these and build one argument.
    return ("MATERIAL AVAILABLE TO THIS SECTION — choose what carries the column's "
            "argument and leave the rest. Covering all of it is not the goal; making the "
            "strongest supported point is. Two of these often belong in one bullet:\n"
            + "\n".join(f"- Cite [{', '.join(f.fact_ids)}]: {f.question}" for f in findings))
