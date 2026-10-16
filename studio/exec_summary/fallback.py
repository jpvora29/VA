"""Deterministic findings — the structured fallback for every stage (design Section 8).

Same shape as a model answer (:class:`StageOutput`), written from the same evidence ids,
and passed through the same verifier. Used when AI is off (``STUDIO_AI=off``), when the
endpoint fails, when a payload exceeds its budget, or when an answer fails verification
twice.

Written as a story, not a read-out: every sentence names WHAT moved (a product, an
industry inside it, a country), which way, how that compares with the Marsh book, and
what happened to share and rank — the headline, then what drove it, then what held it
back, then where to look next.
"""
from __future__ import annotations

from typing import List, Mapping, Optional, Sequence

from studio.exec_summary import classify as K
from studio.exec_summary.analysis import CountryAnalysis, ExecAnalysis, ProductAnalysis
from studio.exec_summary.drivers import Mover
from studio.exec_summary.evidence import EvidenceStore
from studio.exec_summary.metrics import SliceMetrics
from studio.exec_summary.schemas import ModelFinding, StageOutput, StageResult
from studio.exec_summary.whitespace import (
    FIT_QUALIFICATION,
    PATH_EXPAND,
    PATH_REBUILD,
    OpportunityCandidate,
)

_RULE_FOR_PATH = {PATH_EXPAND: "WS_EXPAND", PATH_REBUILD: "WS_REBUILD"}
#: A growth gap this wide reads as "well ahead of" rather than "ahead of".
WELL_AHEAD_PP = 10.0
#: A growth gap this narrow reads as "in line with".
IN_LINE_PP = 0.5


class _Writer:
    """Looks up displays by metric and remembers which ids a sentence used."""

    def __init__(self, store: EvidenceStore, ids: Mapping[str, str]) -> None:
        self.store, self.ids, self.used = store, ids, []

    def has(self, *metrics: str) -> bool:
        return all(m in self.ids for m in metrics)

    def __call__(self, metric: str) -> str:
        """The display as written, sign included ("+12.1%")."""
        eid = self.ids[metric]
        self.used.append(eid)
        return self.store.get(eid).display

    def mag(self, metric: str) -> str:
        """The display without its sign ("12.1%"), for a sentence whose verb says which way."""
        return self(metric).lstrip("+-")

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


# ── phrases: each one names a movement in words, quoting at most one figure ──


def _moved(w: _Writer, m: SliceMetrics, metric: str = "carrier_yoy") -> str:
    """"grew 12.1%", "fell 2.9%", "was flat" — the verb carries the sign."""
    if not m.carrier_growth.valid:
        w.cite(metric)
        return "was " + w.store.get(w.ids[metric]).display if w.has(metric) else "moved"
    if round(m.carrier_growth.pct, 1) == 0:
        w.cite(metric)
        return "was flat"
    return ("grew " if m.carrier_growth.pct > 0 else "fell ") + w.mag(metric)


def _versus(gap: Optional[float]) -> str:
    if gap is None:
        return ""
    if abs(gap) < IN_LINE_PP:
        return "in line with"
    if gap >= WELL_AHEAD_PP:
        return "well ahead of"
    return "ahead of" if gap > 0 else "behind"


def _against_book(w: _Writer, m: SliceMetrics) -> str:
    """", well ahead of the Marsh book's 9.5% and the peer average's 8.0%" — what exists."""
    parts = []
    if w.has("marsh_yoy") and m.growth_gap_marsh_pp is not None:
        parts.append(f"{_versus(m.growth_gap_marsh_pp)} the Marsh book's {w.mag('marsh_yoy')}")
    if w.has("peer_avg_yoy") and m.growth_gap_peer_pp is not None:
        parts.append(f"the peer average's {w.mag('peer_avg_yoy')}")
    return (", " + " and ".join(parts)) if parts else ""


def _share(w: _Writer, m: SliceMetrics, owner: str = "") -> str:
    """"lifting share of wallet to 9.1%" / "cutting Zurich's share of wallet to 7.4%"."""
    if not w.has("carrier_sow") or m.sow_change_pp is None or round(m.sow_change_pp, 1) == 0:
        return ""
    w.cite("sow_change")
    verb = "lifting" if m.sow_change_pp > 0 else "cutting"
    return f"{verb} {owner}share of wallet to {w('carrier_sow')}"


def _rank(w: _Writer, m: SliceMetrics) -> str:
    """"climbing to #1" / "slipping to #7" / "holding #3" — empty when unranked."""
    if not w.has("carrier_rank"):
        return ""
    move = m.rank_movement
    w.cite("rank_movement")
    if move is None:
        return ""
    if move > 0:
        return f"climbing to {w('carrier_rank')}"
    if move < 0:
        return f"slipping to {w('carrier_rank')}"
    return f"holding {w('carrier_rank')}"


def _joined(parts: Sequence[str], last: str = "and") -> str:
    """"Singapore", "Singapore and Hong Kong", "Singapore, Japan and Hong Kong"."""
    items = [p for p in parts if p]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def _inside(store: EvidenceStore, within: Optional[Mover], ids: List[str], *,
            gained: bool) -> str:
    """"with Technology & Telecom adding the most at $7.4M (17.2% of it)"."""
    if within is None:
        return ""
    iw = _Writer(store, within.evidence)
    share = f" ({iw('contribution_to_change')} of it)" if iw.has("contribution_to_change") else ""
    text = (f"{within.name} adding the most at {iw.mag('carrier_premium_change')}{share}"
            if gained else f"mainly in {within.name}, which lost {iw.mag('carrier_premium_change')}")
    ids.extend(iw.take())
    return text


def _headline_tail(w: _Writer, m: SliceMetrics) -> str:
    """", lifting share of wallet to 9.1% and climbing to #5" — share and rank, if moved."""
    tail = _joined([_share(w, m), _rank(w, m)])
    return f", {tail}" if tail else ""


# ── product stage ────────────────────────────────────────────────────────────


#: The facts a classification's stated basis quotes, so the basis can be cited.
_BASIS_FACTS = ("growth_gap_vs_marsh", "growth_gap_vs_peers", "sow_change", "carrier_sow",
                "peer_avg_sow")


def _severity(classification) -> tuple:
    if classification is not None and K.ATTENTION in classification.labels:
        return "PRODUCT_WEAKNESS", "attention"
    if classification is not None and K.STRENGTH in classification.labels:
        return "PRODUCT_STRENGTH", "strength"
    return "PRODUCT_POSITION", "context"


def _industry_sentence(store: EvidenceStore, pa: ProductAnalysis) -> Optional[ModelFinding]:
    """"Inside Property, Healthcare added $1.2M while Construction lost $0.4M."."""
    parts, ids = [], []
    for mover, verb in ((pa.industry_up, "added"), (pa.industry_down, "lost")):
        if mover is None:
            continue
        w = _Writer(store, mover.evidence)
        parts.append(f"{mover.name} {verb} {w.mag('carrier_premium_change')}")
        ids.extend(w.take())
    if not parts:
        return None
    return _finding("PRODUCT_POSITION", "context",
                    f"Inside {pa.product}, {_joined(parts, 'while')}.", ids)


def product_fallback(analysis: ExecAnalysis, ca: CountryAnalysis,
                     pa: ProductAnalysis) -> StageOutput:
    store, m = analysis.evidence, pa.metrics
    w = _Writer(store, pa.evidence)
    rule, severity = _severity(pa.classification)
    statement = (f"{pa.product} in {ca.country} {_moved(w, m)} to {w('carrier_premium')}"
                 f"{_against_book(w, m)}{_headline_tail(w, m)}.")
    ids = w.take()
    reasons = pa.classification.reasons if pa.classification else ()
    ids += [pa.evidence[m] for m in _BASIS_FACTS if reasons and m in pa.evidence]
    findings = [_finding(rule, severity, statement, ids,
                         interpretation=("; ".join(reasons)[:1].upper() + "; ".join(reasons)[1:])
                         if reasons else "")]
    industries = _industry_sentence(store, pa)
    if industries is not None:
        findings.append(industries)
    if pa.survey_line is not None and pa.survey_evidence:
        sw = _Writer(store, pa.survey_evidence)
        text = f"The {pa.product} survey score is {sw('survey_score')}"
        if sw.has("survey_score_prior"):
            text += f" against {sw('survey_score_prior')} a year earlier"
        findings.append(_finding("SURVEY_SIGNAL", "context", text + ".", sw.take()))
    return StageOutput(scope_id=pa.scope_id,
                       findings=findings[:analysis.config.findings.product_max],
                       priority_refs=[], missing_references=[])


# ── opportunity stage ────────────────────────────────────────────────────────


def _opportunity_finding(store: EvidenceStore, c: OpportunityCandidate,
                         carrier: str = "the carrier") -> ModelFinding:
    w = _Writer(store, c.evidence)
    where = f" ({c.segment_detail} segment)" if c.segment_detail else ""
    name = f"the {c.name} segment" if c.view == "segment" else c.name
    if c.metrics.carrier_cur > 0:
        holds = f"{carrier} holds only {w('carrier_premium')}, a {w('carrier_sow')} share of wallet"
    else:
        w.cite("carrier_premium")
        holds = f"{carrier} places none of it through Marsh"
    statement = (f"The clearest opening is {name}{where} within {c.product} in {c.country}: "
                 f"a {w('marsh_premium')} Marsh book growing {w.mag('marsh_yoy')} where {holds}.")
    return _finding(_RULE_FOR_PATH.get(c.path, "WS_DEVELOP"), "opportunity", statement,
                    w.take(), interpretation="A growing Marsh book with low carrier participation.",
                    recommendation=f"Review appetite, capacity and placement access for {c.name}.",
                    qualifications=c.qualifications or (FIT_QUALIFICATION,))


def opportunity_fallback(analysis: ExecAnalysis, ca: CountryAnalysis,
                         pa: ProductAnalysis) -> StageOutput:
    carrier = analysis.context.carrier
    findings = [_opportunity_finding(analysis.evidence, c, carrier) for c in pa.shortlist]
    return StageOutput(scope_id=f"{pa.scope_id}/opportunity",
                       findings=findings[:analysis.config.findings.opportunity_max],
                       priority_refs=[], missing_references=[])


# ── movers: the sentences that say who did it ────────────────────────────────


def _leaders_sentence(store: EvidenceStore, leaders: Sequence[Mover]) -> Optional[ModelFinding]:
    """"Cyber added $43.2M (52.0% of the increase) and climbed to #1, with Technology &
    Telecom adding the most at $7.4M; Financial Lines added $32.6M and rose to #3."."""
    if not leaders:
        return None
    ids: List[str] = []
    clauses = []
    for i, mover in enumerate(leaders):
        w = _Writer(store, mover.evidence)
        share = (f" ({w('contribution_to_change')} of the increase)"
                 if i == 0 and w.has("contribution_to_change") else "")
        rank = _rank(w, mover.metrics).replace("climbing", "climbed").replace(
            "slipping", "slipped").replace("holding", "held")
        clause = f"{mover.name} added {w.mag('carrier_premium_change')}{share}"
        clause += f" and {rank}" if rank else ""
        ids.extend(w.take())
        if i == 0:
            inside = _inside(store, mover.within, ids, gained=True)
            clause += f", with {inside}" if inside else ""
        clauses.append(clause)
    return _finding("EXEC_STRENGTH", "strength", "; ".join(clauses) + ".", ids)


def _drag_sentence(store: EvidenceStore, drag: Optional[Mover], rule: str) -> Optional[ModelFinding]:
    """"Casualty held the total back: it was flat while its Marsh book grew 9.5%, cutting
    share of wallet to 7.4% and slipping to #7, mainly in Financial Services."."""
    if drag is None:
        return None
    m = drag.metrics
    w = _Writer(store, drag.evidence)
    book = f" while its Marsh book grew {w.mag('marsh_yoy')}" if (
        w.has("marsh_yoy") and m.marsh_growth.valid and m.marsh_growth.pct > 0) else ""
    text = f"{drag.name} held the total back: it {_moved(w, m)}{book}{_headline_tail(w, m)}"
    ids = w.take()
    inside = _inside(store, drag.within, ids, gained=False)
    text += f", {inside}" if inside else ""
    return _finding(rule, "attention", text + ".", ids)


# ── country stage ────────────────────────────────────────────────────────────


def country_fallback(analysis: ExecAnalysis, ca: CountryAnalysis,
                     children: Mapping[str, StageResult]) -> StageOutput:
    store, m = analysis.evidence, ca.metrics
    w = _Writer(store, ca.evidence)
    led = f", led by {ca.product_leaders[0].name}" if ca.product_leaders else ""
    text = (f"In {ca.country}, premium {_moved(w, m)} to {w('carrier_premium')}"
            f"{_against_book(w, m)}{_headline_tail(w, m)}{led}.")
    findings = [_finding("COUNTRY_PERFORMANCE", "context", text, w.take())]
    leaders = _leaders_sentence(store, ca.product_leaders[:2])
    if leaders is not None:
        findings.append(leaders.model_copy(update={"rule_id": "COUNTRY_STRENGTH"}))
    drag = _drag_sentence(store, ca.product_drags[0] if ca.product_drags else None,
                          "COUNTRY_WEAKNESS")
    if drag is not None:
        findings.append(drag)
    opp = next((children[f"{p.scope_id}/opportunity"] for p in ca.products
                if f"{p.scope_id}/opportunity" in children
                and children[f"{p.scope_id}/opportunity"].findings), None)
    if opp is not None:
        f = opp.findings[0]
        findings.append(_finding("COUNTRY_OPPORTUNITY", "opportunity", f.statement,
                                 f.evidence_ids, recommendation=f.recommendation,
                                 qualifications=f.qualifications))
    return StageOutput(scope_id=f"{ca.country}/country",
                       findings=findings[:analysis.config.findings.country_max],
                       priority_refs=[], missing_references=[])


# ── overall stage: overall → each country → products → gaps → opportunities ──


def _verb(w: _Writer, metric: str, value: Optional[float]) -> str:
    """"grew 9.5%" / "fell 2.1%" / "was flat" for any growth metric."""
    if not w.has(metric):
        return ""
    if value is None:
        w.cite(metric)
        return "was " + w.store.get(w.ids[metric]).display
    if round(value, 1) == 0:
        w.cite(metric)
        return "was flat"
    return ("grew " if value > 0 else "fell ") + w.mag(metric)


def _overall_sentence(analysis: ExecAnalysis) -> ModelFinding:
    """Section 1 — the whole selection, naming no country and no product."""
    ctx, m = analysis.context, analysis.overall
    w = _Writer(analysis.evidence, analysis.overall_evidence)
    text = (f"Overall, {ctx.carrier}'s Marsh-placed premium {_moved(w, m)} to "
            f"{w('carrier_premium')} in {ctx.current_label}")
    marsh = _verb(w, "marsh_yoy", m.marsh_growth.pct if m.marsh_growth.valid else None)
    parts = [f"the Marsh book {marsh} to {w('marsh_premium')}"] if marsh else []
    peer = _verb(w, "peer_avg_yoy", m.peer.growth.pct if m.peer.growth.valid else None)
    if peer:
        who = "the average peer across these markets" if ctx.multi_country else "the average peer"
        parts.append(f"{who} {peer} to {w('peer_avg_premium')}")
    text += (", while " + " and ".join(parts)) if parts else ""
    share = _share(w, m, owner=f"{ctx.carrier}'s ")
    text += f", {share}" if share else ""
    return _finding("EXEC_OVERALL", "context", text + ".", w.take())


def _rank_clause(w: _Writer, m: SliceMetrics) -> str:
    """"at rank #5, up 1" / "at rank #7, unchanged"."""
    if not w.has("carrier_rank"):
        return ""
    move = f", {w('rank_movement')}" if w.has("rank_movement") and m.rank_movement else ""
    return f"at rank {w('carrier_rank')}{move}"


def _country_sentence(analysis: ExecAnalysis, ca: CountryAnalysis) -> ModelFinding:
    """Section 2 — one country: premium, growth vs its Marsh book, share of wallet against
    the peers' share, and rank."""
    m, w = ca.metrics, _Writer(analysis.evidence, ca.evidence)
    if analysis.context.multi_country:
        book_growth = m.marsh_growth.pct if m.marsh_growth.valid else None
        book = f" against a Marsh book that {_verb(w, 'marsh_yoy', book_growth)}"
        head = f"In {ca.country}, premium {_moved(w, m)} to {w('carrier_premium')}{book}, with "
    else:
        head = f"In {ca.country}, {analysis.context.carrier} has "
    share = ""
    if w.has("carrier_sow"):
        change = f" ({w('sow_change')})" if w.has("sow_change") else ""
        peers = f" against {w('peer_avg_sow')} for peers" if w.has("peer_avg_sow") else ""
        share = f"share of wallet at {w('carrier_sow')}{change}{peers}"
    rank = _rank_clause(w, m)
    tail = ", ".join(p for p in (share, rank) if p)
    return _finding("EXEC_COUNTRY", "context", (head + tail).rstrip(", ") + ".", w.take())


def _split(analysis: ExecAnalysis, product: str, ids: List[str], *, by: str) -> str:
    """"$21.8M in Singapore and $21.4M in Hong Kong" (by change) or "fell 0.4% in Singapore
    and grew 0.4% in Hong Kong" (by growth) — where a product's movement happened."""
    parts = []
    for ca in analysis.countries:
        pa = analysis.product_in(ca.country, product)
        if pa is None:
            continue
        w = _Writer(analysis.evidence, pa.evidence)
        if by == "change" and w.has("carrier_premium_change"):
            change = pa.metrics.carrier_cur - pa.metrics.carrier_prior
            amount = w.mag("carrier_premium_change")
            parts.append(f"{amount} in {ca.country}" if change >= 0
                         else f"a {amount} fall in {ca.country}")
        elif by == "growth":
            parts.append(f"{_moved(w, pa.metrics)} in {ca.country}")
        ids.extend(w.take())
    return _joined(parts)


def _product_leader_sentence(analysis: ExecAnalysis) -> Optional[ModelFinding]:
    """Section 3a — what added the most, where, its rank move and the industry inside."""
    leaders = analysis.product_leaders
    if not leaders:
        return None
    store, multi, ids, clauses = analysis.evidence, analysis.context.multi_country, [], []
    for i, mover in enumerate(leaders):
        w = _Writer(store, mover.evidence)
        clause = f"{mover.name} added {'the most, ' if i == 0 else ''}{w.mag('carrier_premium_change')}"
        ids.extend(w.take())
        if multi:
            where = _split(analysis, mover.name, ids, by="change")
            clause += f" ({where})" if where else ""
        rank = _rank(w, mover.metrics)
        clause += f", {rank}" if rank else ""
        ids.extend(w.take())
        if i == 0 and mover.within is not None:
            iw = _Writer(store, mover.within.evidence)
            clause += f", mostly in {mover.within.name} ({iw.mag('carrier_premium_change')})"
            ids.extend(iw.take())
        clauses.append(clause)
    return _finding("EXEC_PRODUCT", "strength", "By product, " + "; ".join(clauses) + ".", ids)


def _product_drag_sentence(analysis: ExecAnalysis) -> Optional[ModelFinding]:
    """Section 3b — what held the total back, in which country, and the industry behind it."""
    if not analysis.product_drags:
        return None
    drag, store = analysis.product_drags[0], analysis.evidence
    m, w = drag.metrics, _Writer(store, drag.evidence)
    ids: List[str] = []
    if analysis.context.multi_country:
        moved = _split(analysis, drag.name, ids, by="growth")
    else:
        moved = _moved(w, m)
    book = (f" while its Marsh book grew {w.mag('marsh_yoy')}"
            if w.has("marsh_yoy") and m.marsh_growth.valid and m.marsh_growth.pct > 0 else "")
    rank = _rank(w, m)
    text = f"{drag.name} held the total back: it {moved}{book}" + (f", {rank}" if rank else "")
    ids.extend(w.take())
    if drag.within is not None:
        iw = _Writer(store, drag.within.evidence)
        text += f", mostly in {drag.within.name} ({iw.mag('carrier_premium_change')} lower)"
        ids.extend(iw.take())
    return _finding("EXEC_PRODUCT", "attention", text + ".", ids)


def _gap_sentence(analysis: ExecAnalysis) -> Optional[ModelFinding]:
    """Section 4 — the gaps to close: product × country behind its Marsh book or losing
    share, and the markets where share of wallet sits below the peer average."""
    store, rules, ids, parts = analysis.evidence, analysis.config.materiality, [], []
    for pa in analysis.gaps[:2]:
        w, m = _Writer(store, pa.evidence), pa.metrics
        where = f"{pa.product} in {pa.country}" if analysis.context.multi_country else pa.product
        gap = m.growth_gap_marsh_pp
        if gap is not None and gap <= -rules.growth_gap_pp and w.has("growth_gap_vs_marsh"):
            parts.append(f"{where} trails its Marsh book's growth by "
                         f"{w.mag('growth_gap_vs_marsh')}")
        elif m.sow_change_pp is not None and w.has("sow_change"):
            parts.append(f"{where} gave up {w.mag('sow_change')} of share of wallet")
        ids.extend(w.take())
    below = []
    for ca in sorted(analysis.countries, key=lambda c: -c.metrics.carrier_cur):
        m, w = ca.metrics, _Writer(store, ca.evidence)
        if m.sow_cur is not None and m.peer.sow_cur is not None and m.sow_cur < m.peer.sow_cur:
            where = f"in {ca.country} " if analysis.context.multi_country else ""
            below.append(f"{where}({w('carrier_sow')} against {w('peer_avg_sow')})")
            ids.extend(w.take())
    sentences = [f"The gaps to close: {_joined(parts)}."] if parts else []
    if below:
        also = " also" if parts else ""
        sentences.append(f"{analysis.context.carrier}'s share of wallet is{also} below the peer "
                         f"average {_joined(below)}.")
    if not sentences:
        return None
    return _finding("EXEC_GAP", "attention", " ".join(sentences), ids)


def _opportunities_sentence(analysis: ExecAnalysis) -> Optional[ModelFinding]:
    """Section 5 — the best one or two openings, each placed in product and country."""
    best = sorted((c for ca in analysis.countries for c in ca.shortlist),
                  key=lambda c: c.ranking_keys())[:2]
    if not best:
        return None
    carrier, ids, parts = analysis.context.carrier, [], []
    for c in best:
        w = _Writer(analysis.evidence, c.evidence)
        name = f"the {c.name} segment" if c.view == "segment" else c.name
        if c.metrics.carrier_cur > 0:
            holds = f"{carrier} at {w('carrier_sow')} share of wallet"
        else:
            w.cite("carrier_premium")
            holds = f"no {carrier} premium"
        parts.append(f"{name} within {c.product} in {c.country} ({w('marsh_premium')} Marsh "
                     f"book growing {w.mag('marsh_yoy')}, {holds})")
        ids.extend(w.take())
    lead = "The clearest opening is " if len(parts) == 1 else "The clearest openings are "
    text = (lead + _joined(parts) + "; review appetite, capacity and placement access there, "
            "which are not yet validated.")
    return _finding("EXEC_OPPORTUNITY", "opportunity", text, ids,
                    qualifications=(FIT_QUALIFICATION,))


def _survey_sentence(analysis: ExecAnalysis) -> Optional[ModelFinding]:
    if not analysis.overall_survey_evidence:
        return None
    line = analysis.overall_survey.overall
    w = _Writer(analysis.evidence, analysis.overall_survey_evidence)
    move = line.movement
    mood = ("steady" if move is None or abs(move) < 0.1 else
            "improving" if move > 0 else "softening")
    text = f"Service perception is {mood}: the survey score is {w('survey_score')}"
    if w.has("survey_score_prior"):
        text += f" against {w('survey_score_prior')} a year earlier"
    if w.has("survey_gap_vs_peers") and line.peer_gap is not None and round(line.peer_gap, 1) != 0:
        side = "behind" if line.peer_gap < 0 else "ahead of"
        text += f", {w.mag('survey_gap_vs_peers')} {side} the peer average"
    ids = w.take()
    weakest = _weakest_attribute(analysis)
    if weakest is not None:
        country, name, aw = weakest
        text += f", with {name} the weakest area in {country} at {aw('survey_score')}"
        ids.extend(aw.take())
    return _finding("EXEC_SURVEY", "context", text + ".", ids)


def _weakest_attribute(analysis: ExecAnalysis):
    for ca in analysis.countries:
        if ca.weakest_attributes:
            name = ca.weakest_attributes[0]
            return ca.country, name, _Writer(analysis.evidence, ca.attribute_evidence[name])
    return None


def overall_fallback(analysis: ExecAnalysis, countries: Mapping[str, StageResult]) -> StageOutput:
    """The summary in the order it is read: overall, each country, products, gaps,
    opportunities."""
    ordered = sorted(analysis.countries, key=lambda c: -c.metrics.carrier_cur)
    findings = [f for f in (
        _overall_sentence(analysis),
        *(_country_sentence(analysis, ca) for ca in ordered[:6]),
        _product_leader_sentence(analysis),
        _product_drag_sentence(analysis),
        _gap_sentence(analysis),
        _survey_sentence(analysis),
        _opportunities_sentence(analysis),
    ) if f is not None]
    cap = analysis.config.findings.overall_max
    if len(findings) > cap:          # keep the overall sentence and the closing opportunity
        findings = findings[:cap - 1] + findings[-1:]
    return StageOutput(scope_id="ALL/overall", findings=findings, priority_refs=[],
                       missing_references=[])
