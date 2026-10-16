"""Survey scores, movement and gaps for the executive summary (design Section 7).

Survey facts stay separate from premium facts: they are read from the survey book, in its
own vocabulary, and joined to the commercial story only through country and (where a
practice maps to a premium line) product. A country score is never copied onto a product
or an industry — a product with no mapped practice simply has no product-level survey.

The book is reached through :class:`SurveySource`, a small adapter, so the scoring rules
here are testable without a warehouse.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from logger import get_logger
from studio.exec_summary.config import ExecConfig
from studio.exec_summary.context import AnalysisContext
from studio.exec_summary.peers import PeerSet

logger = get_logger(__name__)

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"

CARRIER = "Carrier"
COUNTRY = "SurveyCountry"
PRACTICE = "SurveyPractice"
ATTRIBUTE = "Attributes"
YEAR = "Survey_Year"


@dataclass(frozen=True)
class ScoreLine:
    """One scored thing (overall, a section, an attribute, a practice) in one scope."""

    name: str
    score: Optional[float]
    prior: Optional[float] = None
    peer_mean: Optional[float] = None
    peer_prior: Optional[float] = None
    book_mean: Optional[float] = None        # every surveyed carrier in the same scope
    peer_count: int = 0

    @property
    def movement(self) -> Optional[float]:
        return None if self.score is None or self.prior is None else self.score - self.prior

    @property
    def peer_gap(self) -> Optional[float]:
        return None if self.score is None or self.peer_mean is None else self.score - self.peer_mean

    @property
    def prior_peer_gap(self) -> Optional[float]:
        if self.prior is None or self.peer_prior is None:
            return None
        return self.prior - self.peer_prior

    @property
    def gap_change(self) -> Optional[float]:
        if self.peer_gap is None or self.prior_peer_gap is None:
            return None
        return self.peer_gap - self.prior_peer_gap

    @property
    def book_gap(self) -> Optional[float]:
        return None if self.score is None or self.book_mean is None else self.score - self.book_mean


@dataclass(frozen=True)
class SurveySummary:
    scope_label: str
    status: str
    year: Optional[int] = None
    prior_year: Optional[int] = None
    scale_max: float = 5.0
    overall: Optional[ScoreLine] = None
    sections: Tuple[ScoreLine, ...] = ()
    attributes: Tuple[ScoreLine, ...] = ()
    practices: Dict[str, ScoreLine] = field(default_factory=dict)   # premium product → line
    note: str = ""

    @property
    def available(self) -> bool:
        return self.status != STATUS_UNAVAILABLE and self.overall is not None


def unavailable(scope_label: str, note: str) -> SurveySummary:
    return SurveySummary(scope_label=scope_label, status=STATUS_UNAVAILABLE, note=note)


# ── the adapter onto the survey book ─────────────────────────────────────────


#: ``(group_by, filters) -> [(dims, value)]`` — AVG score per cut.
RowsFn = Callable[[Tuple[str, ...], Dict[str, Any]], List[Tuple[Dict[str, Any], float]]]


@dataclass(frozen=True)
class SurveySource:
    rows: RowsFn
    section_column: Optional[str]
    market_for: Callable[[str], Optional[str]]
    carrier_for: Callable[[str], Optional[str]]
    peers_for: Callable[[str, Tuple[str, ...]], Tuple[str, ...]]
    years_for: Callable[[str, str], Tuple[int, ...]]


def survey_source_from_result(result: Any) -> SurveySource:
    """The production adapter: the run's survey book through the existing survey helpers."""
    from studio.template_fill.survey import facts, identity, scope

    def rows(group_by, filters):
        return [(dict(f.dims or {}), float(f.value)) for f in
                facts._breakdown(result, tuple(group_by), dict(filters))
                if f.value is not None]

    def carrier_for(market):
        return identity.resolve_carrier(result, (market,))

    def peers_for(market, premium_peers):
        country_pin = (getattr(result, "survey_peers_by_country", None) or {})
        pinned = None
        for key, value in country_pin.items():
            if facts.norm_label(key) == facts.norm_label(market):
                pinned = tuple(value) or None
        scoped = replace(result, survey_peers=pinned, peers=tuple(premium_peers) or None)
        subject = carrier_for(market)
        return identity.resolve_peers(scoped, subject, (market,)) if subject else ()

    def years_for(market, carrier):
        return scope.surveyed_years(result, {facts.CARRIER_COL: carrier,
                                             facts.COUNTRY_COL: market})

    return SurveySource(rows=rows, section_column=facts.section_column(result),
                        market_for=lambda c: scope.book_country(result, c),
                        carrier_for=carrier_for, peers_for=peers_for, years_for=years_for)


# ── scoring ──────────────────────────────────────────────────────────────────


def _pick_years(surveyed: Sequence[int], current: int) -> Tuple[Optional[int], Optional[int]]:
    """The survey wave at or before the premium year, and the wave before it."""
    from studio.template_fill.survey.scope import reporting_years

    return reporting_years(surveyed, (current,))


def _by(rows, keys: Tuple[str, ...]) -> Dict[Tuple, float]:
    return {tuple(str(d.get(k)) for k in keys): v for d, v in rows}


def _mean(values: Sequence[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _score_at(per_carrier: Dict[Tuple, float], who: str, name: Tuple, year: Optional[int]):
    return per_carrier.get((who, *name, str(year))) if year is not None else None


def _lines(source: SurveySource, market: str, dims: Tuple[str, ...], carrier: str,
           peers: Tuple[str, ...], year: int, prior: Optional[int],
           min_peers: int) -> List[ScoreLine]:
    """Score lines per ``dims`` cut: carrier, peer mean, and the whole surveyed book."""
    years = [y for y in (year, prior) if y is not None]
    per_carrier = _by(source.rows((CARRIER, *dims, YEAR), {COUNTRY: market, YEAR: years}),
                      (CARRIER, *dims, YEAR))
    book = _by(source.rows((*dims, YEAR), {COUNTRY: market, YEAR: years}), (*dims, YEAR))
    names = sorted({k[1:-1] for k in per_carrier if k[0] == carrier and k[-1] == str(year)})
    out = []
    for name in names:
        peer_now = [v for v in (_score_at(per_carrier, p, name, year) for p in peers)
                    if v is not None]
        peer_before = [v for v in (_score_at(per_carrier, p, name, prior) for p in peers)
                       if v is not None]
        enough = len(peer_now) >= min_peers
        out.append(ScoreLine(
            name=" – ".join(name) if name else "Overall",
            score=_score_at(per_carrier, carrier, name, year),
            prior=_score_at(per_carrier, carrier, name, prior),
            peer_mean=_mean(peer_now) if enough else None,
            peer_prior=_mean(peer_before) if enough and len(peer_before) >= min_peers else None,
            book_mean=book.get((*name, str(year))),
            peer_count=len(peer_now),
        ))
    return out


def _scale_max(lines: Sequence[ScoreLine]) -> float:
    top = max((l.score or 0.0 for l in lines), default=0.0)
    return 10.0 if top > 5.0 else 5.0


def _practice_lines(lines: Sequence[ScoreLine], products: Sequence[str]) -> Dict[str, ScoreLine]:
    """Survey practices that name a premium product line, keyed by that product."""
    from studio.template_fill.facts_survey_lines import line_for

    wanted = {p.lower(): p for p in products}
    out: Dict[str, ScoreLine] = {}
    for line in lines:
        product = wanted.get(line_for(line.name))
        if product is not None:
            out[product] = line
    return out


def country_survey(source: SurveySource, context: AnalysisContext, country: str,
                   peer_set: Optional[PeerSet], products: Sequence[str],
                   config: ExecConfig) -> SurveySummary:
    """One country's survey evidence, or an explicit ``unavailable`` with the reason."""
    if not context.survey_on:
        return unavailable(country, "survey not in the run's data basis")
    if source.section_column is None:
        return unavailable(country, "no survey book")
    market = source.market_for(country)
    if market is None:
        return unavailable(country, "country not surveyed")
    carrier = source.carrier_for(market)
    if carrier is None:
        return unavailable(country, "carrier not in the survey for this country")
    year, prior = _pick_years(source.years_for(market, carrier), context.current_year)
    if year is None:
        return unavailable(country, "no survey wave at or before the reporting year")
    peers = source.peers_for(market, peer_set.members if peer_set else ())
    min_peers = config.survey.min_peer_carriers
    overall = _lines(source, market, (), carrier, peers, year, prior, min_peers)
    if not overall:
        return unavailable(country, "carrier has no scored responses")
    sections = _lines(source, market, (source.section_column,), carrier, peers, year, prior,
                      min_peers)
    attributes = _lines(source, market, (source.section_column, ATTRIBUTE), carrier, peers,
                        year, prior, min_peers)
    practices = _lines(source, market, (PRACTICE,), carrier, peers, year, prior, min_peers)
    partial = overall[0].peer_mean is None or prior is None
    return SurveySummary(
        scope_label=country,
        status=STATUS_PARTIAL if partial else STATUS_COMPLETE,
        year=year, prior_year=prior, scale_max=_scale_max(overall),
        overall=overall[0], sections=tuple(sections), attributes=tuple(attributes),
        practices=_practice_lines(practices, products),
        note="" if not partial else "peer reference or prior wave unavailable",
    )


def overall_survey(by_country: Mapping[str, SurveySummary]) -> SurveySummary:
    """The selected countries together: a mean of country scores, gaps averaged within
    country (design Section 6 — never a union of peer lists into a global peer set)."""
    valid = [s for s in by_country.values() if s.available]
    if not valid:
        return unavailable("selected countries", "no country has survey evidence")
    if len(valid) == 1:
        return replace(valid[0], scope_label="selected countries")
    o = [s.overall for s in valid]
    line = ScoreLine(
        name="Overall",
        score=_mean([l.score for l in o]), prior=_mean([l.prior for l in o]),
        peer_mean=_mean([l.peer_mean for l in o]) if all(l.peer_mean is not None for l in o) else None,
        peer_prior=_mean([l.peer_prior for l in o]) if all(l.peer_prior is not None for l in o) else None,
        book_mean=_mean([l.book_mean for l in o]),
        peer_count=sum(l.peer_count for l in o),
    )
    complete = len(valid) == len(by_country) and all(s.status == STATUS_COMPLETE for s in valid)
    return SurveySummary(
        scope_label="selected countries",
        status=STATUS_COMPLETE if complete else STATUS_PARTIAL,
        year=max(s.year for s in valid), prior_year=max((s.prior_year or 0) for s in valid) or None,
        scale_max=max(s.scale_max for s in valid), overall=line,
        note="" if complete else "some countries lack survey evidence",
    )


def ranked_attributes(summary: SurveySummary, n: int) -> Tuple[List[ScoreLine], List[ScoreLine]]:
    """(best n, weakest n) attributes by score — ties keep a stable name order."""
    scored = sorted((a for a in summary.attributes if a.score is not None),
                    key=lambda a: (-a.score, a.name))
    best = scored[:n]
    weakest = [a for a in reversed(scored) if a not in best][:n]
    return best, weakest
