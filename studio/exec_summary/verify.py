"""Deterministic claim checks on a stage answer (design Sections 13, 17, 21).

Every check is drop-only: a failing finding is removed with its reason, never rewritten
(a verifier that rewrites is a second author). The checks verify direction, unit and
scope, not only "does this number appear somewhere":

* scope        — the answer's scope_id and every cited id belong to THIS payload;
* figures      — every number is a display value of a cited fact (or the period label);
* direction    — "grew" is never written beside a negative movement, nor "fell" beside a
                 positive one;
* wording      — no causal claims, no "market" for the Marsh book, no markdown;
* disclosure   — no other carrier is named;
* invention    — no industry, segment, product or country outside the payload.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Set, Tuple

from studio.ai.verifier import allowed_numbers, verify_bullets
from studio.exec_summary.evidence import (
    UNIT_MONEY,
    UNIT_PCT_CHANGE,
    UNIT_PP,
    UNIT_SCORE,
    EvidenceStore,
)
from studio.exec_summary.payloads import StagePayload
from studio.exec_summary.schemas import VERIFIED, Finding, ModelFinding, StageOutput

MAX_WORDS = 60

_CAUSAL = re.compile(r"\b(because|due to|caused|causes|led to|leads to|resulted in|"
                     r"as a result of|driven by poor|thanks to)\b", re.I)
_MARKET = re.compile(r"\b(market share|insurance market|the market|whole market|"
                     r"overall market)\b", re.I)
_MARKDOWN = re.compile(r"(\*\*|__|^\s*[-*•#]\s|`)", re.M)
_UP = re.compile(r"\b(grew|grow|grows|growing|rose|rise|rising|increased|increase|up|gained|"
                 r"gain|expanded|improved|higher|climbed|added|lifted)\b", re.I)
_DOWN = re.compile(r"\b(fell|fall|falling|declined|decline|declining|decreased|decrease|down|"
                   r"dropped|drop|contracted|lost|shrank|lower|weakened|slipped|eased)\b", re.I)
_SIGNED_UNITS = {UNIT_PCT_CHANGE, UNIT_PP, UNIT_SCORE, UNIT_MONEY}


@dataclass(frozen=True)
class VerifiedStage:
    findings: Tuple[Finding, ...]
    errors: Tuple[str, ...]
    scope_ok: bool

    @property
    def rejected(self) -> int:
        return len(self.errors)


def _words(text: str) -> int:
    return len(text.split())


def _mentions(text: str, name: str, *, case: bool = False) -> bool:
    """Whole-word mention. ``case=True`` for proper names that are also common words
    ("Commercial" the segment vs "commercial position")."""
    flags = 0 if case else re.I
    return bool(name) and re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text, flags) is not None


def _occurrences(text: str, needle: str) -> list:
    out, at = [], text.find(needle)
    while at >= 0:
        out.append(at)
        at = text.find(needle, at + 1)
    return out


def _contradicts(text: str, at: int, item) -> str:
    """The contradiction at one position: a verb just before it pointing the wrong way."""
    window = text[max(0, at - 40):at]
    up = [m.end() for m in _UP.finditer(window)]
    down = [m.end() for m in _DOWN.finditer(window)]
    nearest_up = max(up) if up else -1
    nearest_down = max(down) if down else -1
    if item.value < 0 and nearest_up > nearest_down:
        return f"says it rose beside a negative {item.metric_id} ({item.display})"
    if (item.value > 0 and nearest_down > nearest_up and item.metric_id != "rank_movement"
            and "below" not in window and "behind" not in window):
        return f"says it fell beside a positive {item.metric_id} ({item.display})"
    return ""


def _direction_issue(text: str, store: EvidenceStore, ids: Sequence[str]) -> str:
    """A movement verb right before a signed figure that contradicts its sign.

    The figure is looked for as written ("-20.0%") and as its magnitude ("fell 20.0%"),
    which the prompt allows. A magnitude can appear more than once ("A added $0.5M while
    B lost $0.5M"), so a figure is only flagged when NO occurrence reads the right way.
    """
    for eid in ids:
        item = store.get(eid)
        if item is None or item.unit not in _SIGNED_UNITS or item.value in (None, 0):
            continue
        if item.unit == UNIT_MONEY and not item.display.startswith(("+", "-")):
            continue                     # a level, not a change
        spots = _occurrences(text, item.display) or _occurrences(text, item.display.lstrip("+-"))
        issues = [_contradicts(text, at, item) for at in spots]
        if issues and all(issues):
            return issues[0]
    return ""


def check_finding(f: ModelFinding, payload: StagePayload, store: EvidenceStore, *,
                  forbidden_names: Iterable[str], unknown_names: Iterable[str]) -> str:
    """``""`` when the finding passes every check, else the first reason it fails."""
    text = " ".join(t for t in (f.statement, f.interpretation, f.recommendation) if t)
    if f.rule_id not in payload.allowed_rules:
        return f"rule_id {f.rule_id!r} is not allowed here"
    if not f.statement.strip():
        return "empty statement"
    if not f.evidence_ids:
        return "no evidence_ids cited"
    foreign = [i for i in f.evidence_ids if i not in payload.allowed_ids]
    if foreign:
        return f"cites ids not in this input: {', '.join(foreign[:4])}"
    allowed = allowed_numbers(*store.displays(f.evidence_ids), *payload.context_text)
    for part in (f.statement, f.interpretation, f.recommendation, *f.qualifications):
        _, issues = verify_bullets([part], allowed)
        if issues:
            return f"{issues[0]} (copy figures exactly from cited display values)"
    direction = _direction_issue(f.statement, store, f.evidence_ids)
    if direction:
        return direction
    if _CAUSAL.search(text):
        return f"causal wording {_CAUSAL.search(text).group(0)!r}"
    if _MARKET.search(text):
        return f"says {_MARKET.search(text).group(0)!r} instead of 'Marsh book'"
    if _MARKDOWN.search(f.statement):
        return "markdown in statement"
    named = [n for n in forbidden_names if _mentions(text, n)]
    if named:
        return f"names another carrier ({named[0]})"
    invented = [n for n in unknown_names if _mentions(text, n, case=True)]
    if invented:
        return f"mentions {invented[0]!r}, which is not in the input"
    if _words(f.statement) > MAX_WORDS:
        return f"statement is {_words(f.statement)} words (max {MAX_WORDS})"
    return ""


def verify_stage(output: StageOutput, payload: StagePayload, store: EvidenceStore, *,
                 forbidden_names: Iterable[str] = (), universe: Iterable[str] = (),
                 finding_prefix: str = "f") -> VerifiedStage:
    """Check one stage answer; returns the surviving findings and every rejection reason."""
    if output.scope_id != payload.scope_id:
        return VerifiedStage((), (f"scope_id {output.scope_id!r} != {payload.scope_id!r}",), False)
    in_payload = payload.to_json().lower()
    unknown = [n for n in universe if n and n.lower() not in in_payload]
    forbidden = list(forbidden_names)
    kept: List[Finding] = []
    errors: List[str] = []
    for n, f in enumerate(output.findings, start=1):
        if len(kept) >= payload.max_findings:
            errors.append(f"finding {n}: more than {payload.max_findings} findings")
            continue
        reason = check_finding(f, payload, store, forbidden_names=forbidden,
                               unknown_names=unknown)
        if reason:
            errors.append(f"finding {n}: {reason}")
            continue
        kept.append(Finding(
            finding_id=f"{finding_prefix}{len(kept) + 1}", rule_id=f.rule_id,
            scope_id=payload.scope_id, severity=f.severity, statement=f.statement.strip(),
            interpretation=f.interpretation.strip(), recommendation=f.recommendation.strip(),
            evidence_ids=tuple(dict.fromkeys(f.evidence_ids)),
            qualifications=tuple(q.strip() for q in f.qualifications if q.strip()),
            validation_status=VERIFIED))
    return VerifiedStage(tuple(kept), tuple(errors), True)


def names_universe(cube) -> Set[str]:
    """Every industry, segment, product and country in the book — what a model could invent."""
    names: Set[str] = set()
    for column in ("industry", "segment", "product", "country"):
        names.update(str(v) for v in cube[column].unique() if str(v) != "Unmapped")
    return names


def other_carriers(cube, carrier: str) -> Set[str]:
    """Every carrier in the book except the focal one — never named in the output."""
    return {str(c) for c in cube["carrier"].unique() if str(c).lower() != carrier.lower()}
