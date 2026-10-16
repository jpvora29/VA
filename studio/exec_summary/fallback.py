"""Deterministic findings — the structured fallback for every stage (design Section 8).

Same shape as a model answer (:class:`StageOutput`), written from the same evidence ids,
and passed through the same verifier. Used when AI is off (``STUDIO_AI=off``), when the
endpoint fails, when a payload exceeds its budget, or when an answer fails verification
twice. The wording follows the design's reusable commentary pattern (Section 13).
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from studio.exec_summary import classify as K
from studio.exec_summary.analysis import CountryAnalysis, ExecAnalysis, ProductAnalysis
from studio.exec_summary.evidence import EvidenceStore
from studio.exec_summary.schemas import ModelFinding, StageOutput, StageResult
from studio.exec_summary.whitespace import (
    FIT_QUALIFICATION,
    PATH_EXPAND,
    PATH_REBUILD,
    OpportunityCandidate,
)

_RULE_FOR_PATH = {PATH_EXPAND: "WS_EXPAND", PATH_REBUILD: "WS_REBUILD"}


class _Writer:
    """Looks up displays by metric and remembers which ids a sentence used."""

    def __init__(self, store: EvidenceStore, ids: Mapping[str, str]) -> None:
        self.store, self.ids, self.used = store, ids, []

    def has(self, *metrics: str) -> bool:
        return all(m in self.ids for m in metrics)

    def __call__(self, metric: str) -> str:
        eid = self.ids[metric]
        self.used.append(eid)
        return self.store.get(eid).display

    def cite(self, metric: str) -> None:
        """Cite a fact the sentence states in words rather than figures."""
        if metric in self.ids:
            self.used.append(self.ids[metric])

    def take(self) -> List[str]:
        used, self.used = list(dict.fromkeys(self.used)), []
        return used


def _finding(rule: str, severity: str, statement: str, ids: Sequence[str], *,
             interpretation: str = "", recommendation: str = "",
             qualifications: Sequence[str] = ()) -> ModelFinding:
    return ModelFinding(rule_id=rule, severity=severity, statement=statement,
                        interpretation=interpretation, recommendation=recommendation,
                        evidence_ids=list(ids), qualifications=list(qualifications))


def _comparison(w: _Writer) -> str:
    """", against +6.0% for the peer average and +11.1% for the Marsh book" — what exists."""
    parts = []
    if w.has("peer_avg_yoy"):
        parts.append(f"{w('peer_avg_yoy')} for the peer average")
    if w.has("marsh_yoy"):
        parts.append(f"{w('marsh_yoy')} for the Marsh book")
    return (", against " + " and ".join(parts)) if parts else ""


def _position(w: _Writer, subject: str) -> str:
    return (f"{subject} carrier premium of {w('carrier_premium')} was {w('carrier_yoy')} "
            f"year on year{_comparison(w)}.")


def _share(w: _Writer, subject: str) -> Optional[str]:
    if not w.has("carrier_sow"):
        return None
    text = f"{subject} share of wallet is {w('carrier_sow')}"
    if w.has("sow_change"):
        text += f" ({w('sow_change')})"
    if w.has("peer_avg_sow"):
        text += f" against a peer average of {w('peer_avg_sow')}"
    return text + "."


def _severity(classification) -> Tuple[str, str]:
    if classification is not None and K.ATTENTION in classification.labels:
        return "PRODUCT_WEAKNESS", "attention"
    if classification is not None and K.STRENGTH in classification.labels:
        return "PRODUCT_STRENGTH", "strength"
    return "PRODUCT_POSITION", "context"


#: The facts a classification's stated basis quotes, so the basis can be cited.
_BASIS_FACTS = ("growth_gap_vs_marsh", "growth_gap_vs_peers", "sow_change", "carrier_sow",
                "peer_avg_sow")


def product_fallback(analysis: ExecAnalysis, ca: CountryAnalysis,
                     pa: ProductAnalysis) -> StageOutput:
    w = _Writer(analysis.evidence, pa.evidence)
    rule, severity = _severity(pa.classification)
    statement = _position(w, pa.product)
    reasons = pa.classification.reasons if pa.classification else ()
    basis_ids = [pa.evidence[m] for m in _BASIS_FACTS if reasons and m in pa.evidence]
    interpretation = "; ".join(reasons)
    findings = [_finding(rule, severity, statement, [*w.take(), *basis_ids],
                         interpretation=interpretation[:1].upper() + interpretation[1:])]
    share = _share(w, pa.product)
    if share:
        findings.append(_finding("PRODUCT_POSITION", "context", share, w.take()))
    if pa.survey_line is not None and pa.survey_evidence:
        sw = _Writer(analysis.evidence, pa.survey_evidence)
        text = f"The {pa.product} survey score is {sw('survey_score')}"
        if sw.has("survey_score_prior"):
            text += f" versus {sw('survey_score_prior')} a year earlier"
        if sw.has("survey_gap_vs_peers"):
            text += f", {sw('survey_gap_vs_peers')} against the peer average"
        findings.append(_finding("SURVEY_SIGNAL", "context", text + ".", sw.take()))
    return StageOutput(scope_id=pa.scope_id, findings=findings[:analysis.config.findings.product_max],
                       priority_refs=[], missing_references=[])


def _opportunity_finding(store: EvidenceStore, c: OpportunityCandidate) -> ModelFinding:
    w = _Writer(store, c.evidence)
    where = f" ({c.segment_detail} segment)" if c.segment_detail else ""
    if c.metrics.carrier_cur > 0:
        carrier = f"the carrier holds {w('carrier_premium')}, a {w('carrier_sow')} share of wallet"
    else:
        w.cite("carrier_premium")
        carrier = "the carrier places none of it through Marsh"
    statement = (f"Within {c.product} in {c.country}, {c.name}{where} has a Marsh book of "
                 f"{w('marsh_premium')} ({w('marsh_yoy')} year on year) while {carrier}.")
    return _finding(_RULE_FOR_PATH.get(c.path, "WS_DEVELOP"), "opportunity", statement,
                    w.take(), interpretation="A growing Marsh book with low carrier participation.",
                    recommendation=f"Review appetite, capacity and placement access for {c.name}.",
                    qualifications=c.qualifications or (FIT_QUALIFICATION,))


def opportunity_fallback(analysis: ExecAnalysis, ca: CountryAnalysis,
                         pa: ProductAnalysis) -> StageOutput:
    findings = [_opportunity_finding(analysis.evidence, c) for c in pa.shortlist]
    return StageOutput(scope_id=f"{pa.scope_id}/opportunity",
                       findings=findings[:analysis.config.findings.opportunity_max],
                       priority_refs=[], missing_references=[])


def _rescoped(result: StageResult, rule: str) -> Optional[ModelFinding]:
    """A verified child finding carried up under a parent rule id."""
    if not result.findings:
        return None
    f = result.findings[0]
    return _finding(rule, f.severity, f.statement, f.evidence_ids,
                    interpretation=f.interpretation, recommendation=f.recommendation,
                    qualifications=f.qualifications)


def country_fallback(analysis: ExecAnalysis, ca: CountryAnalysis,
                     children: Mapping[str, StageResult]) -> StageOutput:
    w = _Writer(analysis.evidence, ca.evidence)
    text = _position(w, f"In {ca.country}, the")
    text = text[0].upper() + text[1:]
    if w.has("carrier_sow"):
        text = text[:-1] + f"; share of wallet is {w('carrier_sow')}"
        if w.has("carrier_rank"):
            text += f" and rank is {w('carrier_rank')}"
        text += "."
    findings = [_finding("COUNTRY_PERFORMANCE", "context", text, w.take())]
    picks = [("COUNTRY_STRENGTH", K.STRENGTH), ("COUNTRY_WEAKNESS", K.ATTENTION)]
    for rule, label in picks:
        pa = next((p for p in ca.products if p.classification and label in p.classification.labels
                   and p.scope_id in children), None)
        carried = _rescoped(children[pa.scope_id], rule) if pa else None
        if carried:
            findings.append(carried)
    opp = next((children[f"{p.scope_id}/opportunity"] for p in ca.products
                if f"{p.scope_id}/opportunity" in children), None)
    carried = _rescoped(opp, "COUNTRY_OPPORTUNITY") if opp else None
    if carried:
        findings.append(carried)
    return StageOutput(scope_id=f"{ca.country}/country",
                       findings=findings[:analysis.config.findings.country_max],
                       priority_refs=[], missing_references=[])


def _product_extremes(analysis: ExecAnalysis) -> Tuple[Optional[str], Optional[str]]:
    """(largest product, the product growing furthest below its Marsh book)."""
    rows = analysis.product_totals
    if not rows:
        return None, None
    largest = rows[0].scope.product
    behind = [r for r in rows if r.growth_gap_marsh_pp is not None and r.growth_gap_marsh_pp < 0
              and r.scope.product != largest]
    worst = min(behind, key=lambda r: r.growth_gap_marsh_pp).scope.product if behind else None
    return largest, worst


def _joined(names: Sequence[str]) -> str:
    """"Singapore", "Singapore and Hong Kong", "Singapore, Japan and Hong Kong"."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def overall_fallback(analysis: ExecAnalysis, countries: Mapping[str, StageResult]) -> StageOutput:
    store, ctx = analysis.evidence, analysis.context
    w = _Writer(store, analysis.overall_evidence)
    where = _joined(ctx.countries)
    opener = ("Across " if ctx.multi_country else "In ") + where + ", " if where else ""
    lead = _position(w, f"{opener}Marsh-placed")
    share = _share(w, "Carrier")
    trajectory_ids = w.take()
    findings = [_finding("EXEC_TRAJECTORY", "context",
                         lead + (" " + share if share else ""), trajectory_ids)]
    if ctx.multi_country and analysis.countries:
        top = max(analysis.countries, key=lambda c: c.metrics.carrier_cur)
        cw = _Writer(store, top.evidence)
        findings.append(_finding(
            "EXEC_COUNTRY", "context",
            f"{top.country} is the largest market at {cw('carrier_premium')} "
            f"({cw('carrier_yoy')} year on year).", cw.take()))
    largest, worst = _product_extremes(analysis)
    if largest:
        pw = _Writer(store, analysis.product_total_evidence[largest])
        findings.append(_finding(
            "EXEC_STRENGTH", "strength",
            f"{largest} is the largest line at {pw('carrier_premium')}, "
            f"{pw('portfolio_mix')} of the portfolio.", pw.take()))
    if worst:
        pw = _Writer(store, analysis.product_total_evidence[worst])
        findings.append(_finding(
            "EXEC_WEAKNESS", "attention",
            f"{worst} needs attention: premium was {pw('carrier_yoy')} year on year against "
            f"{pw('marsh_yoy')} for the Marsh book.", pw.take()))
    if analysis.overall_survey_evidence:
        sw = _Writer(store, analysis.overall_survey_evidence)
        text = f"The carrier survey score is {sw('survey_score')}"
        if sw.has("survey_score_prior"):
            text += f" versus {sw('survey_score_prior')} a year earlier"
        if sw.has("survey_gap_vs_peers"):
            text += f", {sw('survey_gap_vs_peers')} against the peer average"
        findings.append(_finding("EXEC_SURVEY", "context", text + ".", sw.take()))
    best = sorted((c for ca in analysis.countries for c in ca.shortlist),
                  key=lambda c: c.ranking_keys())
    if best:
        # The opportunity closes the paragraph WITH its action — the design's
        # "[Action], subject to [qualification]"; the qualification is the action itself.
        opp = _opportunity_finding(store, best[0])
        findings.append(opp.model_copy(update={
            "rule_id": "EXEC_OPPORTUNITY",
            "statement": f"{opp.statement} {opp.recommendation[:-1]} before pursuing it."}))
    else:
        findings.append(_finding(
            "EXEC_ACTION", "context",
            "Review the weaker lines against their peer and Marsh book references before "
            "scaling placements.", trajectory_ids[:1]))
    cap = analysis.config.findings.overall_max
    if len(findings) > cap:          # keep the trajectory and the closing action
        findings = findings[:cap - 1] + findings[-1:]
    return StageOutput(scope_id="ALL/overall", findings=findings, priority_refs=[],
                       missing_references=[])
