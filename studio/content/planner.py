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
from studio.deck.model import CardsBlock, DeckSpec, KpiBlock, SlideSpec, TableBlock

_ACCENT = {
    "performance": "blue", "premium_movement": "navy", "portfolio_mix": "teal",
    "geo_industry": "green", "share_position": "blue", "whitespace": "amber",
    "risks": "amber", "decisions": "navy", "appendix": "navy",
}
_AGENDA_ORDER = [sid for sid, _ in AGENDA]


def _evidence_dicts(finding) -> List[dict]:
    return [{"label": e.label, "value": e.value, "detail": e.detail} for e in finding.evidence]


def _cover(spec) -> SlideSpec:
    line = f"{spec.carrier} — {spec.country}" if spec.country else spec.carrier
    return SlideSpec(layout="cover", eyebrow="QUARTERLY BUSINESS REVIEW", title=line,
                     subtitle=f"{spec.period} · Premium & Market Performance", accent="navy")


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
    slides: List[SlideSpec] = [_cover(spec), _exec(spec, result)]

    if report == "exec":
        return DeckSpec(slides=slides, meta={**_meta(spec), "report": "exec"})

    # Material findings, in canonical agenda order.
    by_section = {f.section: f for f in spec.findings}
    for sid in _AGENDA_ORDER:
        if sid in by_section:
            slides.append(_finding_slide(by_section[sid], spec))

    if spec.actions or spec.decisions:
        slides.append(_decision_slide(spec))
    if spec.data_gaps:
        slides.append(_methodology_slide(spec))

    return DeckSpec(slides=slides, meta={**_meta(spec), "report": "qbr"})


def _meta(spec: QBRContentSpec) -> dict:
    return {"carrier": spec.carrier, "country": spec.country, "year": spec.period,
            "title": f"{spec.carrier} — QBR"}
