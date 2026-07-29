"""Commentary drafting — bounded evidence in, cited sentences out (Phase 5).

The deterministic drafter composes the plan's narrative structure (what changed →
why it matters → drivers if supported → watch next) purely from the slide's
allowed facts, citing every number's fact id — 100% faithful by construction.
When the gated Studio LLM is available it may redraft the wording via a strict
structured-output call that must return fact ids per sentence; either way the
deterministic verifier (:mod:`studio.commentary.verify`) filters the result, so
unsupported numbers, causality or peer names never reach the deck.

Async drafting uses ``gather_ordered`` so parallel slides never reorder.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from logger import get_logger
from studio.commentary.planner import CommentaryPlan, SlideCommentaryPlan
from studio.commentary.verify import CommentarySentence, VerificationIssue, verify_sentences
from studio.content.evidence_pack import EvidenceItem, EvidencePack

logger = get_logger(__name__)


@dataclass(frozen=True)
class SlideCommentary:
    """Verified commentary for one slide (empty sentences ⇒ honest data gap)."""

    slide_idx: int
    purpose: str
    sentences: Tuple[CommentarySentence, ...] = ()
    issues: Tuple[VerificationIssue, ...] = ()
    data_gap: str = ""

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


# ── deterministic drafting (the always-available author) ─────────────────────


def _facts(pack: EvidencePack, plan: SlideCommentaryPlan, measure: str) -> List[EvidenceItem]:
    return [pack.items[f] for f in plan.allowed_fact_ids
            if f in pack.items and pack.items[f].measure == measure]


def _total_scope(items: Sequence[EvidenceItem]) -> List[EvidenceItem]:
    return [i for i in items if i.dims.get("scope") == "total"]


def _what_changed(pack: EvidencePack, plan: SlideCommentaryPlan) -> Optional[CommentarySentence]:
    """Premium moved X% YoY to CUR, from PRIOR — with the absolute move when large."""
    from studio.rules import load_rules

    pcts = _total_scope(_facts(pack, plan, "premium_movement_pct"))
    totals = sorted(_facts(pack, plan, "premium_total"),
                    key=lambda i: (i.provenance.period or 0) if i.provenance else 0)
    if not pcts or len(totals) < 2:
        return None
    pct_item = pcts[0]
    prior, current = totals[0], totals[-1]
    cites = [pct_item.fact_id, current.fact_id, prior.fact_id]

    verb = "grew" if pct_item.value >= 0 else "declined"
    text = (f"{pack.subject} premium {verb} {pct_item.rendered} year on year to "
            f"{current.rendered}, from {prior.rendered} in {pack.comparison_period}.")

    rules = load_rules()
    if abs(pct_item.value) >= rules.drivers.large_change_pct and rules.yoy.require_absolute_change:
        deltas = _total_scope(_facts(pack, plan, "premium_movement"))
        if deltas:
            text = text[:-1] + f" — an absolute movement of {deltas[0].rendered}."
            cites.append(deltas[0].fact_id)
    return CommentarySentence(text, tuple(cites))


def _why_it_matters(pack: EvidencePack, plan: SlideCommentaryPlan) -> Optional[CommentarySentence]:
    ranks = _facts(pack, plan, "rank")
    sows = _facts(pack, plan, "sow")
    if ranks and sows:
        return CommentarySentence(
            f"That keeps {pack.subject} at {ranks[0].rendered} in the market with "
            f"{sows[0].rendered} share of wallet.",
            (ranks[0].fact_id, sows[0].fact_id))
    if ranks:
        return CommentarySentence(
            f"{pack.subject} holds {ranks[0].rendered} in the market.", (ranks[0].fact_id,))
    if sows:
        return CommentarySentence(
            f"{pack.subject}'s share of wallet stands at {sows[0].rendered}.",
            (sows[0].fact_id,))
    return None


def _drivers(pack: EvidencePack, plan: SlideCommentaryPlan) -> Optional[CommentarySentence]:
    """Name a driver only when a decomposition fact explains enough of the move."""
    from studio.rules import load_rules

    rules = load_rules()
    total_deltas = _total_scope(_facts(pack, plan, "premium_movement"))
    dim_deltas = [i for i in _facts(pack, plan, "premium_movement")
                  if i.dims.get("scope") != "total"]
    if not total_deltas or not dim_deltas:
        return None
    total = total_deltas[0]
    if not total.value:
        return None
    top = max(dim_deltas, key=lambda i: abs(i.value))
    contribution = abs(top.value) / abs(total.value) * 100.0
    if rules.drivers.require_driver_for_large_change and \
            contribution < rules.drivers.min_driver_contribution_pct:
        return None
    entity = next((str(v) for k, v in top.dims.items() if k not in ("scope", "year")), "")
    if not entity:
        return None
    return CommentarySentence(
        f"The movement was driven by {entity}, which contributed {top.rendered} "
        f"of the {total.rendered} total change.",
        (top.fact_id, total.fact_id))


def _watch_next(pack: EvidencePack, plan: SlideCommentaryPlan) -> Optional[CommentarySentence]:
    if not plan.contract.allow_recommendations:
        return None
    ws = sorted(_facts(pack, plan, "whitespace_market"), key=lambda i: -i.value)
    if not ws:
        return None
    entity = next((str(v) for v in ws[0].dims.values()), "the largest gap")
    return CommentarySentence(
        f"Leaders should watch {entity} — {ws[0].rendered} of market premium "
        f"currently unwritten.",
        (ws[0].fact_id,))


_STRUCTURE_BUILDERS = {
    "what_changed": _what_changed,
    "why_it_matters": _why_it_matters,
    "drivers": _drivers,
    "watch_next": _watch_next,
}


def draft_deterministic(
    plan: SlideCommentaryPlan, pack: EvidencePack
) -> Tuple[CommentarySentence, ...]:
    """The contract structure, composed purely from allowed facts."""
    out: List[CommentarySentence] = []
    for step in plan.contract.structure:
        builder = _STRUCTURE_BUILDERS.get(step)
        sent = builder(pack, plan) if builder else None
        if sent is not None:
            out.append(sent)
    return tuple(out)


# ── optional LLM redraft (strict structured output) ──────────────────────────


def _ai_model():
    from pydantic import BaseModel, Field

    class SentenceModel(BaseModel):
        sentence: str = Field(description="One commentary sentence")
        fact_ids: List[str] = Field(description="Fact ids from the packet that support EVERY number")

    class SlideCommentaryModel(BaseModel):
        sentences: List[SentenceModel]

    return SlideCommentaryModel


_SYSTEM = """You are a senior insurance broking analyst writing QBR slide commentary
for ICL leaders and carriers. Rewrite the draft using ONLY the evidence packet.
HARD RULES: every sentence must list the fact_ids supporting it; every number,
currency amount, percentage and rank must be copied EXACTLY from a cited fact's
rendered value; never invent fact ids; never name a competitor carrier; no causal
claims ("drove", "because") unless a decomposition fact is cited. Structure:
what changed -> why it matters -> what drove it (only if supported) -> what to watch.
At most {max_sentences} sentences."""


def _packet_json(plan: SlideCommentaryPlan, pack: EvidencePack,
                 draft: Sequence[CommentarySentence]) -> str:
    facts = [
        {"fact_id": f, "measure": pack.items[f].measure,
         "rendered": pack.items[f].rendered,
         "dims": {str(k): str(v) for k, v in pack.items[f].dims.items()}}
        for f in plan.allowed_fact_ids if f in pack.items
    ]
    return json.dumps({
        "subject": pack.subject, "period": pack.period,
        "comparison_period": pack.comparison_period,
        "slide_purpose": plan.purpose,
        "evidence": facts,
        "deterministic_draft": [{"sentence": s.text, "fact_ids": list(s.fact_ids)} for s in draft],
    }, ensure_ascii=False)


def _redraft_with_ai(
    plan: SlideCommentaryPlan, pack: EvidencePack, draft: Sequence[CommentarySentence]
) -> Optional[Tuple[CommentarySentence, ...]]:
    """Redraft via the deep-agent harness (commentary-style skill) when on,
    the one-shot structured call otherwise; the verifier gates both the same way.
    """
    from studio.ai.client import llm_available, structured
    from studio.ai.deep_agent import deep_agent_available, run_deep_agent

    if not llm_available() or not draft:
        return None
    cap = plan.contract.max_bullets * plan.contract.max_sentences_per_bullet
    model = _ai_model()
    system = _SYSTEM.format(max_sentences=cap)
    packet = _packet_json(plan, pack, draft)
    node = f"commentary-{plan.purpose}"

    result = None
    if deep_agent_available():
        result = run_deep_agent(packet, system_prompt=system, response_format=model,
                                tier="fast", node=node)
    if result is None:
        result = structured(model, system, packet, tier="fast", node=node)
    if result is None or not result.sentences:
        return None
    return tuple(CommentarySentence(s.sentence, tuple(s.fact_ids)) for s in result.sentences)


# ── per-slide draft + verify, and the ordered parallel entrypoint ─────────────


async def draft_slide_commentary(
    plan: SlideCommentaryPlan,
    pack: EvidencePack,
    *,
    forbidden_names: Sequence[str] = (),
) -> SlideCommentary:
    """Draft one slide (LLM if available, deterministic otherwise) and verify it."""
    if plan.data_gap:
        return SlideCommentary(plan.slide_idx, plan.purpose, data_gap=plan.data_gap)

    draft = draft_deterministic(plan, pack)
    redrafted = await asyncio.to_thread(_redraft_with_ai, plan, pack, draft)
    candidate = redrafted if redrafted else draft

    kept, issues = verify_sentences(candidate, plan, pack, forbidden_names=forbidden_names)
    if redrafted and not kept:
        # The redraft failed verification wholesale — fall back to the faithful draft.
        kept, fallback_issues = verify_sentences(draft, plan, pack,
                                                 forbidden_names=forbidden_names)
        issues = issues + fallback_issues
    gap = "" if kept else (plan.data_gap or "no sentence survived verification")
    return SlideCommentary(plan.slide_idx, plan.purpose, kept, issues, data_gap=gap)


async def draft_and_verify_commentary(
    plan: CommentaryPlan,
    pack: EvidencePack,
    *,
    forbidden_names: Sequence[str] = (),
    max_parallel: int = 4,
) -> Tuple[SlideCommentary, ...]:
    """Draft every slide in parallel, preserving slide order in the result."""
    from studio.pipeline.async_utils import bounded_gather

    tasks = [
        draft_slide_commentary(s, pack, forbidden_names=forbidden_names)
        for s in plan.slides
    ]
    results = await bounded_gather(tasks, limit=max_parallel)
    return tuple(results)
