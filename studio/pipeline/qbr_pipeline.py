"""QBR deck pipeline — the readable end-to-end orchestration (plan §Pipeline Style).

    Structured SQL output -> EvidencePack -> Evidence graph -> ReportPlan
      -> TemplateDescriptor -> LayoutIntent -> BindingMap -> RenderPlan
      -> QAReport -> PowerPoint deck

Each step is a small named function testable on its own; the pipeline function
just calls them in order. Independent work (layout labelling, per-slide
commentary drafting) runs in parallel with deterministic result ordering.
Deterministic code is the authority throughout — the LLM (when enabled) only
refines labels and wording behind validators. Export fails safe: a critical QA
failure returns the report with no deck path instead of inventing content.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from logger import get_logger
from studio.commentary import (
    CommentaryPlan,
    SlideCommentary,
    build_commentary_plan,
    draft_and_verify_commentary,
)
from studio.content.evidence_builder import build_evidence_pack
from studio.content.evidence_graph import EvidenceGraph, build_evidence_graph
from studio.content.evidence_pack import EvidencePack
from studio.content.model import DataGap
from studio.content.report_plan import (
    Claim,
    Finding,
    Importance,
    ReportPlan,
    decide_placement,
)
from studio.pipeline.async_utils import run_sync
from studio.qa import QAReport, run_qbr_qa
from studio.template_intelligence import (
    BindingMapV2,
    LayoutIntent,
    TemplateDescriptor,
    detect_layout_intent,
    parse_template,
    validate_or_create_binding_map,
)

logger = get_logger(__name__)

_YEAR_COL = "Year"
_COUNTRY_COL = "Country"

# Slide purposes that carry evidence-grounded commentary.
_COMMENTARY_PURPOSES = frozenset({
    "executive_summary", "trading_summary", "product_deep_dive",
    "country_view", "swot", "growth", "ranking",
})


# ── contracts ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StudioSelection:
    """What the user asked for: filters + template (+ output location)."""

    filters: Mapping[str, Any] = field(default_factory=dict)
    template_path: Optional[str] = None            # None → active template
    out_path: Optional[str] = None                 # None → outputs/<auto>.pptx
    audience: str = "carrier_leadership"
    report_type: str = "full_qbr"


@dataclass(frozen=True)
class RenderPlan:
    """The deck population plan: the TemplateDoc + its materialized fields."""

    doc: Dict[str, Any]
    fields: Dict[str, Dict[str, Any]]
    hidden_slides: Tuple[int, ...] = ()


@dataclass(frozen=True)
class QBRPipelineResult:
    deck_path: Optional[str]
    qa_report: QAReport
    commentary: Tuple[SlideCommentary, ...] = ()
    render_plan: Optional[RenderPlan] = None
    evidence_pack: Optional[EvidencePack] = None
    evidence_graph: Optional[EvidenceGraph] = None
    report_plan: Optional[ReportPlan] = None
    layout_intent: Optional[LayoutIntent] = None
    binding_map: Optional[BindingMapV2] = None


# ── step 1: structured SQL output ─────────────────────────────────────────────


async def load_structured_sql_output(selection: StudioSelection):
    """Run the deterministic compute layer (engine-bound → worker thread)."""
    from studio.compute import compute_overall

    return await asyncio.to_thread(compute_overall, filters=dict(selection.filters))


def _reporting_year(result) -> Optional[int]:
    year = (result.resolved_filters or {}).get(_YEAR_COL)
    if isinstance(year, (list, tuple, set)):
        year = max(int(y) for y in year) if year else None
    return int(year) if year is not None else None


def _country(result) -> Optional[str]:
    val = (result.resolved_filters or {}).get(_COUNTRY_COL)
    if isinstance(val, (list, tuple, set)):
        return str(next(iter(sorted(str(v) for v in val)))) if val else None
    return str(val) if val else None


# ── step 2: evidence ──────────────────────────────────────────────────────────


def build_evidence(result) -> EvidencePack:
    return build_evidence_pack(
        result, carrier=result.subject, country=_country(result),
        year=_reporting_year(result),
    )


# ── step 3: report plan (the business argument) ───────────────────────────────


def _fact_ids(pack: EvidencePack, measure: str, *, total_only: bool = False) -> List[str]:
    return [
        fid for fid, item in sorted(pack.items.items())
        if item.measure == measure and (not total_only or item.dims.get("scope") == "total")
    ]


def build_report_plan(
    pack: EvidencePack, graph: EvidenceGraph, selection: StudioSelection
) -> ReportPlan:
    """Deterministic argument construction: findings with claims citing fact ids."""
    findings: List[Finding] = []

    totals = _fact_ids(pack, "premium_total")
    move_pct = _fact_ids(pack, "premium_movement_pct", total_only=True)
    move_abs = _fact_ids(pack, "premium_movement", total_only=True)
    if totals:
        pct_item = pack.items[move_pct[0]] if move_pct else None
        severity = min(1.0, abs(pct_item.value) / 100.0) if pct_item else 0.2
        imp = Importance(financial_materiality=0.9, change_severity=severity,
                         strategic_relevance=0.6, actionability=0.4)
        obs = Claim(
            text=f"{pack.subject} premium moved "
                 f"{pct_item.rendered if pct_item else 'vs prior period'} in {pack.period}.",
            claim_type="observation",
            fact_ids=tuple(totals + move_pct + move_abs),
        )
        findings.append(Finding(section="performance", claims=(obs,), importance=imp,
                                placement=decide_placement(imp)))

    dim_moves = [
        fid for fid in _fact_ids(pack, "premium_movement")
        if pack.items[fid].dims.get("scope") != "total"
    ]
    if dim_moves and move_abs:
        top = max(dim_moves, key=lambda f: abs(pack.items[f].value))
        imp = Importance(financial_materiality=0.7, change_severity=0.6,
                         strategic_relevance=0.5, actionability=0.5)
        drv = Claim(
            text="The movement decomposes across product lines; the largest "
                 f"contribution is {pack.items[top].rendered}.",
            claim_type="driver",
            fact_ids=(top,) + tuple(move_abs),
        )
        findings.append(Finding(section="premium_movement", claims=(drv,), importance=imp,
                                placement=decide_placement(imp)))

    whitespace = _fact_ids(pack, "whitespace_market")
    if whitespace:
        imp = Importance(financial_materiality=0.5, change_severity=0.1,
                         strategic_relevance=0.8, actionability=0.9)
        rec = Claim(
            text="Material whitespace exists in industries the market writes "
                 "but the carrier does not.",
            claim_type="recommendation",
            fact_ids=tuple(whitespace[:3]),
        )
        findings.append(Finding(section="whitespace", claims=(rec,), importance=imp,
                                placement=decide_placement(imp)))

    return ReportPlan(
        report_type=selection.report_type,
        audience=selection.audience,
        subject=pack.subject,
        country=pack.country,
        period=pack.period,
        comparison_period=pack.comparison_period,
        findings=tuple(findings),
        data_gaps=tuple(DataGap(c.section, c.reason) for c in pack.gaps()),
    )


# ── steps 4–6: template understanding ─────────────────────────────────────────


def _resolve_template_path(selection: StudioSelection) -> str:
    if selection.template_path:
        return selection.template_path
    from studio.template_fill.registry import active_template_path

    return active_template_path()


# ── step 7: render plan ───────────────────────────────────────────────────────


def build_render_plan(result, template_path: str) -> RenderPlan:
    """Resolve the TemplateDoc against the template (the proven fill path)."""
    from studio.template_fill.model import materialize_fields, new_template_doc

    doc = new_template_doc(result, template_path=template_path)
    return RenderPlan(doc=doc, fields=materialize_fields(doc),
                      hidden_slides=tuple(doc.get("hidden", [])))


# ── step 8: commentary targets from layout intent ─────────────────────────────


def commentary_targets(
    layout_intent: LayoutIntent, render_plan: RenderPlan
) -> List[Tuple[int, str]]:
    """(slide_idx, purpose) for every visible commentary-bearing slide."""
    hidden = set(render_plan.hidden_slides)
    return [
        (p.slide_idx, p.purpose)
        for p in layout_intent.slides
        if p.purpose in _COMMENTARY_PURPOSES and p.slide_idx not in hidden
    ]


def apply_commentary(render_plan: RenderPlan, commentary: Sequence[SlideCommentary]) -> RenderPlan:
    """Write verified commentary into the doc's prose (note:) slots per slide.

    Only replaces slots the fill layer already carved out (`note:<slide>:<shape>:<para>`),
    so template geometry is untouched; slides with no prose slot keep their
    commentary in the QA record only.
    """
    from studio.template_fill.model import materialize_fields

    by_slide = {c.slide_idx: c for c in commentary if c.sentences}
    if not by_slide:
        return render_plan
    doc = dict(render_plan.doc)
    values = dict(doc.get("values", {}))
    replaced = 0
    for role, current in sorted(values.items()):
        if not role.startswith("note:"):
            continue
        try:
            slide_idx = int(role.split(":")[1])
        except (IndexError, ValueError):
            continue
        slide_commentary = by_slide.get(slide_idx)
        # Only the primary paragraph (non-empty value) carries prose; blanked
        # paragraphs stay blank.
        if slide_commentary is None or not str(current).strip():
            continue
        values[role] = slide_commentary.text
        replaced += 1
    doc["values"] = values
    logger.info("pipeline: verified commentary applied to %d prose slot(s)", replaced)
    return RenderPlan(doc=doc, fields=materialize_fields(doc),
                      hidden_slides=render_plan.hidden_slides)


# ── step 9: QA + export ───────────────────────────────────────────────────────


def _banned_peer_names(result) -> Tuple[str, ...]:
    """The subject's peer carriers — never nameable in carrier-facing output."""
    try:
        from studio.data import peer_members

        subject = result.subject or ""
        return tuple(n for n in peer_members(result.flow, subject) if n and n != subject)
    except Exception:  # noqa: BLE001 — no peer table is not an error
        return ()


def export_qbr_deck(
    render_plan: RenderPlan, qa_report: QAReport, selection: StudioSelection
) -> Optional[str]:
    """Write the deck — unless QA found a critical failure (fail safe)."""
    if qa_report.blocking:
        logger.warning("pipeline: export blocked by %d critical QA issue(s)",
                       len(qa_report.criticals()))
        return None
    from studio.template_fill.fill import fill_template

    out = selection.out_path or str(
        Path("outputs") / f"qbr_pipeline_{time.strftime('%Y%m%d_%H%M%S')}.pptx")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    return fill_template(render_plan.doc, out_path=out)


# ── the pipeline ──────────────────────────────────────────────────────────────


async def build_qbr_deck_pipeline(selection: StudioSelection) -> QBRPipelineResult:
    """The whole flow, one readable sequence (plan §Pipeline Style)."""
    sql_output = await load_structured_sql_output(selection)
    evidence_pack = build_evidence(sql_output)
    evidence_graph = build_evidence_graph(evidence_pack)

    template_path = _resolve_template_path(selection)
    template_descriptor = await asyncio.to_thread(parse_template, template_path)

    # Layout labelling (may call the LLM) and the render plan (engine-bound) are
    # independent — run them together; result order is fixed by position.
    layout_intent, render_plan = await asyncio.gather(
        detect_layout_intent(template_descriptor),
        asyncio.to_thread(build_render_plan, sql_output, template_path),
    )

    binding_map, binding_issues = validate_or_create_binding_map(
        template_descriptor, layout_intent, template_path=template_path)

    report_plan = build_report_plan(evidence_pack, evidence_graph, selection)

    commentary_plan: CommentaryPlan = build_commentary_plan(
        evidence_pack, evidence_graph, commentary_targets(layout_intent, render_plan))
    banned = _banned_peer_names(sql_output)
    commentary = await draft_and_verify_commentary(
        commentary_plan, evidence_pack, forbidden_names=banned)

    render_plan = apply_commentary(render_plan, commentary)

    qa_report = run_qbr_qa(
        fields=render_plan.fields, values=render_plan.doc.get("values", {}),
        commentary=commentary, pack=evidence_pack,
        binding_map=binding_map, descriptor=template_descriptor,
        hidden_slides=render_plan.hidden_slides, banned_names=banned,
    )

    deck_path = await asyncio.to_thread(export_qbr_deck, render_plan, qa_report, selection)

    return QBRPipelineResult(
        deck_path=deck_path, qa_report=qa_report, commentary=commentary,
        render_plan=render_plan, evidence_pack=evidence_pack,
        evidence_graph=evidence_graph, report_plan=report_plan,
        layout_intent=layout_intent, binding_map=binding_map,
    )


def build_qbr_deck(selection: StudioSelection) -> QBRPipelineResult:
    """Synchronous wrapper for Dash callbacks and other non-async entrypoints."""
    return run_sync(build_qbr_deck_pipeline(selection))
