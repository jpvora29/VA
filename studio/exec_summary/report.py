"""The ReportEnvelope sidecar — the audit trail written beside every deck (design Section 17).

``<deck>.pptx.exec.json`` holds what the slides cannot: the normalised context, the peer
set per country, rule and prompt versions, every stage result with its source (model or
fallback) and rejection reasons, the evidence each finding cites, and the full
opportunity register with every gate result.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from studio.exec_summary.analysis import ExecAnalysis
from studio.exec_summary.prompts import PROMPT_VERSION
from studio.exec_summary.schemas import SOURCE_MODEL, STATUS_COMPLETE, StageResult
from studio.exec_summary.stages import CommentaryResult
from studio.exec_summary.whitespace import OpportunityCandidate

SIDECAR_SUFFIX = ".exec.json"


def sidecar_path(deck_path: str) -> Path:
    return Path(f"{deck_path}{SIDECAR_SUFFIX}")


def completeness(results: List[StageResult], analysis: ExecAnalysis) -> str:
    """complete only when every stage verified complete AND no survey/peer gap exists."""
    stages_ok = all(r.status == STATUS_COMPLETE for r in results)
    peers_ok = all(c.peer_set.available for c in analysis.countries)
    survey_ok = (not analysis.context.survey_on) or (
        analysis.overall_survey is not None and analysis.overall_survey.status == STATUS_COMPLETE)
    return "complete" if stages_ok and peers_ok and survey_ok else "partial"


def _candidate_row(c: OpportunityCandidate) -> Dict[str, Any]:
    m = c.metrics
    return {
        "candidate_id": c.candidate_id, "country": c.country, "product": c.product,
        "view": c.view, "name": c.name, "path": c.path, "eligibility": c.eligibility,
        "segment_detail": c.segment_detail,
        "marsh_premium": m.marsh_cur, "marsh_prior": m.marsh_prior,
        "marsh_yoy_pct": m.marsh_growth.pct, "carrier_premium": m.carrier_cur,
        "carrier_sow_pct": m.sow_cur, "peer_avg_sow_pct": m.peer.sow_cur,
        "benchmark_headroom": c.benchmark_headroom,
        "gates": [{"gate": g.name, "passed": g.passed, "detail": g.detail} for g in c.gates],
        "qualifications": list(c.qualifications),
    }


def build_envelope(analysis: ExecAnalysis, commentary: CommentaryResult, *,
                   model_label: str) -> Dict[str, Any]:
    results = commentary.all_results()
    cited = sorted({eid for r in results for f in r.findings for eid in f.evidence_ids},
                   key=lambda e: int(e[1:]))
    ctx = analysis.context
    return {
        "run_id": ctx.run_id,
        "normalized_context": asdict(ctx),
        "peer_versions_by_country": {c.country: {"members": list(c.peer_set.members),
                                                 "source": c.peer_set.source}
                                     for c in analysis.countries},
        "rule_version": analysis.config.rule_version,
        "selection_rule_version": analysis.config.selection_rule_version,
        "prompt_version": PROMPT_VERSION,
        "model": model_label,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "completeness_status": completeness(results, analysis),
        "coverage_summary": {
            "countries": len(analysis.countries),
            "stages": len(results),
            "stages_from_model": sum(r.source == SOURCE_MODEL for r in results),
            "stages_fallback": sum(r.source != SOURCE_MODEL for r in results),
            "evidence_items": len(analysis.evidence),
            "survey": (analysis.overall_survey.status if analysis.overall_survey
                       else "not requested"),
            "opportunities_evaluated": len(analysis.register),
            "opportunities_qualified": sum(c.qualified for c in analysis.register),
        },
        "overall": commentary.overall.as_dict() if commentary.overall else None,
        "countries": [r.as_dict() for r in commentary.countries.values()],
        "children": [r.as_dict() for r in commentary.children.values()],
        "evidence": [analysis.evidence.get(e).as_dict() for e in cited],
        "opportunity_register": [_candidate_row(c) for c in analysis.register],
    }


def write_report(deck_path: str, envelope: Dict[str, Any]) -> str:
    path = sidecar_path(deck_path)
    path.write_text(json.dumps(envelope, indent=1, default=str), encoding="utf-8")
    return str(path)


def read_report(deck_path: str) -> Optional[Dict[str, Any]]:
    path = sidecar_path(deck_path)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None
