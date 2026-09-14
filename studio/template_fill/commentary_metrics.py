"""Descriptive prose telemetry and a per-bullet clarity check.

Opening variety, causal words and implications are diagnostics, not quality targets.
Clear observations may repeat carrier names and need no invented cause or consequence.
The clarity check flags ambiguous comparisons and overlong bullets for repair; numerical
and semantic verification determine whether the finding is supported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)


# A bullet short enough to be a heading ("Key Highlights:") is not a claim and is not scored.
_MIN_CLAIM_WORDS = 6

# Why something moved: a driver, an attribution, a mechanism.
_CAUSAL = re.compile(
    r"\b(?:because|driven by|led by|came from|carried by|won on|off the back of|"
    r"following|after|on renewal|at renewal|out of a total|which offset|so the gain|"
    r"rather than|thanks to|down to|the result of|as .{0,30}(?:grew|fell|rose|slipped))\b",
    re.I,
)

# What follows for this account: a consequence, a call, an ask.
_IMPLICATION = re.compile(
    r"\b(?:so |which leaves|which means|means |the ask|the question is|what to|worth about|"
    r"is the lever|to protect|the priority|would add|would still|needs to|must |should |"
    r"leaves .{0,30}(?:behind|ahead)|is not yet|not winning it|on the table)\b",
    re.I,
)

# A measure-and-a-value with nothing round it: the metric read-out.
_MEASURE_OPENER = re.compile(
    r"^\s*(?:rank|share of wallet|share|premium|gwp|total|momentum|growth)\b", re.I)
_NUMBER = re.compile(r"\d")


@dataclass(frozen=True)
class CommentaryScore:
    """One deck's prose, measured. Rates are 0.0-1.0 over scored bullets."""

    bullets: int
    subject_opening_rate: float
    opening_variety: float
    causal_rate: float
    implication_rate: float
    restatement_rate: float
    repeated_bullets: int

    def as_row(self) -> str:
        """One log line — the shape a run-to-run comparison is read from."""
        return (f"bullets={self.bullets} "
                f"subject_openings={self.subject_opening_rate:.0%} "
                f"opening_variety={self.opening_variety:.0%} "
                f"causal={self.causal_rate:.0%} "
                f"implication={self.implication_rate:.0%} "
                f"restatement={self.restatement_rate:.0%} "
                f"repeats={self.repeated_bullets}")


def commentary_bullets(values: Mapping[str, object]) -> List[str]:
    """Every prose bullet in a fill payload — the ``note:``/``fbnote:`` roles, split by line."""
    out: List[str] = []
    for role, value in values.items():
        if not (isinstance(role, str) and isinstance(value, str)):
            continue
        if not (role.startswith("note:") or role.startswith("fbnote:")):
            continue
        out += [line.strip() for line in value.split("\n") if line.strip()]
    return out


def _scored(bullets: Sequence[str]) -> List[str]:
    """The bullets worth scoring — headings and labels are neither good nor bad prose."""
    return [b for b in bullets if len(b.split()) >= _MIN_CLAIM_WORDS]


def _opening(bullet: str) -> str:
    """A bullet's opening, normalised to its first three words."""
    words = re.sub(r"[^\w\s]", "", bullet.lower()).split()
    return " ".join(words[:3])


def is_restatement(bullet: str) -> bool:
    """A measure, a value, and nothing the reader could not read off the chart beside it.

    Opening on a measure is not by itself the problem — "Momentum sits with Cyber, so the
    renewal book there is what to protect first" opens on one and earns its place. What
    makes a bullet a read-out is opening on a measure and then saying neither why it moved
    nor what follows. ``commentary._accept`` refuses a REWRITE containing one; a gate on
    the opening alone threw away good rewrites and sent the page back to the draft.
    """
    if not _NUMBER.search(bullet):
        return False
    if _CAUSAL.search(bullet) or _IMPLICATION.search(bullet):
        return False
    return bool(_MEASURE_OPENER.match(bullet))


#: A themed lead-in: a short label naming what the bullet is about, then the finding.
#: Bounded to the first 40 characters so a colon deeper inside a sentence is ordinary
#: punctuation and not read as a label.
_LEAD_IN = re.compile(r"^(?P<label>[^:.!?]{1,40}):\s+(?P<rest>\S.*)$", re.S)

#: How many words a lead-in LABEL may carry. Four covers "Manufacturing growth",
#: "Renewable Energy" and "Share of wallet"; beyond that it is a clause, and a clause
#: before a colon is a sentence that happens to contain one.
_MAX_LABEL_WORDS = 4

#: Words that are never the NAME of anything — they are the column's own heading, and a
#: bullet labelled with the heading it already sits under has spent a line saying where it
#: is. Caught here rather than left to the judge because it needs no evidence to see.
_HEADING_WORDS = frozenset({
    "challenge", "challenges", "opportunity", "opportunities", "success", "successes",
    "strength", "strengths", "weakness", "weaknesses", "threat", "threats",
    "priority", "priorities", "key message", "key messages", "message", "messages",
    "performance", "growth", "reflection", "reflections", "summary", "overall",
    "highlight", "highlights", "thesis", "observation", "recommendation",
})


def lead_in_issue(bullet: str):
    """Why this bullet's ``Theme: finding`` lead-in is malformed, or ``None``.

    The lead-in is allowed because it is genuinely easier to read: a reader scanning a
    column sees what each bullet is ABOUT before reading it. The failure mode it has to be
    kept away from is the one the old flat ban on colons existed for — "Momentum: Cyber
    +97%", a label followed by a chart caption rather than a sentence. So the shape is
    permitted and policed: a short label, then a whole sentence that could stand without it.

    Returns ``None`` for a bullet with no lead-in at all, which is most of them.
    """
    match = _LEAD_IN.match(bullet.strip())
    if not match:
        return None
    label = match.group("label").strip()
    rest = match.group("rest").strip()
    if len(label.split()) > _MAX_LABEL_WORDS:
        return None                     # a sentence containing a colon, not a lead-in
    if label.strip().lower() in _HEADING_WORDS:
        return (f"{label!r} is the column's heading, not the name of anything — label the "
                "industry, segment or product the bullet is about, or drop the label")
    if not label[:1].isupper():
        return "Capitalise the lead-in label before the colon"
    if not rest[:1].isupper():
        return "Start a full sentence after the lead-in colon"
    if not rest.endswith((".", "!", "?")):
        return ("Follow the lead-in with a complete sentence, not a caption "
                f"({rest[:40]!r})")
    if len(rest.split()) < 6:
        return ("The lead-in label is not the finding; the sentence after it must carry "
                "the point on its own")
    return None


def lead_in_label(bullet: str) -> str:
    """The lead-in label of a ``Theme: finding`` bullet, or ``""`` when it has none.

    The renderer emboldens exactly this span (:func:`fill._embolden_lead_in`), so the two
    must agree on where the label ends — which is why it is read off here rather than
    re-parsed there.
    """
    match = _LEAD_IN.match(bullet.strip())
    if not match or lead_in_issue(bullet) is not None:
        return ""
    label = match.group("label").strip()
    return label if len(label.split()) <= _MAX_LABEL_WORDS else ""


def clarity_issue(bullet: str):
    """Concrete ambiguity checks, not a preference for particular sentence openings.

    Meaning and section relevance are also checked by the evidence-aware reviewer.
    These cheap checks catch the recurrent unreadable patterns before that call.
    """
    ambiguous = re.search(
        r"\b(?:placement base|Marsh flow|pressure sat|Marsh demand|annual run rate|"
        r"year.end pace|the same book|the client segment that)\b|"
        r"\bof a\s+\$[\d.,]+[KMB]?\s+pool\b", bullet, re.I)
    if ambiguous:
        return f"Name the entity and exact metric instead of {ambiguous.group(0)!r}"
    if len(bullet.split()) > 60:
        return "Keep one finding in at most two short sentences; move supporting figures to the chart"
    if len(re.split(r"(?<=[.!?])\s+", bullet.strip())) > 2:
        return "Too many sentences for one finding"
    return None


def _rate(hits: int, total: int) -> float:
    return (hits / total) if total else 0.0


def score(values: Mapping[str, object], *, subject: str = "") -> CommentaryScore:
    """Measure the commentary in one fill payload (or a whole deck's merged payloads)."""
    from studio.template_fill.openings import subject_openings

    bullets = _scored(commentary_bullets(values))
    total = len(bullets)
    openings = {_opening(b) for b in bullets}
    seen: Dict[str, int] = {}
    for bullet in bullets:
        key = " ".join(bullet.lower().split()).rstrip(".")
        seen[key] = seen.get(key, 0) + 1
    return CommentaryScore(
        bullets=total,
        subject_opening_rate=_rate(subject_openings(bullets, subject) if subject else 0, total),
        opening_variety=_rate(len(openings), total),
        causal_rate=_rate(sum(1 for b in bullets if _CAUSAL.search(b)), total),
        implication_rate=_rate(sum(1 for b in bullets if _IMPLICATION.search(b)), total),
        restatement_rate=_rate(sum(1 for b in bullets if is_restatement(b)), total),
        repeated_bullets=sum(n - 1 for n in seen.values() if n > 1),
    )


def log_score(values: Mapping[str, object], *, subject: str = "", label: str = "") -> None:
    """Report a sub-deck's commentary score at assembly — one line, never fatal."""
    measured = score(values, subject=subject)
    if measured.bullets:
        logger.info("commentary_metrics%s: %s",
                    f" [{label}]" if label else "", measured.as_row())


def compare(before: CommentaryScore, after: CommentaryScore) -> List[Tuple[str, float, float]]:
    """``[(metric, before, after)]`` for every rate — what a change is judged on."""
    fields = ("subject_opening_rate", "opening_variety", "causal_rate",
              "implication_rate", "restatement_rate")
    return [(f, getattr(before, f), getattr(after, f)) for f in fields]
