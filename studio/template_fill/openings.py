"""Stop a commentary column opening every bullet with the carrier's name.

The deterministic composers each open on the subject, because each one is written to stand
alone (:mod:`studio.template_fill.feedback`). Stacked into a column they read as a metric
roll-call — "Zurich wrote …", "Zurich ranks …", "Zurich grew …" — which is the single
loudest tell that a page was generated rather than written. A partner names the carrier
once and then talks about *the book*.

This is the DRAFT-side half of the fix, and it is deliberately conservative: it rewrites
only the openings it has an explicit, grammatical rule for, and leaves everything else
exactly as composed. The real variety comes from the LLM path, which is gated on the same
rule (:func:`studio.template_fill.commentary._accept`); this is what the page falls back to
when that rewrite is refused, so it has to be safe rather than clever.

One rule per shape, in :data:`_RULES`, so a new composer sentence is a new rule rather than
an edit to the walker.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

# ``(what follows the subject, what the whole opening becomes)``. The subject itself is
# spliced in per call, so a rule is written once and works for every carrier.
#
# Each replacement keeps the sentence's claim and its figures untouched — only the noun
# phrase in front changes. "The book" is the deck's own word for the subject's premium with
# Marsh, and it is already how the composers refer back to it mid-sentence.
_RULES: Tuple[Tuple[str, str], ...] = (
    # "Zurich grew its book with Marsh 12.4% year on year to $48.2m"
    (r"\s+grew its book with Marsh\s+", "The book with Marsh grew "),
    # "Zurich held its book with Marsh at $48.2m."
    (r"\s+held its book with Marsh at\s+", "The book with Marsh held at "),
    # "Zurich's book with Marsh fell 4.1% year on year to $48.2m"
    (r"(?:'s|’s)\s+book with Marsh\s+", "The book with Marsh "),
    # "Zurich ranks 4th and holds 8.9% of the wallet…" — and the same for the other
    # standing verbs the composers use. The verb is kept, so the claim is untouched.
    (r"\s+(?=(?:ranks|holds|sits|writes|took|gave)\b)", "The book "),
)


def _opens_on(line: str, subject: str) -> bool:
    """True when ``line`` starts with the carrier's name (possessive included)."""
    return bool(re.match(rf"{re.escape(subject)}(?:'s|’s)?\b", line.strip(), re.I))


def _rewrite(line: str, subject: str) -> Optional[str]:
    """``line`` with its subject opening replaced, or ``None`` when no rule fits."""
    for tail, opening in _RULES:
        match = re.match(rf"{re.escape(subject)}{tail}", line.strip(), re.I)
        if match:
            return opening + line.strip()[match.end():]
    return None


def vary_openings(points: Sequence[str], subject: str) -> List[str]:
    """``points`` with repeated carrier-name openings turned into "the book" openings.

    The FIRST bullet that names the carrier keeps it — a column has to say who it is about
    — and every later one is rewritten where a rule fits. A bullet with no rule is returned
    untouched rather than mangled: a slightly repetitive sentence beats an ungrammatical one.
    """
    subject = str(subject or "").strip()
    if not subject:
        return list(points)
    out: List[str] = []
    named = False
    for line in points:
        if not _opens_on(line or "", subject):
            out.append(line)
            continue
        if not named:                       # the column's one introduction
            named = True
            out.append(line)
            continue
        out.append(_rewrite(line, subject) or line)
    return out


def subject_openings(points: Sequence[str], subject: str) -> int:
    """How many bullets open on the carrier's name — the metric the gate reads."""
    subject = str(subject or "").strip()
    if not subject:
        return 0
    return sum(1 for line in points if _opens_on(line or "", subject))
