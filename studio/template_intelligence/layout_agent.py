"""Layout-intent agent — semantic interpretation of a template's structure (Phase 2).

Deterministic-first: a keyword/kind heuristic labels every slide's purpose and
every shape's role with a confidence score. When the gated Studio LLM is
available (``studio.ai.client``) it may *refine* those labels via a strict
structured-output call; ``validate_layout_intent`` then rejects any returned
reference that does not exist in the descriptor, so the agent can never invent a
slide or shape id. With ``STUDIO_AI=off`` the heuristic labelling stands alone
and the output is fully deterministic.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from logger import get_logger
from studio.template_intelligence.descriptor import (
    ShapeDescriptor,
    SlideDescriptor,
    TemplateDescriptor,
    shape_ref,
)

logger = get_logger(__name__)

# Closed vocabularies — agent output outside these is discarded.
SLIDE_PURPOSES = (
    "cover", "agenda", "divider", "executive_summary", "trading_summary",
    "product_deep_dive", "country_view", "swot", "feedback", "ranking",
    "growth", "methodology", "appendix", "other",
)
SHAPE_ROLES = (
    "title", "subtitle", "kpi", "commentary", "chart", "table",
    "footer", "source", "decorative", "manual", "label",
)


@dataclass(frozen=True)
class SlidePurpose:
    slide_idx: int
    purpose: str                          # one of SLIDE_PURPOSES
    confidence: float = 1.0
    note: str = ""


@dataclass(frozen=True)
class ShapeRoleLabel:
    slide_idx: int
    shape_id: int
    role: str                             # one of SHAPE_ROLES
    expected_content: str = "text"        # money | pct | int | rank | text | series | none
    confidence: float = 1.0

    @property
    def ref(self) -> str:
        return shape_ref(self.slide_idx, self.shape_id)


@dataclass(frozen=True)
class LayoutIntent:
    """Semantic reading of the template: per-slide purpose + per-shape role."""

    slides: Tuple[SlidePurpose, ...] = ()
    shapes: Tuple[ShapeRoleLabel, ...] = ()
    ambiguities: Tuple[str, ...] = ()     # human-readable notes on uncertain labels

    def purpose_of(self, slide_idx: int) -> Optional[SlidePurpose]:
        return next((s for s in self.slides if s.slide_idx == slide_idx), None)

    def role_of(self, slide_idx: int, shape_id: int) -> Optional[ShapeRoleLabel]:
        return next(
            (s for s in self.shapes if s.slide_idx == slide_idx and s.shape_id == shape_id),
            None,
        )

    def low_confidence(self, threshold: float = 0.5) -> Tuple[ShapeRoleLabel, ...]:
        return tuple(s for s in self.shapes if s.confidence < threshold)


# ── deterministic slide-purpose heuristics ────────────────────────────────────

_DIVIDER_TITLE = re.compile(r"^\s*(?:country|region|product)\s*\(\s*\d+\s*\)\s*$", re.I)

# Ordered (keywords → purpose, confidence); first match wins.
_PURPOSE_RULES: List[Tuple[Tuple[str, ...], str, float]] = [
    (("swot",), "swot", 0.9),
    (("trading summary",), "trading_summary", 0.9),
    (("executive summary", "exec summary"), "executive_summary", 0.9),
    (("feedback",), "feedback", 0.85),
    (("methodology", "limitations", "data sources"), "methodology", 0.85),
    (("appendix",), "appendix", 0.85),
    (("agenda", "contents"), "agenda", 0.85),
    (("lc ranking", "ranking",), "ranking", 0.8),
    (("growth rate", "vs marsh growth", "growth"), "growth", 0.7),
    (("product deep dive", "product line", "portfolio and lc", "portfolio"), "product_deep_dive", 0.7),
    (("country view", "country performance", "by country"), "country_view", 0.7),
    (("highlight", "summary"), "executive_summary", 0.6),
]


def _slide_purpose(slide: SlideDescriptor) -> SlidePurpose:
    title = slide.title.strip()
    low = title.lower()
    if _DIVIDER_TITLE.match(title):
        return SlidePurpose(slide.index, "divider", 0.9)
    if slide.index == 0 and len(slide.shapes) <= 6:
        return SlidePurpose(slide.index, "cover", 0.7)
    for keywords, purpose, conf in _PURPOSE_RULES:
        if any(k in low for k in keywords):
            return SlidePurpose(slide.index, purpose, conf)
    return SlidePurpose(slide.index, "other", 0.3, note=f"no keyword match for title {title[:60]!r}")


# ── deterministic shape-role heuristics ───────────────────────────────────────

_ELLIPSIS = re.compile(r"…|\.{3,}")
_SOURCE = re.compile(r"\bsource\b|\bconfidential\b|\bmethodolog", re.I)


def _shape_role(slide: SlideDescriptor, sh: ShapeDescriptor, slide_h: int) -> ShapeRoleLabel:
    def label(role: str, expected: str = "text", conf: float = 0.8) -> ShapeRoleLabel:
        return ShapeRoleLabel(slide.index, sh.shape_id, role, expected, conf)

    if sh.kind == "chart":
        # An externally-linked (think-cell) chart cannot be auto-filled — manual only.
        if sh.chart_external:
            return label("manual", "none", 0.9)
        return label("chart", "series", 0.9)
    if sh.kind == "table":
        return label("table", "text", 0.9)
    if sh.kind == "picture":
        return label("decorative", "none", 0.9)
    if sh.kind != "text" or not sh.text.strip():
        return label("decorative", "none", 0.5)

    text = sh.text.strip()
    if "title" in sh.name.lower() or (text and text == slide.title):
        return label("title", "text", 0.9)
    if _SOURCE.search(text) and sh.y > slide_h * 0.8:
        return label("source", "text", 0.85)
    if sh.y > slide_h * 0.9 and len(text) <= 80:
        return label("footer", "text", 0.7)
    if sh.tokens:
        from studio.template_fill.slots import classify

        kinds = {classify(t) or "text" for t in sh.tokens}
        numeric = kinds & {"money", "pct", "int", "rank"}
        if numeric:
            return label("kpi", sorted(numeric)[0], 0.85)
        if any(_ELLIPSIS.search(t) for t in sh.tokens):
            return label("commentary", "text", 0.85)
        return label("label", "text", 0.7)
    if len(text) <= 40:
        return label("label", "text", 0.6)
    return label("commentary", "text", 0.4)


def detect_layout_intent_deterministic(descriptor: TemplateDescriptor) -> LayoutIntent:
    """Heuristic labelling only — the fallback that always works, LLM or not."""
    slides = tuple(_slide_purpose(s) for s in descriptor.slides)
    shapes = tuple(
        _shape_role(s, sh, descriptor.height_emu or 1)
        for s in descriptor.slides for sh in s.shapes
    )
    ambiguities = tuple(
        f"slide {p.slide_idx}: {p.note}" for p in slides if p.note
    ) + tuple(
        f"{r.ref}: low-confidence role {r.role!r} ({r.confidence:.2f})"
        for r in shapes if r.confidence < 0.5
    )
    return LayoutIntent(slides=slides, shapes=shapes, ambiguities=ambiguities)


# ── validation: agent output may only reference real ids ─────────────────────


def validate_layout_intent(
    intent: LayoutIntent, descriptor: TemplateDescriptor
) -> Tuple[LayoutIntent, List[str]]:
    """Drop labels whose slide/shape does not exist or whose vocab is unknown.

    Returns the cleaned intent and the rejection notes (also appended to
    ``ambiguities``) — the deterministic gate between agent output and use.
    """
    valid_slides = {s.index for s in descriptor.slides}
    valid_refs = descriptor.shape_refs()
    rejected: List[str] = []

    slides = []
    for p in intent.slides:
        if p.slide_idx not in valid_slides:
            rejected.append(f"slide purpose references nonexistent slide {p.slide_idx}")
            continue
        if p.purpose not in SLIDE_PURPOSES:
            rejected.append(f"slide {p.slide_idx}: unknown purpose {p.purpose!r}")
            continue
        slides.append(SlidePurpose(p.slide_idx, p.purpose, max(0.0, min(1.0, p.confidence)), p.note))

    shapes = []
    for r in intent.shapes:
        if r.ref not in valid_refs:
            rejected.append(f"shape role references nonexistent shape {r.ref}")
            continue
        if r.role not in SHAPE_ROLES:
            rejected.append(f"{r.ref}: unknown role {r.role!r}")
            continue
        shapes.append(ShapeRoleLabel(r.slide_idx, r.shape_id, r.role, r.expected_content,
                                     max(0.0, min(1.0, r.confidence))))

    cleaned = LayoutIntent(
        slides=tuple(slides), shapes=tuple(shapes),
        ambiguities=tuple(intent.ambiguities) + tuple(rejected),
    )
    return cleaned, rejected


# ── optional LLM refinement (strict structured output) ───────────────────────


def _ai_models():
    """Pydantic boundary models, imported lazily (pydantic only at the LLM seam)."""
    from pydantic import BaseModel, Field

    class SlideLabel(BaseModel):
        slide_idx: int = Field(description="Existing slide index from the payload")
        purpose: str = Field(description=f"One of: {', '.join(SLIDE_PURPOSES)}")
        confidence: float = Field(ge=0.0, le=1.0)

    class TemplateLayout(BaseModel):
        slides: List[SlideLabel]

    return TemplateLayout


_SYSTEM = """You classify PowerPoint template slides for an insurance QBR generator.
For each slide choose its purpose from the allowed vocabulary ONLY, with a confidence.
Never invent slide indexes — use only the indexes provided. Purposes: {purposes}."""


def _ai_payload(descriptor: TemplateDescriptor) -> str:
    slides = [
        {
            "slide_idx": s.index,
            "layout": s.layout,
            "title": s.title[:120],
            "n_shapes": len(s.shapes),
            "has_chart": any(sh.kind == "chart" for sh in s.shapes),
            "has_table": any(sh.kind == "table" for sh in s.shapes),
            "sample_text": [sh.text[:80] for sh in s.shapes if sh.kind == "text"][:6],
        }
        for s in descriptor.slides
    ]
    return json.dumps({"slides": slides}, ensure_ascii=False)


def _label_slides_with_ai(descriptor: TemplateDescriptor):
    """AI slide labels via the deep-agent harness first, one-shot call second.

    The harness (`studio.ai.deep_agent`) brings the ``template-layout`` skill,
    planning and retry middleware; when it is off or fails, the plain structured
    call keeps working exactly as before. Returns the pydantic labels or None.
    """
    from studio.ai.client import llm_available, structured
    from studio.ai.deep_agent import deep_agent_available, run_deep_agent

    if not llm_available():
        return None
    model = _ai_models()
    system = _SYSTEM.format(purposes=", ".join(SLIDE_PURPOSES))
    if deep_agent_available():
        result = run_deep_agent(
            _ai_payload(descriptor), system_prompt=system,
            response_format=model, tier="fast", node="template-layout",
        )
        if result is not None:
            return result
    return structured(model, system, _ai_payload(descriptor),
                      tier="fast", node="template-layout")


def _refine_with_ai(descriptor: TemplateDescriptor, base: LayoutIntent) -> LayoutIntent:
    """Let the gated LLM re-label slide purposes; keep only validated output."""
    result = _label_slides_with_ai(descriptor)
    if result is None:
        return base

    by_idx: Dict[int, SlidePurpose] = {p.slide_idx: p for p in base.slides}
    for lab in result.slides:
        prior = by_idx.get(lab.slide_idx)
        # Only accept an AI label when it beats the heuristic's confidence.
        if prior is not None and lab.purpose in SLIDE_PURPOSES and lab.confidence > prior.confidence:
            by_idx[lab.slide_idx] = SlidePurpose(lab.slide_idx, lab.purpose, lab.confidence,
                                                 note="ai-refined")
    refined = LayoutIntent(
        slides=tuple(by_idx[i] for i in sorted(by_idx)),
        shapes=base.shapes, ambiguities=base.ambiguities,
    )
    cleaned, rejected = validate_layout_intent(refined, descriptor)
    if rejected:
        logger.warning("layout_agent: rejected %d AI label(s): %s", len(rejected), rejected[:3])
    return cleaned


async def detect_layout_intent(descriptor: TemplateDescriptor) -> LayoutIntent:
    """Deterministic labelling, then optional AI refinement, then validation."""
    base = detect_layout_intent_deterministic(descriptor)
    intent = await asyncio.to_thread(_refine_with_ai, descriptor, base)
    cleaned, _ = validate_layout_intent(intent, descriptor)
    return cleaned


def detect_layout_intent_sync(descriptor: TemplateDescriptor) -> LayoutIntent:
    """Synchronous variant for non-async callers (Dash callbacks, tests)."""
    base = detect_layout_intent_deterministic(descriptor)
    cleaned, _ = validate_layout_intent(_refine_with_ai(descriptor, base), descriptor)
    return cleaned
