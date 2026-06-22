"""build_evidence_pack — adapter from computed facts to the EvidencePack contract.

Turns an `OverallResult` (studio/compute.py) into an `EvidencePack`: assigns a
stable `fact_id` to every number, records provenance, wires `derived_from` for
computed measures (a movement points back at the two period totals it came from),
and runs the Phase-0 capability probe (§10.3) so the plan knows what the data can
and cannot support.

This is the seam where numbers acquire identity. Downstream, claims reference these
ids and renderers use `EvidenceItem.rendered` verbatim — the LLM never emits a
number. Deterministic: every id is a pure function of (measure, dims, period), so
the same `OverallResult` yields the same pack.

Imports the engine-backed compute helpers, so it can only run where the analytics
stack is installed (unlike the pure contracts in evidence_pack.py / report_plan.py
/ qa.py).
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from studio.compute import (
    OverallResult,
    concentration,
    movement_by_dim,
    peer_gap,
    period_totals,
    rank_movement,
    sow_movement,
)
from studio.content.evidence_pack import (
    Capability,
    EvidenceItem,
    EvidencePack,
    Provenance,
    make_fact_id,
)
from studio.page.format import money, pct

_PRIMARY = "Product_Line"
_INDUSTRY = "SIC_Major_Class"


def _signed_money(v: float) -> str:
    return ("+" if v >= 0 else "-") + money(abs(v))


def _put(
    items: Dict[str, EvidenceItem],
    measure: str,
    value: float,
    rendered: str,
    *,
    dims: Optional[Mapping[str, Any]] = None,
    period: Optional[int] = None,
    confidence: str = "high",
    prov: Optional[Provenance] = None,
    derived_from: tuple = (),
) -> str:
    """Create one EvidenceItem, index it by its stable id, return the id."""
    dims = dict(dims or {})
    fid = make_fact_id(measure, dims, period)
    items[fid] = EvidenceItem(
        fact_id=fid, measure=measure, value=value, rendered=rendered,
        dims=dims, confidence=confidence, provenance=prov, derived_from=tuple(derived_from),
    )
    return fid


def build_evidence_pack(
    result: OverallResult, *, carrier=None, country=None, year=None
) -> EvidencePack:
    carrier = carrier or result.subject or "Market"
    flow, filters, engine = result.flow, result.resolved_filters, result.engine
    period = f"FY{year}" if year else "current period"
    comp = f"FY{int(year) - 1}" if year else "prior period"
    yr_int = int(year) if year else None
    prov = Provenance(flow=flow, source="GPR — premium ledger", primitive="", filters=dict(filters), period=yr_int)

    items: Dict[str, EvidenceItem] = {}

    totals = period_totals(flow, filters, engine)
    movers = movement_by_dim(flow, _PRIMARY, filters, engine) if totals else []
    rankm = rank_movement(flow, filters, engine, carrier)
    sowm = sow_movement(flow, filters, engine, carrier)
    primary = next((b for b in result.breakdowns if b.column == _PRIMARY),
                   result.breakdowns[0] if result.breakdowns else None)
    conc = concentration(primary.rows) if (primary and primary.rows) else None
    pg = peer_gap(flow, filters, engine)

    # ── period totals + total movement ───────────────────────────────────────
    if totals:
        cur_id = _put(items, "premium_total", totals["current"], money(totals["current"]),
                      dims={"year": totals["current_year"]}, period=totals["current_year"], prov=prov)
        pri_id = _put(items, "premium_total", totals["prior"], money(totals["prior"]),
                      dims={"year": totals["prior_year"]}, period=totals["prior_year"], prov=prov)
        _put(items, "premium_movement", totals["delta"], _signed_money(totals["delta"]),
             dims={"scope": "total", "year": totals["current_year"]}, period=totals["current_year"],
             prov=prov, derived_from=(cur_id, pri_id))
        if totals.get("pct") is not None:
            _put(items, "premium_movement_pct", totals["pct"], pct(totals["pct"], signed=True),
                 dims={"scope": "total", "year": totals["current_year"]}, period=totals["current_year"],
                 prov=prov, derived_from=(cur_id, pri_id))

    # ── per-dimension movement (the driver decomposition) ────────────────────
    for m in movers:
        _put(items, "premium_movement", m["delta"], _signed_money(m["delta"]),
             dims={_PRIMARY: m["name"], "year": yr_int}, period=yr_int, prov=prov)

    # ── rank ─────────────────────────────────────────────────────────────────
    if rankm:
        rendered = f"#{rankm['current']}" + (f" of {rankm['of_n']}" if rankm.get("of_n") else "")
        _put(items, "rank", float(rankm["current"]), rendered,
             dims={"entity": carrier, "year": yr_int}, period=yr_int, prov=prov)

    # ── share of wallet ──────────────────────────────────────────────────────
    if sowm and sowm.get("current") is not None:
        _put(items, "sow", sowm["current"], f"{sowm['current']:.1f}%",
             dims={"entity": carrier, "year": yr_int}, period=yr_int, prov=prov)

    # ── concentration (HHI / top-3) ──────────────────────────────────────────
    if conc:
        _put(items, "hhi", float(conc["hhi"]), str(conc["hhi"]), dims={"basis": _PRIMARY}, period=yr_int, prov=prov)
        _put(items, "concentration", conc["top3"], f"{conc['top3']:.0f}%",
             dims={"basis": _PRIMARY, "stat": "top3"}, period=yr_int, prov=prov)

    # ── peer ratio (aggregate only — confidentiality) ────────────────────────
    if pg and pg.get("ratio") is not None:
        _put(items, "peer_ratio", pg["ratio"], f"{pg['ratio']:.2f}x",
             dims={"entity": carrier, "year": yr_int}, period=yr_int, confidence="medium", prov=prov)

    # ── whitespace ───────────────────────────────────────────────────────────
    for w in (result.whitespace or []):
        _put(items, "whitespace_market", w["market"], money(w["market"]),
             dims={_INDUSTRY: w["name"]}, period=yr_int, confidence="medium", prov=prov)

    capabilities = probe_capabilities(result, totals=totals, movers=movers, rankm=rankm,
                                      sowm=sowm, conc=conc, pg=pg)

    return EvidencePack(
        subject=carrier, country=country, period=period, comparison_period=comp,
        items=items, capabilities=capabilities,
        sources=("GPR — premium ledger", "Peers — aggregate benchmark"),
    )


def probe_capabilities(
    result: OverallResult, *, totals=None, movers=None, rankm=None, sowm=None, conc=None, pg=None
) -> Dict[str, Capability]:
    """Phase-0 probe: per agenda section, what the live data supports (§10.3).

    Availability is read from what compute actually returned this run — never a
    hand-authored table. Blocked sections become DataGaps on the methodology slide.
    """
    movers = movers or []
    flow = result.flow
    has_year = bool(totals)
    caps: Dict[str, Capability] = {}

    def cap(section, available, comparison, confidence="high", reason=""):
        caps[section] = Capability(section, available, comparison, confidence, reason)

    cap("performance", has_year, comparison=bool(totals and totals.get("prior") is not None),
        confidence="high" if has_year else "low",
        reason="" if has_year else "no reporting year selected — prior-period comparison unavailable")
    cap("premium_movement", bool(movers), comparison=bool(movers),
        reason="" if movers else "needs a reporting year and a product breakdown")
    cap("portfolio_mix", bool(conc), comparison=False,
        reason="" if conc else "no product breakdown rows to measure concentration")
    industry = next((b for b in result.breakdowns if b.column == _INDUSTRY), None)
    cap("geo_industry", bool(industry and industry.rows), comparison=False,
        reason="" if (industry and industry.rows) else "no industry breakdown in scope")
    cap("share_position", bool(rankm or sowm or pg), comparison=bool(rankm or sowm),
        reason="" if (rankm or sowm or pg) else "rank/share/peer measures unavailable")
    cap("whitespace", bool(result.whitespace), comparison=False, confidence="medium",
        reason="" if result.whitespace else "no whitespace candidates (needs a carrier subject)")
    cap("risks", bool(movers or conc), comparison=False,
        reason="" if (movers or conc) else "no movement or concentration signal to flag")
    cap("decisions", True, comparison=False)

    # Structurally blocked on the GPR premium ledger (§ evidence.py gaps).
    cap("rate_volume_mix", False, False, "low",
        "rate–exposure–volume decomposition needs policy counts/exposure; the ledger holds amounts only")
    cap("retention", False, False, "low",
        "retention/renewal/new-business needs policy-level transactional data (not in the ledger)")
    cap("prior_actions", False, False, "low",
        "no prior-quarter QBR loaded — previous-action progress cannot be tracked yet")
    cap("survey", flow != "gpr", flow != "gpr", "low" if flow == "gpr" else "medium",
        "broker/customer survey not in scope for this Premium view" if flow == "gpr" else "")
    return caps
