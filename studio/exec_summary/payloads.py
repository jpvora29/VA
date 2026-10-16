"""Bounded, compact JSON payloads — the only thing a model ever sees (design Sections 18-19).

Each fact is written inline as ``"metric": "e17 | $39.9M"``: the evidence id the model must
cite sits beside the exact display string it must quote. Every payload records which ids
it exposed, so the verifier can reject a citation from another scope (a cross-country fact
is simply not in this payload's id set). Selection counts travel with every bounded list,
so the model can never mistake a shortlist for the whole universe.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from studio.exec_summary import classify as K
from studio.exec_summary.analysis import CountryAnalysis, ExecAnalysis, ProductAnalysis
from studio.exec_summary.evidence import EvidenceStore
from studio.exec_summary.schemas import (
    STAGE_COUNTRY,
    STAGE_OPPORTUNITY,
    STAGE_OVERALL,
    STAGE_PRODUCT,
    StageResult,
)
from studio.exec_summary.whitespace import OpportunityCandidate

# Which slice metrics a payload shows, in reading order. Anything else stays in the store.
SLICE_FACTS = ("carrier_premium", "carrier_premium_prior", "carrier_premium_change",
               "carrier_yoy", "marsh_premium", "marsh_yoy", "carrier_sow", "carrier_sow_prior",
               "sow_change", "carrier_rank", "rank_movement", "portfolio_mix",
               "peer_avg_premium", "peer_avg_yoy", "peer_avg_sow", "growth_gap_vs_marsh",
               "growth_gap_vs_peers")
INDUSTRY_FACTS = ("carrier_premium", "carrier_yoy", "marsh_premium", "marsh_yoy",
                  "carrier_sow", "sow_change", "portfolio_mix", "peer_avg_sow")
SURVEY_FACTS = ("survey_score", "survey_score_prior", "survey_movement", "survey_peer_avg",
                "survey_gap_vs_peers", "survey_gap_change", "survey_book_avg",
                "survey_gap_vs_book")

RULES_BY_STAGE: Mapping[str, Tuple[str, ...]] = {
    STAGE_PRODUCT: ("PRODUCT_STRENGTH", "PRODUCT_WEAKNESS", "PRODUCT_POSITION",
                    "SURVEY_SIGNAL", K.RULE_REL_UNDERPERF, K.RULE_SHARED_PRESSURE,
                    K.RULE_GROW_BELOW_MARSH, K.RULE_OUTPERFORM, K.RULE_IN_LINE,
                    K.RULE_SURVEY_WEAK_TOO, K.RULE_SURVEY_STRONG),
    STAGE_OPPORTUNITY: ("WS_EXPAND", "WS_REBUILD", "WS_DEVELOP"),
    STAGE_COUNTRY: ("COUNTRY_PERFORMANCE", "COUNTRY_STRENGTH", "COUNTRY_WEAKNESS",
                    "COUNTRY_SURVEY", "COUNTRY_OPPORTUNITY"),
    STAGE_OVERALL: ("EXEC_TRAJECTORY", "EXEC_COUNTRY", "EXEC_STRENGTH", "EXEC_WEAKNESS",
                    "EXEC_SURVEY", "EXEC_OPPORTUNITY", "EXEC_ACTION"),
}


@dataclass
class StagePayload:
    stage: str
    scope_id: str
    data: dict
    allowed_ids: Set[str] = field(default_factory=set)
    context_text: List[str] = field(default_factory=list)   # figures allowed uncited
    max_findings: int = 3
    min_findings: int = 1
    child_refs: Tuple[str, ...] = ()

    @property
    def allowed_rules(self) -> Tuple[str, ...]:
        return RULES_BY_STAGE[self.stage]

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))


class _Facts:
    """Collects inline facts and the ids they expose, for one payload."""

    def __init__(self, store: EvidenceStore) -> None:
        self.store = store
        self.ids: Set[str] = set()

    def pick(self, ids: Mapping[str, str], keys: Sequence[str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key in keys:
            eid = ids.get(key)
            item = self.store.get(eid) if eid else None
            if item is not None:
                out[key] = f"{eid} | {item.display}"
                self.ids.add(eid)
        return out

    def cite(self, ids: Iterable[str]) -> Dict[str, str]:
        """Evidence ids from a child finding, each with its display, for re-quoting."""
        out: Dict[str, str] = {}
        for eid in ids:
            item = self.store.get(eid)
            if item is not None:
                out[eid] = f"{item.metric_id} | {item.scope_label} | {item.display}"
                self.ids.add(eid)
        return out


def _context(analysis: ExecAnalysis, **extra) -> dict:
    ctx = analysis.context
    base = {"carrier": ctx.carrier, "period": f"{ctx.current_label} vs {ctx.prior_label}",
            "currency": ctx.currency}
    base.update({k: v for k, v in extra.items() if v not in (None, "", [], ())})
    return base


def _context_text(analysis: ExecAnalysis, *more: str) -> List[str]:
    ctx = analysis.context
    return [ctx.current_label, ctx.prior_label, str(ctx.current_year), str(ctx.prior_year),
            *more]


def _status(classification) -> dict:
    if classification is None:
        return {}
    return {"labels": list(classification.labels), "pattern": classification.pattern,
            "survey_rule": classification.survey_rule or "none",
            "basis": list(classification.reasons)}


def _survey_block(facts: _Facts, ca: CountryAnalysis, pa: Optional[ProductAnalysis],
                  analysis: ExecAnalysis) -> dict:
    survey = ca.survey
    if survey is None or not survey.available:
        return {"grain": "unavailable", "reason": survey.note if survey else "not requested"}
    block: dict = {"scale": f"0 to {survey.scale_max:g}",
                   "wave": f"{survey.year} vs {survey.prior_year or 'none'}"}
    if pa is not None and pa.survey_evidence:
        block["grain"] = "product practice"
        block["product"] = facts.pick(pa.survey_evidence, SURVEY_FACTS)
    else:
        block["grain"] = "country only (context, not product-specific)"
    block["country"] = facts.pick(ca.survey_evidence, SURVEY_FACTS)
    keys = ("survey_score", "survey_gap_vs_peers", "survey_movement")
    block["best_attributes"] = {name: facts.pick(ca.attribute_evidence[name], keys)
                                for name in ca.best_attributes}
    block["weakest_attributes"] = {name: facts.pick(ca.attribute_evidence[name], keys)
                                   for name in ca.weakest_attributes}
    return block


def product_payload(analysis: ExecAnalysis, ca: CountryAnalysis,
                    pa: ProductAnalysis) -> StagePayload:
    cfg = analysis.config
    facts = _Facts(analysis.evidence)
    sel = pa.selection
    industries = [{"name": row.scope.industry, "views": list(sel.labels[row.scope.industry]),
                   **facts.pick(pa.industry_evidence[row.scope.industry], INDUSTRY_FACTS)}
                  for row in sel.rows]
    segments = [{"name": row.scope.segment,
                 **facts.pick(pa.segment_evidence[row.scope.segment], INDUSTRY_FACTS)}
                for row in sorted(pa.segments, key=lambda r: -r.carrier_cur)[:6]]
    data = {
        "stage": STAGE_PRODUCT, "scope_id": pa.scope_id,
        "context": _context(analysis, country=ca.country, product=pa.product,
                            peer_set=f"{len(ca.peer_set.members)} approved peers in {ca.country}"),
        "country_totals": facts.pick(ca.evidence, ("carrier_premium", "marsh_premium")),
        "product": facts.pick(pa.evidence, SLICE_FACTS),
        "status": _status(pa.classification),
        "survey": _survey_block(facts, ca, pa, analysis),
        "industries": {"rule": sel.rule_version,
                       "counts": {"total": sel.total, "eligible": sel.eligible,
                                  "selected": len(sel.rows), "omitted": sel.omitted},
                       "top3": list(sel.top), "bottom3": list(sel.bottom), "rows": industries},
        "segments": segments,
        "allowed_rule_ids": list(RULES_BY_STAGE[STAGE_PRODUCT]),
    }
    return StagePayload(STAGE_PRODUCT, pa.scope_id, data, facts.ids,
                        _context_text(analysis), max_findings=cfg.findings.product_max)


def _candidate(facts: _Facts, c: OpportunityCandidate) -> dict:
    return {
        "candidate_id": c.candidate_id, "view": c.view, "name": c.name, "path": c.path,
        "fit": c.eligibility, "segment_detail": c.segment_detail or "not measured",
        "gates_passed": [g.name for g in c.gates if g.passed],
        "facts": facts.pick(c.evidence, ("marsh_premium", "marsh_premium_prior", "marsh_yoy",
                                         "carrier_premium", "carrier_sow", "peer_avg_sow")),
        "qualifications": list(c.qualifications),
    }


def opportunity_payload(analysis: ExecAnalysis, ca: CountryAnalysis,
                        pa: ProductAnalysis) -> Optional[StagePayload]:
    """``None`` when the product has no qualified candidate — no call is made."""
    if not pa.shortlist:
        return None
    cfg = analysis.config
    facts = _Facts(analysis.evidence)
    scope_id = f"{pa.scope_id}/opportunity"
    data = {
        "stage": STAGE_OPPORTUNITY, "scope_id": scope_id,
        "context": _context(analysis, country=ca.country, product=pa.product),
        "product_status": _status(pa.classification),
        "product": facts.pick(pa.evidence, ("carrier_premium", "carrier_sow", "carrier_yoy",
                                            "marsh_yoy")),
        "survey": _survey_block(facts, ca, pa, analysis),
        "candidates": [_candidate(facts, c) for c in pa.shortlist],
        "counts": {"evaluated": len(pa.candidates),
                   "qualified": sum(c.qualified for c in pa.candidates),
                   "sent": len(pa.shortlist)},
        "allowed_rule_ids": list(RULES_BY_STAGE[STAGE_OPPORTUNITY]),
    }
    return StagePayload(STAGE_OPPORTUNITY, scope_id, data, facts.ids, _context_text(analysis),
                        max_findings=cfg.findings.opportunity_max)


def _child(facts: _Facts, result: StageResult) -> dict:
    return {"ref": result.scope_id, "stage": result.stage,
            "findings": [{"severity": f.severity, "statement": f.statement,
                          "evidence": facts.cite(f.evidence_ids)} for f in result.findings]}


def _ordered_products(ca: CountryAnalysis, n: int) -> Tuple[list, list]:
    leaders = sorted(ca.products, key=lambda p: -p.metrics.carrier_cur)[:n]
    weak = sorted((p for p in ca.products if p.classification and
                   K.ATTENTION in p.classification.labels and p not in leaders),
                  key=lambda p: -K.adversity_score(p.metrics))[:n]
    weak_in_leaders = [p for p in leaders if p.classification and
                       K.ATTENTION in p.classification.labels]
    return leaders, (weak_in_leaders + weak)[:n]


def country_payload(analysis: ExecAnalysis, ca: CountryAnalysis,
                    children: Mapping[str, StageResult]) -> StagePayload:
    cfg = analysis.config
    facts = _Facts(analysis.evidence)
    leaders, weak = _ordered_products(ca, cfg.shortlist.products_per_side)
    picked = {p.scope_id: p for p in [*leaders, *weak]}
    child_results = [children[sid] for sid in picked if sid in children and children[sid].findings]
    opps = [children[f"{p.scope_id}/opportunity"] for p in ca.products
            if f"{p.scope_id}/opportunity" in children
            and children[f"{p.scope_id}/opportunity"].findings]
    scope_id = f"{ca.country}/country"
    data = {
        "stage": STAGE_COUNTRY, "scope_id": scope_id,
        "context": _context(analysis, country=ca.country,
                            peer_set=f"{len(ca.peer_set.members)} approved peers in {ca.country}"),
        "country": facts.pick(ca.evidence, SLICE_FACTS),
        "status": _status(ca.classification),
        "survey": _survey_block(facts, ca, None, analysis),
        "leading_products": [p.product for p in leaders],
        "weak_products": [p.product for p in weak],
        "product_findings": [_child(facts, r) for r in child_results],
        "opportunity_findings": [_child(facts, r) for r in opps][:cfg.shortlist.opportunities_per_country],
        "counts": {"products": len(ca.products), "products_sent": len(child_results),
                   "opportunity_results": len(opps)},
        "allowed_rule_ids": list(RULES_BY_STAGE[STAGE_COUNTRY]),
    }
    return StagePayload(STAGE_COUNTRY, scope_id, data, facts.ids, _context_text(analysis),
                        max_findings=cfg.findings.country_max,
                        child_refs=tuple(r.scope_id for r in [*child_results, *opps]))


def _ordered_countries(analysis: ExecAnalysis, n: int) -> Tuple[list, list]:
    leaders = sorted(analysis.countries, key=lambda c: -c.metrics.carrier_cur)[:n]
    weak = sorted(analysis.countries, key=lambda c: -K.adversity_score(c.metrics))
    weak = [c for c in weak if K.adverse_reasons(c.metrics, analysis.config.materiality)][:n]
    return leaders, weak


def overall_payload(analysis: ExecAnalysis, countries: Mapping[str, StageResult],
                    products: Mapping[str, StageResult]) -> StagePayload:
    cfg = analysis.config
    facts = _Facts(analysis.evidence)
    leaders, weak = _ordered_countries(analysis, cfg.shortlist.countries_per_side)
    chosen = list({c.country: c for c in [*leaders, *weak]}.values())
    country_results = [countries[f"{c.country}/country"] for c in chosen
                       if f"{c.country}/country" in countries]
    # Product evidence across the whole run, so the summary can name the strongest and
    # weakest lines with their basis even in a one-country deck.
    totals = {p.scope.product: facts.pick(analysis.product_total_evidence[p.scope.product],
                                          ("carrier_premium", "carrier_yoy", "carrier_sow",
                                           "portfolio_mix", "marsh_yoy"))
              for p in analysis.product_totals[:6]}
    opportunities = sorted((c for ca in analysis.countries for c in ca.shortlist),
                           key=lambda c: c.ranking_keys())[:cfg.shortlist.opportunities_per_country]
    data = {
        "stage": STAGE_OVERALL, "scope_id": "ALL/overall",
        "context": _context(analysis, countries=list(analysis.context.countries)),
        "overall": facts.pick(analysis.overall_evidence, SLICE_FACTS),
        "status": _status(analysis.overall_classification),
        "survey": (facts.pick(analysis.overall_survey_evidence, SURVEY_FACTS)
                   if analysis.overall_survey_evidence else
                   {"grain": "unavailable",
                    "reason": analysis.overall_survey.note if analysis.overall_survey
                    else "survey not in the run's data basis"}),
        "products_all_countries": totals,
        "country_totals": {
            c.country: facts.pick(c.evidence, ("carrier_premium", "carrier_yoy", "marsh_yoy",
                                               "carrier_sow", "sow_change", "rank_movement"))
            for c in sorted(analysis.countries, key=lambda c: -c.metrics.carrier_cur)[:6]},
        "leading_countries": [c.country for c in leaders],
        "weak_countries": [c.country for c in weak],
        "country_findings": [_child(facts, r) for r in country_results],
        "top_opportunities": [{"country": c.country, "product": c.product,
                               **_candidate(facts, c)} for c in opportunities],
        "counts": {"countries": len(analysis.countries),
                   "countries_sent": len(country_results),
                   "opportunities_qualified": sum(c.qualified for c in analysis.register)},
        "allowed_rule_ids": list(RULES_BY_STAGE[STAGE_OVERALL]),
    }
    return StagePayload(STAGE_OVERALL, "ALL/overall", data, facts.ids,
                        _context_text(analysis, str(len(analysis.countries))),
                        max_findings=cfg.findings.overall_max,
                        min_findings=min(cfg.findings.overall_min, 2),
                        child_refs=tuple(r.scope_id for r in country_results))


def token_count(text: str) -> int:
    """Tokens as the GPT-5 family counts them (o200k); a char estimate if unavailable."""
    try:
        import tiktoken

        return len(tiktoken.get_encoding("o200k_base").encode(text))
    except Exception:  # noqa: BLE001 — a budget estimate must never break a build
        return len(text) // 4


def trim_for_budget(payload: StagePayload, system: str, budget: int) -> Optional[StagePayload]:
    """Drop optional blocks (segments, attribute lists) until the call fits; ``None`` if it
    still does not — the caller then uses the structured fallback (design Section 19)."""
    optional = (("segments",), ("survey", "best_attributes"), ("survey", "weakest_attributes"),
                ("industries", "rows"))
    for path in (None, *optional):
        if path is not None:
            node = payload.data
            for key in path[:-1]:
                node = node.get(key, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict) and path[-1] in node:
                if path == ("industries", "rows"):
                    return None          # required facts: never silently truncated
                node.pop(path[-1])
        if token_count(system) + token_count(payload.to_json()) <= budget:
            return payload
    return None
