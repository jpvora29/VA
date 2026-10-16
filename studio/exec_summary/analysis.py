"""The deterministic analytical core — everything finishes here before any prose
(design Sections 8, 9).

:class:`ExecAnalysisBuilder` builds an :class:`ExecAnalysis` one part at a time; read
:func:`analyse` to see what the analysis contains, read one ``add_*`` to see how that part
is computed. Every figure a later stage may quote is registered in the evidence store here,
so the model can only ever cite numbers this module computed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Mapping, Optional

import pandas as pd

from studio.exec_summary import evidence as E
from studio.exec_summary.classify import Classification, classify
from studio.exec_summary.config import ExecConfig
from studio.exec_summary.context import AnalysisContext
from studio.exec_summary.metrics import Scope, SliceMetrics, slice_metrics
from studio.exec_summary.peers import PeerSet
from studio.exec_summary.selection import IndustrySelection, select_industries
from studio.exec_summary.survey import (
    ScoreLine,
    SurveySource,
    SurveySummary,
    country_survey,
    overall_survey,
    ranked_attributes,
)
from studio.exec_summary.whitespace import (
    PATH_DEVELOP,
    PATH_EXPAND,
    PATH_REBUILD,
    VIEW_INDUSTRY,
    VIEW_SEGMENT,
    OpportunityCandidate,
    qualify,
    shortlist,
)


@dataclass
class ProductAnalysis:
    country: str
    product: str
    metrics: SliceMetrics
    evidence: Dict[str, str]
    classification: Optional[Classification] = None
    industries: List[SliceMetrics] = field(default_factory=list)
    selection: Optional[IndustrySelection] = None
    industry_evidence: Dict[str, Dict[str, str]] = field(default_factory=dict)
    segments: List[SliceMetrics] = field(default_factory=list)
    segment_evidence: Dict[str, Dict[str, str]] = field(default_factory=dict)
    survey_line: Optional[ScoreLine] = None
    survey_evidence: Dict[str, str] = field(default_factory=dict)
    candidates: List[OpportunityCandidate] = field(default_factory=list)
    shortlist: List[OpportunityCandidate] = field(default_factory=list)

    @property
    def scope_id(self) -> str:
        return self.metrics.scope.scope_id


@dataclass
class CountryAnalysis:
    country: str
    metrics: SliceMetrics
    evidence: Dict[str, str]
    peer_set: PeerSet
    classification: Optional[Classification] = None
    products: List[ProductAnalysis] = field(default_factory=list)
    survey: Optional[SurveySummary] = None
    survey_evidence: Dict[str, str] = field(default_factory=dict)
    attribute_evidence: Dict[str, Dict[str, str]] = field(default_factory=dict)
    best_attributes: List[str] = field(default_factory=list)
    weakest_attributes: List[str] = field(default_factory=list)
    shortlist: List[OpportunityCandidate] = field(default_factory=list)


@dataclass
class ExecAnalysis:
    context: AnalysisContext
    config: ExecConfig
    evidence: E.EvidenceStore
    overall: Optional[SliceMetrics] = None
    overall_evidence: Dict[str, str] = field(default_factory=dict)
    overall_classification: Optional[Classification] = None
    overall_survey: Optional[SurveySummary] = None
    overall_survey_evidence: Dict[str, str] = field(default_factory=dict)
    countries: List[CountryAnalysis] = field(default_factory=list)
    product_totals: List[SliceMetrics] = field(default_factory=list)
    product_total_evidence: Dict[str, Dict[str, str]] = field(default_factory=dict)

    @property
    def register(self) -> List[OpportunityCandidate]:
        """Every evaluated candidate across the run — the full opportunity register."""
        return [c for country in self.countries for p in country.products for c in p.candidates]


# ── survey evidence ──────────────────────────────────────────────────────────


def add_survey_evidence(store: E.EvidenceStore, line: ScoreLine, scope_id: str, label: str,
                        period: str) -> Dict[str, str]:
    """Register a score line's score, movement and gaps (score points, never premium)."""
    ids: Dict[str, str] = {}
    pairs = (("survey_score", line.score, E.score), ("survey_score_prior", line.prior, E.score),
             ("survey_movement", line.movement, E.score_change),
             ("survey_peer_avg", line.peer_mean, E.score),
             ("survey_gap_vs_peers", line.peer_gap, E.score_change),
             ("survey_gap_change", line.gap_change, E.score_change),
             ("survey_book_avg", line.book_mean, E.score),
             ("survey_gap_vs_book", line.book_gap, E.score_change))
    for metric, value, fmt in pairs:
        if value is not None:
            ids[metric] = store.add(metric, scope_id, f"{line.name} ({label})", period,
                                    value, fmt(value), E.UNIT_SCORE)
    return ids


def _survey_period(summary: SurveySummary) -> str:
    return f"survey {summary.year}" + (f" vs {summary.prior_year}" if summary.prior_year else "")


# ── the builder ──────────────────────────────────────────────────────────────


class ExecAnalysisBuilder:
    """Builds an :class:`ExecAnalysis` one part at a time, over one premium cube."""

    def __init__(self, context: AnalysisContext, cube: pd.DataFrame,
                 peer_sets: Mapping[str, PeerSet], survey_source: Optional[SurveySource],
                 config: ExecConfig) -> None:
        self._ctx = context
        self._cube = cube
        self._peers = dict(peer_sets)
        self._survey = survey_source
        self._cfg = config
        self._result = ExecAnalysis(context=context, config=config, evidence=E.EvidenceStore())

    # small shared helpers -----------------------------------------------------

    def _metrics(self, scope: Scope, parent: Optional[float] = None,
                 parent_label: str = "") -> SliceMetrics:
        return slice_metrics(self._cube, scope, self._ctx.carrier, self._ctx.current_year,
                             self._ctx.prior_year, self._peers, parent_carrier_cur=parent,
                             mix_parent=parent_label)

    def _evidence(self, m: SliceMetrics) -> Dict[str, str]:
        return E.add_slice_evidence(self._result.evidence, m, self._ctx.current_label,
                                    self._ctx.symbol)

    def _products_in(self, country: str) -> List[str]:
        local = self._cube[(self._cube["country"] == country)
                           & (self._cube["year"] == self._ctx.current_year)]
        totals = local.groupby("product")["premium"].sum()
        return [p for p in totals.sort_values(ascending=False).index if totals[p] > 0]

    # the parts ------------------------------------------------------------------

    def add_overall(self) -> "ExecAnalysisBuilder":
        """The selected countries together: summed premium, recomputed shares."""
        m = self._metrics(Scope())
        self._result.overall = m
        self._result.overall_evidence = self._evidence(m)
        self._result.overall_classification = classify(m, self._cfg.materiality)
        return self

    def add_countries(self) -> "ExecAnalysisBuilder":
        """One analysis per selected country, against that country's own peer set."""
        for country in self._ctx.countries:
            m = self._metrics(Scope(country=country), self._result.overall.carrier_cur,
                              "carrier premium across the selected countries")
            self._result.countries.append(CountryAnalysis(
                country=country, metrics=m, evidence=self._evidence(m),
                peer_set=self._peers.get(country) or PeerSet(country, (), "none"),
                classification=classify(m, self._cfg.materiality)))
        return self

    def add_products(self) -> "ExecAnalysisBuilder":
        """Country × product: scale, growth, SoW, mix (of the country book) and rank."""
        for ca in self._result.countries:
            products = self._products_in(ca.country)
            for product in products:
                m = self._metrics(Scope(country=ca.country, product=product),
                                  ca.metrics.carrier_cur,
                                  f"carrier premium in {ca.country}")
                ca.products.append(ProductAnalysis(country=ca.country, product=product,
                                                   metrics=m, evidence=self._evidence(m)))
        return self

    def add_survey(self) -> "ExecAnalysisBuilder":
        """Country survey scores and gaps; product-level only where a practice maps."""
        by_country: Dict[str, SurveySummary] = {}
        for ca in self._result.countries:
            products = [p.product for p in ca.products]
            ca.survey = (country_survey(self._survey, self._ctx, ca.country, ca.peer_set,
                                        products, self._cfg)
                         if self._survey is not None else None)
            by_country[ca.country] = ca.survey
            if ca.survey is None or not ca.survey.available:
                continue
            period = _survey_period(ca.survey)
            ca.survey_evidence = add_survey_evidence(
                self._result.evidence, ca.survey.overall, f"{ca.country}/survey", ca.country, period)
            best, weakest = ranked_attributes(ca.survey, self._cfg.shortlist.attributes_per_side)
            ca.best_attributes = [line.name for line in best]
            ca.weakest_attributes = [line.name for line in weakest]
            for line in [*best, *weakest]:
                ca.attribute_evidence[line.name] = add_survey_evidence(
                    self._result.evidence, line, f"{ca.country}/survey/{line.name}", ca.country,
                    period)
            for pa in ca.products:
                pa.survey_line = ca.survey.practices.get(pa.product)
                if pa.survey_line is not None:
                    pa.survey_evidence = add_survey_evidence(
                        self._result.evidence, pa.survey_line, f"{pa.scope_id}/survey",
                        f"{pa.product} in {ca.country}", period)
        summaries = {c: s for c, s in by_country.items() if s is not None}
        if summaries:
            self._result.overall_survey = overall_survey(summaries)
            o = self._result.overall_survey
            if o.available:
                self._result.overall_survey_evidence = add_survey_evidence(
                    self._result.evidence, o.overall, "ALL/survey", "selected countries",
                    _survey_period(o))
        return self

    def add_classifications(self) -> "ExecAnalysisBuilder":
        """Leader / strength / attention per country × product, read with its survey."""
        for ca in self._result.countries:
            leader = ca.products[0].product if ca.products else None
            scale = ca.survey.scale_max if ca.survey and ca.survey.available else 5.0
            for pa in ca.products:
                pa.classification = classify(pa.metrics, self._cfg.materiality,
                                             is_leader=pa.product == leader,
                                             survey_line=pa.survey_line or (
                                                 ca.survey.overall if ca.survey else None),
                                             scale_max=scale)
        return self

    def add_industries(self) -> "ExecAnalysisBuilder":
        """Every SIC major within each country × product; top 3 / bottom 3 registered."""
        cfg = self._cfg
        for ca in self._result.countries:
            for pa in ca.products:
                pa.industries = [self._metrics(Scope(ca.country, pa.product, industry=i),
                                               pa.metrics.carrier_cur,
                                               f"carrier {pa.product} premium in {ca.country}")
                                 for i in self._names(ca.country, pa.product, "industry")]
                pa.selection = select_industries(
                    pa.industries, top_n=cfg.shortlist.industries_top,
                    bottom_n=cfg.shortlist.industries_bottom,
                    material_marsh=cfg.whitespace.material_marsh_premium,
                    rule_version=cfg.selection_rule_version)
                for row in pa.selection.rows:
                    pa.industry_evidence[row.scope.industry] = self._evidence(row)
        return self

    def add_segments(self) -> "ExecAnalysisBuilder":
        """Every segment within each country × product (overall and within the product)."""
        for ca in self._result.countries:
            for pa in ca.products:
                pa.segments = [self._metrics(Scope(ca.country, pa.product, segment=s),
                                             pa.metrics.carrier_cur,
                                             f"carrier {pa.product} premium in {ca.country}")
                               for s in self._names(ca.country, pa.product, "segment")]
                for row in pa.segments:
                    pa.segment_evidence[row.scope.segment] = self._evidence(row)
        return self

    def add_opportunities(self) -> "ExecAnalysisBuilder":
        """Whitespace gates over every industry and segment; shortlist per product/country."""
        cfg = self._cfg
        for ca in self._result.countries:
            for pa in ca.products:
                path = _path_for(pa.classification)
                pa.candidates = [
                    qualify(row, country=ca.country, product=pa.product, view=VIEW_INDUSTRY,
                            name=row.scope.industry, path=path, gates=cfg.whitespace)
                    for row in pa.industries
                ] + [
                    qualify(row, country=ca.country, product=pa.product, view=VIEW_SEGMENT,
                            name=row.scope.segment, path=path, gates=cfg.whitespace)
                    for row in pa.segments
                ]
                picked = shortlist(pa.candidates, cfg.shortlist.opportunities_per_product)
                pa.shortlist = [replace(c, evidence=self._evidence(c.metrics),
                                        segment_detail=self._segment_detail(ca.country, pa, c))
                                for c in picked]
            pool = [c for p in ca.products for c in p.shortlist]
            ca.shortlist = shortlist(pool, cfg.shortlist.opportunities_per_country)
        return self

    def add_product_totals(self) -> "ExecAnalysisBuilder":
        """Each product over all selected countries — the detail slide's table rows."""
        overall = self._result.overall
        totals = self._cube[self._cube["year"] == self._ctx.current_year]
        carrier = totals[totals["carrier"].str.lower() == self._ctx.carrier.lower()]
        by_product = carrier.groupby("product")["premium"].sum()
        products = [p for p in by_product.sort_values(ascending=False).index if by_product[p] > 0]
        self._result.product_totals = [
            self._metrics(Scope(product=p), overall.carrier_cur,
                          "carrier premium across the selected countries")
            for p in products]
        self._result.product_total_evidence = {
            row.scope.product: self._evidence(row) for row in self._result.product_totals}
        return self

    def build(self) -> ExecAnalysis:
        return self._result

    # helpers that answer one question each ---------------------------------------

    def _names(self, country: str, product: str, column: str) -> List[str]:
        local = self._cube[(self._cube["country"] == country) & (self._cube["product"] == product)]
        return sorted(str(v) for v in local[column].unique())

    def _segment_detail(self, country: str, pa: ProductAnalysis,
                        candidate: OpportunityCandidate) -> Optional[str]:
        """The segment inside a qualifying industry where Marsh is largest and the carrier
        is negligible — segment specificity only where the intersection is measured."""
        gates = self._cfg.whitespace
        if candidate.view != VIEW_INDUSTRY:
            return None
        best = None
        for segment in self._names(country, pa.product, "segment"):
            m = self._metrics(Scope(country, pa.product, industry=candidate.name,
                                    segment=segment))
            low = (m.sow_cur or 0.0) <= gates.max_carrier_sow_pct
            if low and m.marsh_cur > 0 and (best is None or m.marsh_cur > best[1]):
                best = (segment, m.marsh_cur)
        return best[0] if best else None


def _path_for(classification: Optional[Classification]) -> str:
    """Scenario 1 from a strength, Scenario 2 from a weakness, else plain development."""
    if classification is None:
        return PATH_DEVELOP
    if "needs_attention" in classification.labels:
        return PATH_REBUILD
    if "relative_strength" in classification.labels:
        return PATH_EXPAND
    return PATH_DEVELOP


def analyse(context: AnalysisContext, cube: pd.DataFrame, peer_sets: Mapping[str, PeerSet],
            survey_source: Optional[SurveySource], config: ExecConfig) -> ExecAnalysis:
    """The whole deterministic analysis, in the order the business reads it."""
    return (
        ExecAnalysisBuilder(context, cube, peer_sets, survey_source, config)
        .add_overall()
        .add_countries()
        .add_products()
        .add_survey()
        .add_classifications()
        .add_industries()
        .add_segments()
        .add_opportunities()
        .add_product_totals()
        .build()
    )
