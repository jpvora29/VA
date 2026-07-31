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
from typing import Any, Dict, List, Optional, Tuple

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
# The commentary voice chosen in Setup → the instruction appended to the polish prompt.
# Every style keeps the same faithfulness guardrails; only the tone/length shifts.
_STYLE_DIRECTIVE: Dict[str, str] = {
    "concise": "Keep each bullet to one short clause — the headline figure and nothing else.",
    "balanced": "Keep each bullet to one short sentence.",
    "detailed": "Allow each bullet up to two sentences: the figure and its 'so what'.",
}

# Commentary is written as BULLET POINTS, one per line, so the polish must preserve the line
# structure exactly — the deck renders each line as its own bulleted paragraph.
_BULLET_RULES = (
    "The draft is a bullet list, ONE BULLET PER LINE. Return exactly the same number of "
    "lines, in the same order, one polished bullet per line. Never merge, split, reorder or "
    "add lines. Do not write any bullet character, dash or number at the start of a line — "
    "the slide adds the bullet itself. "
)


def _style_system(style: Optional[str]) -> str:
    base = (
        "You are a senior Marsh broking analyst polishing commentary for a carrier QBR slide. "
        "Rewrite the draft so it reads board-ready: lead with the 'so what', use active voice, "
        "and keep every claim anchored to the figures provided. "
        "HARD RULES: keep EVERY number, currency amount, percentage and rank EXACTLY as written — "
        "never invent, recalculate or round a figure; never name a competitor carrier. "
    )
    return base + _BULLET_RULES + _STYLE_DIRECTIVE.get(
        (style or "balanced").lower(), _STYLE_DIRECTIVE["balanced"])


def _cx(sh: Shape) -> float:
    return sh.x + sh.w / 2.0


# A prose box the author left filled with EXAMPLE commentary rather than ellipses reads as
# a sentence — several words of running text. Headers, captions and KPI tokens never do.
_MIN_PROSE_WORDS = 8


def _reads_as_prose(text: str) -> bool:
    return len((text or "").split()) >= _MIN_PROSE_WORDS


def _is_prose_slot(sh: Shape) -> bool:
    """True for a commentary box: an ellipsis "fill me", or authored example prose.

    Templates mark a prose slot either way — ``…………`` in the earlier decks, a paragraph of
    sample commentary in the current ones. Both must be recognised, or a deck ships the
    author's example narrative as if it were this carrier's story.
    """
    if sh.kind != "text" or not sh.paragraphs:
        return False
    first = sh.paragraphs[0] or ""
    return bool(_ELLIPSIS.search(first)) or _reads_as_prose(first)


def _column_topic(slide: Slide, shape: Shape) -> str:
    """The topic keyword for a prose box = its nearest header above (same column)."""
    headers = [s for s in slide.shapes
               if s.kind == "text" and s is not shape and s.text.strip()
               and not _is_prose_slot(s) and s.y < shape.y and len(s.text.strip()) <= 32]
    if not headers:
        return slide.title()
    return min(headers, key=lambda s: abs(_cx(s) - _cx(shape))).text.strip()


# A prose box whose column header names no known topic falls back to its SECTION's topic:
# a highlights/summary page wants the headline, a four-column page its key messages.
_SECTION_DEFAULT_TOPIC: Dict[Section, str] = {
    Section.HIGHLIGHTS: "reflections",
    Section.SUMMARY: "reflections",
}

_HEADER_TOPICS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("reflection",), "reflections"),
    (("performance", "ytd"), "performance"),
    (("priorit",), "priorities"),
    (("message",), "key_messages"),
    (("strength",), "strengths"),
    (("weak",), "weaknesses"),
    (("opportun",), "opportunities"),
    (("threat",), "threats"),
)


def _topic_key(header: str, section: Section = Section.OTHER) -> str:
    low = header.lower()
    for keywords, topic in _HEADER_TOPICS:
        if any(k in low for k in keywords):
            return topic
    return _SECTION_DEFAULT_TOPIC.get(section, "key_messages")


def _prose_targets(template: Template) -> List[Dict[str, Any]]:
    """``[{slide_idx, shape_id, topic}]`` for every fillable prose box in a commentary section.

    One target per BOX, not per paragraph: the whole box is one bullet list, and the fill
    engine's commentary writer lays the bullets out over the box's paragraphs (appending and
    blanking as needed), so neither a stale ``………`` line nor a leftover line of the author's
    example prose survives.
    """
    out: List[Dict[str, Any]] = []
    for slide in template.slides:
        section = section_of(slide)
        if section not in _COMMENTARY_SECTIONS:
            continue
        for sh in slide.shapes:
            if _is_prose_slot(sh):
                out.append({"slide_idx": slide.index, "shape_id": sh.shape_id,
                            "topic": _topic_key(_column_topic(slide, sh), section)})
    return out


def _role(slide_idx: int, shape_id: int, para: int = 0) -> str:
    return f"note:{slide_idx}:{shape_id}:{para}"


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Re-bind (or add) each commentary prose box as a ``note:<slide>:<shape>:0`` role.

    A box the slot detector never saw — authored prose carries no ``x`` placeholder — is
    ADDED here, so it fills rather than shipping the author's example narrative.
    """
    from studio.template_fill.slots import Slot

    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    stale: List[R.Binding] = []
    for t in _prose_targets(template):
        shape = template.shape(t["slide_idx"], t["shape_id"])
        role = _role(t["slide_idx"], t["shape_id"])
        where = ["para", 0]
        b = by_key.get(Slot(t["slide_idx"], t["shape_id"], where, "", "text", "").key)
        if b is not None:
            b.role, b.placeholder = role, False
        else:
            token = shape.paragraphs[0] if (shape and shape.paragraphs) else ""
            extra.append(R.Binding(
                slot=Slot(t["slide_idx"], t["shape_id"], where, token, "text", ""),
                role=role, placeholder=False))
        # The box's LATER paragraphs are the writer's to lay out; any binding on them (from a
        # token scan, or an earlier augment pass) would fight it, so they are released.
        stale += [x for x in bindings
                  if x.slot.slide_idx == t["slide_idx"] and x.slot.shape_id == t["shape_id"]
                  and list(x.slot.where)[:1] == ["para"] and int(x.slot.where[1]) > 0]
    for b in stale:
        b.role, b.placeholder = None, True
    if extra:
        logger.info("commentary: added %d prose box(es) the token scan could not see", len(extra))
    return bindings + extra


# ── text generation ──────────────────────────────────────────────────────────


# A bullet character the model may prefix a line with despite being told not to.
_LEADING_BULLET = re.compile(r"^\s*(?:[-•▪◦*·]|\d+[.)])\s+")


def _polish(text: str, *, node: str, style: Optional[str] = None) -> str:
    """LLM-polish ``text`` if available, keeping only verifier-faithful output.

    ``style`` (from Setup) tunes the tone/length of the rewrite; the faithfulness guardrails
    are identical across styles. ``text`` is a newline-separated BULLET LIST, so a rewrite is
    only accepted when it comes back with the same number of lines — a model that merges or
    invents bullets would silently change the slide's structure, and the deterministic draft
    is already correct.
    """
    if not text:
        return text
    from studio.ai import client
    from studio.ai.verifier import allowed_numbers, verify_text

    allowed = allowed_numbers(text)
    system = _style_system(style)
    wanted = len(text.split("\n"))

    def call() -> Optional[str]:
        out = client.generate(system, text, tier="fast", node=node)
        if not out:
            return None
        clean, _ = verify_text(out, allowed)
        if not clean:
            return None
        lines = [_LEADING_BULLET.sub("", ln).strip() for ln in clean.split("\n") if ln.strip()]
        if len(lines) != wanted:
            logger.info("commentary: %s polish returned %d line(s) for %d bullet(s) — keeping "
                        "the deterministic draft", node, len(lines), wanted)
            return None
        return "\n".join(lines)

    return client.run_or_fallback(call, lambda: text)


def _topic_points(result, topic: str) -> List[str]:
    """Deterministic, fact-grounded commentary POINTS for a column/quadrant topic.

    One point per bullet — the deck renders each as its own bulleted paragraph, so they are
    kept as separate strings all the way through rather than joined into a paragraph.
    """
    from studio.narrate.commentary import build_commentary, build_initiatives, build_swot

    headline, points, actions = build_commentary(result)

    def by_label(*labels: str) -> List[str]:
        return [p["text"] for p in points if p["label"].rstrip(".") in labels]

    if topic == "reflections":
        return [headline] + by_label("Momentum", "Soft spots")[:2]
    if topic == "performance":
        return by_label("Momentum", "Soft spots", "Penetration")[:3] or [headline]
    if topic == "priorities":
        cards = build_initiatives(result)
        if cards:
            return [f"{c['title']} — {c['body']}" for c in cards[:3]]
        return actions[:3]
    if topic == "key_messages":
        return actions[:3] or [p["text"] for p in points[:2]] or [headline]
    if topic in ("strengths", "weaknesses", "opportunities", "threats"):
        swot = build_swot(result)
        return list(getattr(swot, topic, []) or [])[:3]
    return [headline]


def bullet_list(points: List[str]) -> str:
    """Fold commentary points into the one-bullet-per-LINE form the fill engine renders."""
    return "\n".join(p.strip() for p in points if p and p.strip())


def values(template: Template, result) -> Dict[str, Any]:
    """``{note-role: bullet list}`` for every commentary prose box in the deck.

    Each value is newline-separated — one bullet per line; the fill engine turns each line
    into its own bulleted paragraph.
    """
    out: Dict[str, Any] = {}
    targets = _prose_targets(template)
    if not targets:
        return out
    style = getattr(result, "style", "balanced")
    cache: Dict[str, str] = {}
    for t in targets:
        topic = t["topic"]
        if topic not in cache:
            try:
                base = bullet_list(_topic_points(result, topic))
                cache[topic] = _polish(base, node=f"commentary-{topic}", style=style) if base else ""
            except Exception as exc:  # noqa: BLE001 — commentary must never break the doc
                logger.warning("commentary: topic %s failed: %s", topic, exc)
                cache[topic] = ""
        if cache[topic]:
            out[_role(t["slide_idx"], t["shape_id"])] = cache[topic]
    logger.info("commentary: filled %d prose box(es) across %d topic(s)", len(out), len(cache))
    return out
