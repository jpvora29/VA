"""Commentary planner — pack + graph → a bounded per-slide evidence packet (Phase 4).

For each commentary-bearing slide the planner selects the facts that slide is
allowed to cite: measures the contract permits, entities that clear the
materiality floor, plus every component a movement was derived from (so the
YoY rule — current + prior premium must accompany a YoY mention — is satisfiable
by construction). Slides whose selection is empty are recorded as data gaps
rather than filled with generic prose.

Pure and deterministic: fact ids are sorted, no LLM, no engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from studio.commentary.contracts import CommentaryContract, contract_for
from studio.content.evidence_graph import EvidenceGraph, material_entities
from studio.content.evidence_pack import EvidencePack


@dataclass(frozen=True)
class SlideCommentaryPlan:
    """One slide's bounded evidence packet."""

    slide_idx: int
    purpose: str
    contract: CommentaryContract
    allowed_fact_ids: Tuple[str, ...]
    focus: str = ""                        # entity label the slide is about ("" = whole book)
    data_gap: str = ""                     # non-empty ⇒ nothing citable; record, don't invent


@dataclass(frozen=True)
class CommentaryPlan:
    subject: str
    slides: Tuple[SlideCommentaryPlan, ...] = ()

    def gaps(self) -> Tuple[SlideCommentaryPlan, ...]:
        return tuple(s for s in self.slides if s.data_gap)


def _closure_with_derivations(pack: EvidencePack, fact_ids: Sequence[str]) -> Tuple[str, ...]:
    """Fact ids plus everything they were derived from (movement → its two totals)."""
    out = set(fact_ids)
    frontier = list(fact_ids)
    while frontier:
        item = pack.items.get(frontier.pop())
        if item is None:
            continue
        for src in item.derived_from:
            if src not in out and src in pack.items:
                out.add(src)
                frontier.append(src)
    return tuple(sorted(out))


def _facts_for_slide(
    pack: EvidencePack,
    graph: EvidenceGraph,
    contract: CommentaryContract,
    *,
    focus: str = "",
) -> Tuple[str, ...]:
    """The fact ids a slide may cite: allowed measures × material entities."""
    material = set(material_entities(pack, graph))
    picked: List[str] = []
    for fid, item in sorted(pack.items.items()):
        if item.measure not in contract.allowed_measures:
            continue
        # Entity-scoped facts must clear materiality; subject-level facts always pass.
        entity_ids = graph.neighbors(f"fact:{fid}", "about")
        entity_scoped = [e for e in entity_ids if not e.startswith("carrier:")]
        if entity_scoped and not any(e in material for e in entity_scoped):
            continue
        if focus and entity_scoped and not any(
            e.split(":", 1)[1] == focus for e in entity_scoped
        ):
            continue
        picked.append(fid)
    return _closure_with_derivations(pack, picked)


def build_commentary_plan(
    pack: EvidencePack,
    graph: EvidenceGraph,
    slide_purposes: Sequence[Tuple[int, str]],
    *,
    focus_by_slide: Optional[dict] = None,
) -> CommentaryPlan:
    """Plan commentary for the given ``(slide_idx, purpose)`` targets.

    ``focus_by_slide`` optionally narrows a slide to one entity label (a product
    deep-dive slide cites only that product's facts).
    """
    focus_by_slide = focus_by_slide or {}
    slides: List[SlideCommentaryPlan] = []
    for slide_idx, purpose in slide_purposes:
        contract = contract_for(purpose)
        focus = str(focus_by_slide.get(slide_idx, ""))
        fact_ids = _facts_for_slide(pack, graph, contract, focus=focus)
        gap = ""
        if not fact_ids:
            gap = (f"no citable facts for {purpose} "
                   f"(measures {', '.join(contract.allowed_measures[:3])}… unavailable or immaterial)")
        slides.append(SlideCommentaryPlan(
            slide_idx=slide_idx, purpose=purpose, contract=contract,
            allowed_fact_ids=fact_ids, focus=focus, data_gap=gap,
        ))
    return CommentaryPlan(subject=pack.subject, slides=tuple(slides))
