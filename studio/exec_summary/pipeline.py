"""Build the Carrier Executive Summary deck — the business process, top to bottom.

    selection  ->  context  ->  premium cube  ->  peers  ->  deterministic analysis
               ->  product + opportunity stages  ->  country stages  ->  overall stage
               ->  slide content  ->  filled template  ->  audit sidecar

Everything before the stages is deterministic and is the source of truth; the stages only
write prose about it, and only verified prose reaches the slide.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from logger import get_logger
from studio.exec_summary.analysis import ExecAnalysis, analyse
from studio.exec_summary.config import ExecConfig, load_config
from studio.exec_summary.context import (
    COUNTRY_COL,
    YEAR_COL,
    AnalysisContext,
    build_analysis_context,
    with_countries,
    with_coverage,
)
from studio.exec_summary.coverage import detect_coverage
from studio.exec_summary.cube import carrier_countries, load_premium_cube
from studio.exec_summary.fill import fill_exec_summary
from studio.exec_summary.llm import StageModel, make_stage_model
from studio.exec_summary.peers import resolve_peer_sets
from studio.exec_summary.report import build_envelope, write_report
from studio.exec_summary.slides import build_slide_content
from studio.exec_summary.stages import CommentaryResult, StageEnv, write_commentary
from studio.exec_summary.survey import SurveySource, survey_source_from_result
from studio.exec_summary.verify import names_universe, other_carriers

logger = get_logger(__name__)


@dataclass(frozen=True)
class ExecSummaryResult:
    deck_path: str
    report_path: str
    analysis: ExecAnalysis
    commentary: CommentaryResult


def latest_year(result: Any) -> Optional[int]:
    """The latest year in the run's book — for a selection that pinned none."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    facts = compute_breakdown(PrimitiveArgs(flow=getattr(result, "flow", "gpr"), metric="premium",
                                            group_by=(YEAR_COL,), filters={}),
                              engine=result.engine)
    years = [int(f.dims[YEAR_COL]) for f in facts if str(f.dims.get(YEAR_COL, "")).isdigit()]
    return max(years) if years else None


def resolve_context(result: Any, data_basis: Optional[str]) -> AnalysisContext:
    filters = getattr(result, "resolved_filters", None) or {}
    year = None if filters.get(YEAR_COL) else latest_year(result)
    return build_analysis_context(result, data_basis=data_basis, latest_year=year)


def resolve_period(context: AnalysisContext, engine: Any) -> AnalysisContext:
    """Name and match the period the data really covers (H1, Q1, 9M … — see coverage)."""
    if context.period_relabelled:
        return context
    filters = dict(context.slice_filters)
    if context.countries:
        filters[COUNTRY_COL] = list(context.countries)
    return with_coverage(context, detect_coverage(engine, context.flow, filters,
                                                  context.current_year))


def build_stage_env(analysis: ExecAnalysis, cube, model: StageModel,
                    config: ExecConfig) -> StageEnv:
    return StageEnv(
        model=model, store=analysis.evidence, run_id=analysis.context.run_id,
        rule_version=config.rule_version, budgets=config.budgets,
        concurrency=config.budgets.concurrency,
        forbidden_names=frozenset(other_carriers(cube, analysis.context.carrier)),
        universe=frozenset(names_universe(cube)),
    )


def build_exec_summary(result: Any, *, out_path: str, data_basis: Optional[str] = None,
                       model: Optional[StageModel] = None, config: Optional[ExecConfig] = None,
                       survey_source: Optional[SurveySource] = None,
                       template_path: Optional[str] = None,
                       today: Optional[date] = None) -> ExecSummaryResult:
    """The whole executive summary for one Setup selection's ``OverallResult``."""
    config = config or load_config()
    context = resolve_period(resolve_context(result, data_basis), result.engine)
    cube = load_premium_cube(context, result.engine)
    if not context.countries:
        context = with_countries(context, carrier_countries(cube, context.carrier,
                                                            context.current_year))
    peer_sets = resolve_peer_sets(context, result.engine)
    survey = survey_source or (survey_source_from_result(result) if context.survey_on else None)
    analysis = analyse(context, cube, peer_sets, survey, config)

    stage_model = model or make_stage_model()
    env = build_stage_env(analysis, cube, stage_model, config)
    commentary = write_commentary(analysis, env)

    content = build_slide_content(analysis, commentary.overall, today=today)
    deck_path = fill_exec_summary(content, out_path, carrier_label=context.carrier,
                                  template_path=template_path)
    envelope = build_envelope(analysis, commentary, model_label=stage_model.label)
    report_path = write_report(deck_path, envelope)
    logger.info("exec summary %s: %s (%s, %d stages, %d from model)", context.run_id, deck_path,
                envelope["completeness_status"], envelope["coverage_summary"]["stages"],
                envelope["coverage_summary"]["stages_from_model"])
    return ExecSummaryResult(deck_path=deck_path, report_path=report_path, analysis=analysis,
                             commentary=commentary)
