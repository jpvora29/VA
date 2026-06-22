"""QBR story planner — `QBRContentSpec` → `DeckSpec`.

Selects slides from the canonical agenda based on the MATERIAL findings the
evidence builder produced (no fixed chart+table+SWOT sequence), makes every slide
decision-oriented, and closes with a decisions slide and an honest
methodology/limitations slide listing what the data could not support.

SWOT is intentionally omitted from the default flow (available as an optional
block); a decisions slide + initiative tracker carry more weight.
"""
from __future__ import annotations

from typing import Any, List

from studio.compute import OverallResult
from studio.content.model import AGENDA, AGENDA_LABEL, QBRContentSpec
from studio.deck.model import CardsBlock, ChartBlock, DeckSpec, KpiBlock, SlideSpec, TableBlock
from studio.page.format import money

# Dimensions already represented by a dedicated analytical finding, so the generic
# per-dimension breakdown loop skips them to avoid a duplicate slide.
_COVERED_BY_FINDING = {"Product_Line", "SIC_Major_Class"}
_BREAKDOWN_COLS = [
    {"key": "name", "label": "Segment", "align": "left"},
    {"key": "premium", "label": "GWP", "kind": "money", "align": "right"},
    {"key": "sow", "label": "Share of Wallet", "kind": "pct", "align": "right"},
    {"key": "yoy", "label": "YoY", "kind": "delta", "align": "right"},
]

_ACCENT = {
    "performance": "blue", "premium_movement": "navy", "portfolio_mix": "teal",
    "geo_industry": "green", "share_position": "blue", "whitespace": "amber",
    "risks": "amber", "decisions": "navy", "appendix": "navy",
}
_AGENDA_ORDER = [sid for sid, _ in AGENDA]

# Group the agenda into named chapters so the deck reads like a QBR (cover →
# agenda → SECTION dividers → slides → decisions) instead of one flat run of
# look-alike insight slides.
_CHAPTER = {
    "performance": "Performance",
    "premium_movement": "Performance",
    "portfolio_mix": "Portfolio & Mix",
    "geo_industry": "Portfolio & Mix",
    "share_position": "Position & Growth",
    "whitespace": "Position & Growth",
    "risks": "Risks & Outlook",
}
_CHAPTER_ORDER = ["Performance", "Portfolio & Mix", "Position & Growth", "Risks & Outlook"]
_CHAPTER_ACCENT = {
    "Performance": "blue", "Portfolio & Mix": "teal", "Position & Growth": "green",
    "Risks & Outlook": "amber", "Decisions & Next Steps": "navy",
}
_BREAKDOWN_CHAPTER = "Portfolio & Mix"
_DECISIONS_CHAPTER = "Decisions & Next Steps"


def _evidence_dicts(finding) -> List[dict]:
    return [{"label": e.label, "value": e.value, "detail": e.detail} for e in finding.evidence]


def _cover(spec) -> SlideSpec:
    line = f"{spec.carrier} — {spec.country}" if spec.country else spec.carrier
    return SlideSpec(layout="cover", eyebrow="QUARTERLY BUSINESS REVIEW", title=line,
                     subtitle=f"{spec.period} · Premium & Market Performance", accent="navy")


def _agenda_slide(chapters: List[str]) -> SlideSpec:
    pts = [{"label": f"{i:02d}", "text": ch, "tone": "neutral"} for i, ch in enumerate(chapters, 1)]
    return SlideSpec(layout="agenda", eyebrow="AGENDA", title="What we'll cover",
                     accent="navy", takeaways=pts)


def _divider_slide(title: str, number: int) -> SlideSpec:
    return SlideSpec(layout="divider", eyebrow=f"SECTION {number:02d}", title=title,
                     accent=_CHAPTER_ACCENT.get(title, "blue"))


def _exec(spec: QBRContentSpec, result: OverallResult) -> SlideSpec:
    points = [{"text": w, "tone": "neutral"} for w in spec.what_changed]
    actions = [{"tag": a.tag, "tone": a.tone, "title": a.title, "body": a.impact} for a in spec.actions]
    return SlideSpec(
        layout="exec", eyebrow="EXECUTIVE SUMMARY", title=spec.thesis, accent="blue",
        question="What is the story this quarter?",
        takeaways=points, blocks=[KpiBlock(result.kpis), CardsBlock(actions)],
        sources=list(spec.sources),
    )


def _finding_slide(finding, spec) -> SlideSpec:
    return SlideSpec(
        layout="insight",
        eyebrow=AGENDA_LABEL.get(finding.section, finding.section).upper(),
        title=finding.action_title,
        accent=_ACCENT.get(finding.section, "blue"),
        question=finding.question,
        implication=finding.implication,
        recommendation=finding.recommendation,
        owner=finding.owner, due_date=finding.due_date, confidence=finding.confidence,
        takeaways=list(finding.takeaways),
        blocks=[finding.visual] if finding.visual is not None else [],
        evidence=_evidence_dicts(finding),
        sources=list(finding.sources or spec.sources),
    )


def _decision_slide(spec: QBRContentSpec) -> SlideSpec:
    cols = [
        {"key": "tag", "label": "Move", "align": "left"},
        {"key": "title", "label": "Initiative", "align": "left"},
        {"key": "owner", "label": "Owner", "align": "left"},
        {"key": "due_date", "label": "Due", "align": "left"},
        {"key": "impact", "label": "Expected impact", "align": "left"},
    ]
    rows = [{"tag": a.tag, "title": a.title, "owner": a.owner, "due_date": a.due_date, "impact": a.impact} for a in spec.actions]
    return SlideSpec(
        layout="decision", eyebrow="DECISIONS & NEXT-QUARTER PRIORITIES",
        title="Three moves to grow and defend the book, with owners and timing",
        accent="navy", question="What are we deciding and who owns it?",
        takeaways=[{"label": "Decision.", "text": d, "tone": "neutral"} for d in spec.decisions],
        blocks=[TableBlock(cols, rows)] if rows else [],
        sources=list(spec.sources),
    )


def _breakdown_slide(bsec) -> SlideSpec:
    """A generic 'premium by <dimension>' slide for any breakdown the user selected
    (Country, Business Line, Cover Line, Client Segment, …) — the same chart+table+
    commentary treatment the hardcoded Product/Industry findings get."""
    from studio.narrate import breakdown_takeaways

    rows = sorted(bsec.rows, key=lambda r: r.get("premium") or 0, reverse=True)
    lead = rows[0] if rows else None
    top = rows[:8]
    title = (
        f"{lead['name']} leads {bsec.label.lower()} at {money(lead['premium'])}"
        if lead else f"Premium by {bsec.label}"
    )
    return SlideSpec(
        layout="insight",
        eyebrow=f"BREAKDOWN · {bsec.label.upper()}",
        title=title,
        accent="teal",
        question=f"How does premium split by {bsec.label.lower()}?",
        takeaways=breakdown_takeaways(bsec),
        blocks=[
            ChartBlock("bar", [r["name"] for r in top], [r["premium"] for r in top], f"Premium by {bsec.label}"),
            TableBlock(_BREAKDOWN_COLS, rows, hidden=bsec.hidden, title=f"{bsec.label} detail"),
        ],
        sources=["GPR — premium ledger"],
    )


def _methodology_slide(spec: QBRContentSpec) -> SlideSpec:
    gaps = [{"label": AGENDA_LABEL.get(g.section, g.section) + ".", "text": g.reason, "tone": "warn"} for g in spec.data_gaps]
    return SlideSpec(
        layout="methodology", eyebrow="APPENDIX · METHODOLOGY & DATA LIMITATIONS",
        title="What this QBR is built on — and what it cannot yet show",
        accent="navy", question="How reliable is this, and what is missing?",
        takeaways=gaps,
        meta={"sources": list(spec.sources)},
        sources=list(spec.sources),
    )


def plan_deck(spec: QBRContentSpec, result: OverallResult, *, report: str = "qbr") -> DeckSpec:
    cover, ex = _cover(spec), _exec(spec, result)

    if report == "exec":
        return DeckSpec(slides=[cover, ex], meta={**_meta(spec), "report": "exec"})

    # Tag every content slide with its chapter: material findings (canonical agenda
    # order) + a slide for every OTHER breakdown the user selected (Country, Business
    # Line, …) so the breakdown dropdown drives slides, not just Product.
    by_section = {f.section: f for f in spec.findings}
    tagged: List[tuple] = []  # (chapter, slide)
    for sid in _AGENDA_ORDER:
        if sid in by_section:
            tagged.append((_CHAPTER.get(sid, "Performance"), _finding_slide(by_section[sid], spec)))
    for bsec in result.breakdowns:
        if bsec.column in _COVERED_BY_FINDING or not bsec.rows:
            continue
        tagged.append((_BREAKDOWN_CHAPTER, _breakdown_slide(bsec)))

    has_decisions = bool(spec.actions or spec.decisions)
    present = [ch for ch in _CHAPTER_ORDER if any(c == ch for c, _ in tagged)]
    agenda_items = present + ([_DECISIONS_CHAPTER] if has_decisions else [])

    # Cover → Agenda → Executive summary → SECTION dividers + chapter slides.
    slides: List[SlideSpec] = [cover, _agenda_slide(agenda_items), ex]
    section_no = 0
    for ch in _CHAPTER_ORDER:
        chunk = [s for c, s in tagged if c == ch]
        if not chunk:
            continue
        section_no += 1
        slides.append(_divider_slide(ch, section_no))
        slides.extend(chunk)

    if has_decisions:
        section_no += 1
        slides.append(_divider_slide(_DECISIONS_CHAPTER, section_no))
        slides.append(_decision_slide(spec))
    if spec.data_gaps:
        slides.append(_methodology_slide(spec))

    return DeckSpec(slides=slides, meta={**_meta(spec), "report": "qbr"})


def _meta(spec: QBRContentSpec) -> dict:
    return {"carrier": spec.carrier, "country": spec.country, "year": spec.period,
            "title": f"{spec.carrier} — QBR"}
