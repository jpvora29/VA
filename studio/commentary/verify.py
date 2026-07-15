"""Commentary verifier — deterministic sentence/fact/rule validation (Phase 5).

Every drafted sentence must survive these pure checks or be dropped:

  * cites at least one fact id, and every cited id exists in the EvidencePack
    AND was allowed by the slide's plan (materiality suppression is enforced
    here as well as at planning time);
  * every numeric token already appears in a cited fact's rendered value (or is
    a period year) — the LLM never introduces a number;
  * causal wording ("drove", "because", …) requires a decomposition fact;
  * a YoY citation must be accompanied by current AND prior premium facts;
  * unusually high growth must also cite the absolute movement;
  * YoY commentary on a book below the suppression floor is dropped;
  * no named peer may appear in carrier-facing output.

Issues are returned (never raised) so QA can group them; surviving sentences are
capped by the slide's contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Set, Tuple

from studio.ai.verifier import allowed_numbers, _norm, _TOKEN_RE  # reuse the proven tokenizer
from studio.commentary.planner import SlideCommentaryPlan
from studio.content.evidence_pack import EvidencePack
from studio.content.qa import CAUSAL_MARKERS

DECOMPOSITION_MEASURES = frozenset({"premium_movement", "movement_by_dim", "rate_volume_mix"})


@dataclass(frozen=True)
class CommentarySentence:
    """One drafted sentence with its citations — the unit of verification."""

    text: str
    fact_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    message: str
    slide_idx: int = -1


def _years_in_pack(pack: EvidencePack, fact_ids: Sequence[str]) -> Set[str]:
    """Period years are legitimate numbers even when no fact renders them."""
    years: Set[str] = set()
    for label in (pack.period, pack.comparison_period):
        years.update(re.findall(r"\d{4}", label or ""))
    for fid in fact_ids:
        item = pack.items.get(fid)
        if item is None:
            continue
        for v in item.dims.values():
            if str(v).isdigit() and len(str(v)) == 4:
                years.add(str(v))
        if item.provenance and item.provenance.period is not None:
            years.add(str(item.provenance.period))
    return years


def _allowed_number_tokens(pack: EvidencePack, fact_ids: Sequence[str]) -> Set[str]:
    sources = []
    for fid in fact_ids:
        item = pack.items.get(fid)
        if item is not None:
            sources.append(item.rendered)
            sources.append(f"{item.value}")
    allowed = allowed_numbers(*sources)
    allowed.update(_norm(y) for y in _years_in_pack(pack, fact_ids))
    return allowed


def _cited_measures(pack: EvidencePack, fact_ids: Sequence[str]) -> Set[str]:
    return {pack.items[f].measure for f in fact_ids if f in pack.items}


def _sentence_issues(
    sent: CommentarySentence,
    plan: SlideCommentaryPlan,
    pack: EvidencePack,
    rules,
    forbidden_names: Sequence[str],
) -> List[str]:
    """All rule violations for one sentence (empty ⇒ the sentence survives)."""
    problems: List[str] = []

    if plan.contract.require_fact_citations and not sent.fact_ids:
        return [f"uncited_sentence: {sent.text[:60]!r} carries no fact ids"]

    allowed_ids = set(plan.allowed_fact_ids)
    for fid in sent.fact_ids:
        if fid not in pack.items:
            problems.append(f"unknown_fact: cites nonexistent fact id {fid!r}")
        elif fid not in allowed_ids:
            problems.append(f"fact_not_allowed: {fid!r} is outside this slide's evidence packet")
    if problems:
        return problems

    # Numbers must come from the cited facts (or be a period year).
    allowed = _allowed_number_tokens(pack, sent.fact_ids)
    for m in _TOKEN_RE.finditer(sent.text):
        norm = _norm(m.group(0))
        if norm and norm not in allowed:
            problems.append(f"unsupported_number: {m.group(0).strip()!r} not in cited facts")

    # Peer confidentiality.
    if rules.commentary.block_named_peer_mentions:
        low = sent.text.lower()
        for name in forbidden_names:
            if name and name.lower() in low:
                problems.append(f"peer_name: individual peer {name!r} in carrier-facing prose")

    measures = _cited_measures(pack, sent.fact_ids)

    # Causal wording needs a decomposition fact.
    if rules.commentary.block_causal_language_without_driver_fact:
        hit = next((mk for mk in CAUSAL_MARKERS if mk in sent.text.lower()), None)
        if hit and not (measures & DECOMPOSITION_MEASURES):
            problems.append(
                f"unsupported_causation: {hit!r} used without a decomposition fact")

    # YoY rules.
    movement_pcts = [pack.items[f] for f in sent.fact_ids
                     if f in pack.items and pack.items[f].measure == "premium_movement_pct"]
    if movement_pcts:
        totals = [pack.items[f] for f in sent.fact_ids
                  if f in pack.items and pack.items[f].measure == "premium_total"]
        if rules.yoy.always_include_current_and_prior and len(totals) < 2:
            problems.append(
                "yoy_missing_years: YoY cited without both current and prior premium")
        cur = max(totals, key=lambda t: t.provenance.period or 0) if totals else None
        if cur is not None and cur.value < rules.yoy.suppress_if_current_premium_below:
            problems.append(
                f"yoy_suppressed: current premium {cur.rendered} below the narration floor")
        big = any(abs(mp.value) >= rules.drivers.large_change_pct for mp in movement_pcts)
        has_abs = "premium_movement" in measures
        if big and rules.yoy.require_absolute_change and not has_abs:
            problems.append(
                "missing_absolute_change: large YoY move cited without the absolute movement")

    return problems


def verify_sentences(
    sentences: Sequence[CommentarySentence],
    plan: SlideCommentaryPlan,
    pack: EvidencePack,
    *,
    forbidden_names: Sequence[str] = (),
) -> Tuple[Tuple[CommentarySentence, ...], Tuple[VerificationIssue, ...]]:
    """Filter to the faithful sentences; report why the rest were dropped."""
    from studio.rules import load_rules

    rules = load_rules()
    kept: List[CommentarySentence] = []
    issues: List[VerificationIssue] = []

    for sent in sentences:
        if not (sent.text or "").strip():
            continue
        problems = _sentence_issues(sent, plan, pack, rules, forbidden_names)
        if problems:
            issues.extend(
                VerificationIssue(p.split(":", 1)[0], p, plan.slide_idx) for p in problems
            )
            continue
        kept.append(sent)

    cap = plan.contract.max_bullets * plan.contract.max_sentences_per_bullet
    if len(kept) > cap:
        issues.append(VerificationIssue(
            "trimmed", f"{len(kept) - cap} sentence(s) over the contract cap dropped",
            plan.slide_idx))
        kept = kept[:cap]
    return tuple(kept), tuple(issues)
