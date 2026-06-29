"""Per-page commentary — fill a template's qualitative prose slots from the facts.

Section-aware (see :mod:`studio.template_fill.sections`): on slides that carry
fact-derivable commentary (Trading Summary, SWOT, Highlights, Summary) the ellipsis
prose boxes are bound to ``note:<slot-key>`` roles and filled with commentary built by
:mod:`studio.narrate.commentary` (100% faithful by construction). When an LLM is
configured the wording is polished and then re-checked by the faithfulness verifier
(numbers must already appear in the deterministic text); otherwise the deterministic
text stands. Qualitative-only sections (relationship Feedback) are deliberately left as
placeholders — premium data can't honestly fill them.

Mirrors :mod:`studio.template_fill.grids`: ``augment`` re-binds slots, ``values``
produces the keyed text — both fold into the same doc the preview and fill consume.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from logger import get_logger
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template
from studio.template_fill.sections import Section, section_of

logger = get_logger(__name__)

_ELLIPSIS = re.compile(r"…|\.{3,}")
# Sections whose prose we can ground in premium facts.
_COMMENTARY_SECTIONS = {
    Section.TRADING_SUMMARY, Section.SWOT, Section.HIGHLIGHTS, Section.SUMMARY,
}
_POLISH_SYS = (
    "Rewrite this insurance QBR commentary to be crisp and executive. Keep EVERY number "
    "and the carrier name exactly as given; never invent figures and never name a "
    "competitor. Reply with 1–2 short sentences only."
)


def _cx(sh: Shape) -> float:
    return sh.x + sh.w / 2.0


def _is_prose_slot(sh: Shape) -> bool:
    return sh.kind == "text" and bool(sh.paragraphs) and bool(_ELLIPSIS.search(sh.paragraphs[0] or ""))


def _column_topic(slide: Slide, shape: Shape) -> str:
    """The topic keyword for a prose box = its nearest header above (same column)."""
    headers = [s for s in slide.shapes
               if s.kind == "text" and s is not shape and s.text.strip()
               and not _is_prose_slot(s) and s.y < shape.y and len(s.text.strip()) <= 32]
    if not headers:
        return slide.title()
    return min(headers, key=lambda s: abs(_cx(s) - _cx(shape))).text.strip()


def _topic_key(header: str) -> str:
    low = header.lower()
    if "reflection" in low:
        return "reflections"
    if "performance" in low or "ytd" in low:
        return "performance"
    if "priorit" in low:
        return "priorities"
    if "message" in low:
        return "key_messages"
    if "strength" in low:
        return "strengths"
    if "weak" in low:
        return "weaknesses"
    if "opportun" in low:
        return "opportunities"
    if "threat" in low:
        return "threats"
    return "key_messages"


def _ellipsis_paras(sh: Shape) -> List[int]:
    return [i for i, p in enumerate(sh.paragraphs) if _ELLIPSIS.search(p or "")]


def _prose_targets(template: Template) -> List[Dict[str, Any]]:
    """``[{slide_idx, shape_id, paras, topic}]`` for every fillable prose box in a
    commentary section. ``paras`` are the box's ellipsis paragraph indices — the whole
    column is one commentary (paragraph 0 carries it; the rest are blanked)."""
    out: List[Dict[str, Any]] = []
    for slide in template.slides:
        if section_of(slide) not in _COMMENTARY_SECTIONS:
            continue
        for sh in slide.shapes:
            if _is_prose_slot(sh):
                out.append({"slide_idx": slide.index, "shape_id": sh.shape_id,
                            "paras": _ellipsis_paras(sh),
                            "topic": _topic_key(_column_topic(slide, sh))})
    return out


def _role(slide_idx: int, shape_id: int, para: int) -> str:
    return f"note:{slide_idx}:{shape_id}:{para}"


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Re-bind commentary prose slots to ``note:<slide>:<shape>:<para>`` roles.

    Paragraph 0 carries the column's commentary; the box's remaining ellipsis
    paragraphs are bound too so they get blanked (no leftover ``………`` lines)."""
    from studio.template_fill.slots import Slot

    by_key = {b.slot.key: b for b in bindings}
    for t in _prose_targets(template):
        for i in t["paras"]:
            slot = Slot(t["slide_idx"], t["shape_id"], ["para", i], "", "text", "")
            b = by_key.get(slot.key)
            if b is not None:
                b.role, b.placeholder = _role(t["slide_idx"], t["shape_id"], i), False
    return bindings


# ── text generation ──────────────────────────────────────────────────────────


def _polish(text: str, *, node: str) -> str:
    """LLM-polish ``text`` if available, keeping only verifier-faithful output."""
    if not text:
        return text
    from studio.ai import client
    from studio.ai.verifier import allowed_numbers, verify_text

    allowed = allowed_numbers(text)

    def call() -> Optional[str]:
        out = client.generate(_POLISH_SYS, text, tier="fast", node=node)
        if not out:
            return None
        clean, _ = verify_text(out, allowed)
        return clean or None

    return client.run_or_fallback(call, lambda: text)


def _topic_text(result, topic: str) -> str:
    """Deterministic, fact-grounded commentary for a column/quadrant topic."""
    from studio.narrate.commentary import build_commentary, build_initiatives, build_swot

    headline, points, actions = build_commentary(result)

    def by_label(*labels: str) -> List[str]:
        return [p["text"] for p in points if p["label"].rstrip(".") in labels]

    if topic == "reflections":
        return headline
    if topic == "performance":
        txt = by_label("Momentum", "Soft spots", "Penetration")
        return " ".join(txt[:2]) or headline
    if topic == "priorities":
        cards = build_initiatives(result)
        if cards:
            return " ".join(f"{c['title']} — {c['body']}" for c in cards[:2])
        return " ".join(actions[:2])
    if topic == "key_messages":
        return " ".join(actions[:3]) or " ".join(p["text"] for p in points[:2]) or headline
    if topic in ("strengths", "weaknesses", "opportunities", "threats"):
        swot = build_swot(result)
        items = getattr(swot, topic, []) or []
        return "; ".join(items[:3])
    return headline


def values(template: Template, result) -> Dict[str, Any]:
    """``{note-role: text}`` for every commentary prose slot in the deck."""
    out: Dict[str, Any] = {}
    targets = _prose_targets(template)
    if not targets:
        return out
    cache: Dict[str, str] = {}
    for t in targets:
        topic = t["topic"]
        if topic not in cache:
            try:
                base = _topic_text(result, topic)
                cache[topic] = _polish(base, node=f"commentary-{topic}") if base else ""
            except Exception as exc:  # noqa: BLE001 — commentary must never break the doc
                logger.warning("commentary: topic %s failed: %s", topic, exc)
                cache[topic] = ""
        if not cache[topic]:
            continue
        paras = t["paras"] or [0]
        out[_role(t["slide_idx"], t["shape_id"], paras[0])] = cache[topic]
        for i in paras[1:]:  # blank the box's other ellipsis lines
            out[_role(t["slide_idx"], t["shape_id"], i)] = ""
    logger.info("commentary: filled %d prose slot(s) across %d topic(s)", len(out), len(cache))
    return out
