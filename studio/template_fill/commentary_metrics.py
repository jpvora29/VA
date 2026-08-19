"""Score a deck's commentary on the things that separate a written page from a produced one.

:mod:`studio.template_fill.commentary_qa` asks "is anything WRONG with this text" — an
unbenchmarked adjective, a claim the data can't carry, the same sentence on two slides. This
module asks the different question: "does it READ like a partner wrote it". Both are
report-only; neither ever edits the prose.

It exists because "the commentary is better now" is otherwise unfalsifiable, and this
codebase has already lost two commentary changes to that (see the reverted per-slide cache
and the spare-candidate experiment). Every rule here is a proportion over the deck's own
bullets, so two runs are directly comparable and a regression is visible as a number rather
than as a feeling.

The five that matter, and why:

* ``subject_opening_rate`` — bullets that open on the carrier's name. The roll-call
  ("Zurich wrote …", "Zurich ranks …") is the single loudest generated-text tell.
* ``opening_variety`` — distinct sentence openings over bullets. Catches the roll-call's
  quieter cousin, where every line opens the same way without naming anybody.
* ``causal_rate`` — bullets that say WHY something moved. A consultant's page is mostly
  mechanism; a generated one is mostly measurement.
* ``implication_rate`` — bullets that say what follows for this account. The "so what".
* ``restatement_rate`` — bullets that are a measure and a value and nothing else. The
  metric read-out, stated as a proportion so it can be driven down deliberately.

Deliberately regex-based and local: a judge model would score the deck it just wrote, which
is how you measure your own prompt rather than your own prose.
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
