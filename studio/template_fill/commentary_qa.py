"""Commentary QA — deterministic checks over the prose a deck is about to ship.

The claim ledger (:mod:`studio.template_fill.ledger`) prevents repetition by construction,
and the polish verifier (:func:`studio.template_fill.commentary._accept`) refuses a rewrite
that reads as generated. This module is the layer that CHECKS the finished text — the
safety net for anything either of those missed, and the home for the senior-commentary
rules that are about judgement rather than faithfulness.

It **reports and never rewrites**. Every rule here is a matter of degree — an adjective
that wants a benchmark, a page that ran long — and a rule of that kind must not be allowed
to delete a sentence: dropping is how a slide ends up blank, which is the failure
:mod:`studio.template_fill.feedback`'s fallbacks exist to prevent. Issues are logged at
assembly and returned for a caller that wants to show them.

Each rule is a pure function over one cell's text, dispatched from :data:`_RULES`, so a new
rule is a new function rather than an edit to the walker.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CommentaryIssue:
    """One thing worth a second look, and where it was found."""

    code: str
    message: str
    where: Tuple[str, ...] = ()


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# A claim, as opposed to a label, a KPI callout or a column heading.
_MIN_CLAIM_WORDS = 8


def sentences(text: str) -> List[str]:
    """The whole sentences in a commentary cell, one per bullet line."""
    out: List[str] = []
    for line in (text or "").split("\n"):
        out += [s.strip() for s in _SENTENCE_RE.split(line.strip()) if s.strip()]
    return out


def _claims(text: str) -> List[str]:
    return [s for s in sentences(text) if len(s.split()) >= _MIN_CLAIM_WORDS]


# ── per-cell rules ───────────────────────────────────────────────────────────
# Each returns a message when the text trips it, else None.

# Rank in this deck is a position inside the MARSH BOOK, not inside the open market: the
# data behind it is Marsh-placed premium only. "Market rank" and "#5 in the market" both
# claim more than the figures can support (the plan's terminology-precision point).
_MARKET_CLAIM = re.compile(r"\bmarket (?:rank|lead(?:er|ership)?|position)\b|\bin the market\b",
                           re.I)

# "Addressable" asserts the carrier COULD write it — appetite, capacity, access. Premium
# data shows only that someone else did. Whitespace is observed, not qualified.
_ADDRESSABLE = re.compile(r"\baddressable\b", re.I)
_ADDRESSABILITY_EVIDENCE = re.compile(r"\bappetite\b|\bcapacity\b|\bvalidat", re.I)

# An adjective of quality needs something to be good AGAINST, or it is decoration.
_UNBENCHMARKED = re.compile(r"\b(strong|healthy|robust|solid|excellent|impressive)\b", re.I)
_BENCHMARK = re.compile(r"\b(than|versus|vs\.?|against|above|below|ahead of|behind|"
                        r"peer|average|compared)\b", re.I)

# A page of commentary is read aloud. Past two sentences a BULLET stops being a takeaway.
#
# Measured per bullet, not per cell. A cell holds up to four bullets, so a whole-cell limit
# of three sentences was tripped by 62 of 64 cells on a normal deck — every cell that was
# doing its job. A rule that fires on almost everything reports nothing, and it buried the
# findings beside it. The per-bullet budget is the one ``rules.yaml`` already states
# (``commentary.max_sentences_per_bullet``), so the two no longer disagree.
_MAX_SENTENCES = 2
_MAX_WORDS = 60


def _overstates_the_market(text: str) -> Optional[str]:
    hit = _MARKET_CLAIM.search(text)
    return (f"{hit.group(0)!r} — rank here is a position within the Marsh book, not the "
            f"open market") if hit else None


def _claims_addressability(text: str) -> Optional[str]:
    if _ADDRESSABLE.search(text) and not _ADDRESSABILITY_EVIDENCE.search(text):
        return ("'addressable' without appetite, capacity or validation evidence — premium "
                "placed elsewhere is observed whitespace, not a qualified opportunity")
    return None


def _unbenchmarked_adjective(text: str) -> Optional[str]:
    for sentence in sentences(text):
        hit = _UNBENCHMARKED.search(sentence)
        if hit and not _BENCHMARK.search(sentence):
            return f"{hit.group(0)!r} with nothing to measure it against"
    return None


def _runs_long(text: str) -> Optional[str]:
    """The longest BULLET in the cell, against the per-bullet budget."""
    for bullet in (line.strip() for line in (text or "").split("\n") if line.strip()):
        said = sentences(bullet)
        words = len(bullet.split())
        if len(said) > _MAX_SENTENCES or words > _MAX_WORDS:
            return f"{len(said)} sentences / {words} words on one bullet"
    return None


_RULES: Dict[str, Callable[[str], Optional[str]]] = {
    "market_overstated": _overstates_the_market,
    "unevidenced_addressable": _claims_addressability,
    "unbenchmarked_adjective": _unbenchmarked_adjective,
    "cell_runs_long": _runs_long,
}


# ── deck-level rule ──────────────────────────────────────────────────────────


def _repeated_claims(cells: Mapping[str, str]) -> List[CommentaryIssue]:
    """Claims appearing in more than one cell — the ledger's safety net.

    The ledger works on the deterministic draft; this sees the finished text, so it also
    catches a repeat introduced after it (two cells polished into the same sentence).
    """
    seen: Dict[str, List[str]] = defaultdict(list)
    for role, text in cells.items():
        for claim in _claims(text):
            seen[" ".join(claim.lower().split()).rstrip(".")].append(role)
    return [
        CommentaryIssue("repeated_claim",
                        f"said in {len(roles)} places: {claim[:70]!r}", tuple(sorted(roles)))
        for claim, roles in sorted(seen.items()) if len(roles) > 1
    ]


# ── the walker ───────────────────────────────────────────────────────────────


def _commentary_cells(values: Mapping[str, object]) -> Dict[str, str]:
    """The prose entries of a fill payload — the ``fbnote:``/``note:`` roles, as text."""
    return {
        role: value for role, value in values.items()
        if isinstance(role, str) and isinstance(value, str) and value.strip()
        and (role.startswith("fbnote:") or role.startswith("note:"))
    }


def check(values: Mapping[str, object]) -> List[CommentaryIssue]:
    """Every issue in a sub-deck's fill payload, deck-level rules first."""
    cells = _commentary_cells(values)
    if not cells:
        return []
    issues = _repeated_claims(cells)
    for role, text in sorted(cells.items()):
        for code, rule in _RULES.items():
            message = rule(text)
            if message:
                issues.append(CommentaryIssue(code, message, (role,)))
    return issues


def log_issues(issues: Iterable[CommentaryIssue], *, label: str = "") -> None:
    """Report the issues at assembly — one line each, never fatal."""
    for issue in issues:
        logger.info("commentary_qa%s: %s — %s %s",
                    f" [{label}]" if label else "", issue.code, issue.message,
                    list(issue.where))


# ── the narrative contract ───────────────────────────────────────────────────


def check_narratives(narratives: Iterable[object]) -> List[CommentaryIssue]:
    """Contract issues across a deck's :class:`~studio.narrative.SlideNarrative` set.

    Two kinds. Per narrative, whatever :meth:`SlideNarrative.gaps` reports — a missing
    action, a recommendation that opens on no agreed verb, an unvalidated claim that names
    no open question. Across them, two slides doing the SAME job, which is the structural
    form of the repetition the ledger catches at sentence level: a deck with two
    "performance assessment" pages will say the same thing twice however the words differ.
    """
    issues: List[CommentaryIssue] = []
    roles: Dict[str, List[str]] = defaultdict(list)
    present = [n for n in narratives if n is not None]
    # Traceability is only asked of a deck whose producer HAS fact ids. The template-fill
    # composers ground claims in figures with no id registry behind them, so demanding ids
    # there reports every page; the pipeline engine cites an EvidencePack, so the check
    # turns itself on for that deck — and for the other the day it grows one.
    traceable = any(getattr(n, "evidence_fact_ids", ()) for n in present)
    for narrative in present:
        role = str(getattr(narrative, "slide_role", "") or "?")
        claim = str(getattr(narrative, "primary_claim", "") or "")
        roles[role].append(claim[:40])
        for gap in getattr(narrative, "gaps", lambda: ())():
            issues.append(CommentaryIssue(
                f"narrative_missing_{gap}",
                f"{role!r} carries no {gap.replace('_', ' ')}", (role,)))
        if traceable and not getattr(narrative, "evidence_fact_ids", ()):
            issues.append(CommentaryIssue(
                "narrative_untraceable",
                f"{role!r} cites no fact ids on a deck whose other pages do", (role,)))
    issues += [
        CommentaryIssue("duplicate_slide_role",
                        f"{len(claims)} slides both do the job {role!r}", (role,))
        for role, claims in sorted(roles.items()) if len(claims) > 1
    ]
    return issues
