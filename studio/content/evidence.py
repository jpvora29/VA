"""Build a `QBRContentSpec` from computed facts — the analyst reasoning layer.

Only MATERIAL, data-supported findings are produced; analyses the GPR premium
ledger cannot support (rate–volume–mix, retention/renewal, prior-QBR actions,
survey when not in scope) are recorded as explicit `DataGap`s rather than filled
with generic commentary.
"""
from __future__ import annotations

from typing import Any, List, Optional

from studio.compute import (
    OverallResult,
    concentration,
    movement_by_dim,
    opportunity_matrix,
    peer_gap,
    period_totals,
    position_radar,
    product_country_heatmap,
    rank_movement,
    sow_movement,
    ttm,
)
from studio.content.model import Action, DataGap, Evidence, Finding, QBRContentSpec
from studio.deck.model import ChartBlock, HeatmapBlock, MatrixBlock, RadarBlock, TableBlock
from studio.page.format import money, pct

_PRIMARY = "Product_Line"
# Driver table shows BOTH years' premium + the YoY %, not just an absolute change —
# YoY is what tells a carrier whether a line is genuinely growing.
_MOVE_COLS = [
    {"key": "name", "label": "Segment", "align": "left"},
    {"key": "prior", "label": "Prior yr", "kind": "money", "align": "right"},
    {"key": "current", "label": "Current yr", "kind": "money", "align": "right"},
    {"key": "pct", "label": "YoY", "kind": "delta", "align": "right"},
]
# YoY above this always shows both years' premium (rules.yaml yoy.high_growth_pct).
_HIGH_GROWTH = 100.0


def _signed_money(v: float) -> str:
    return ("+" if v >= 0 else "-") + money(abs(v))


def _mover_label(m: dict) -> str:
    """A driver as 'Name (+X% YoY)', and for >100% growth, the two years' premium."""
    pctv = m.get("pct")
    label = m["name"]
    if pctv is not None:
        label += f" ({pct(pctv, signed=True)} YoY)"
    if pctv is not None and pctv >= _HIGH_GROWTH:
        label += f" [{money(m['prior'])}→{money(m['current'])}]"
    return label


def build_content_spec(result: OverallResult, *, carrier=None, country=None, year=None) -> QBRContentSpec:
    carrier = carrier or result.subject or "Market"
    flow, filters, engine = result.flow, result.resolved_filters, result.engine
    period = f"FY{year}" if year else "current period"
    comp = f"FY{int(year) - 1}" if year else "prior period"

    findings: List[Finding] = []
    gaps: List[DataGap] = []
    what_changed: List[str] = []

    totals = period_totals(flow, filters, engine)
    rankm = rank_movement(flow, filters, engine, carrier)
    sowm = sow_movement(flow, filters, engine, carrier)
    primary = next((b for b in result.breakdowns if b.column == _PRIMARY), result.breakdowns[0] if result.breakdowns else None)
    movers = movement_by_dim(flow, _PRIMARY, filters, engine) if totals else []
    ttm_data = ttm(flow, filters, engine)

    # ── Performance vs prior period ──────────────────────────────────────────
    if totals:
        d, p = totals["delta"], totals["pct"]
        dir_word = "grew" if d >= 0 else "declined"
        ev = [
            Evidence("Current premium", money(totals["current"]), f"{period}"),
            Evidence("Prior premium", money(totals["prior"]), f"{comp}"),
            Evidence("Movement", _signed_money(d), (f"{p:+.1f}%" if p is not None else "n/a")),
        ]
        tk = [{"label": "Premium.", "text": f"GWP {dir_word} {pct(p, signed=True) if p is not None else ''} to {money(totals['current'])} vs {comp}.", "tone": "good" if d >= 0 else "danger"}]
        if rankm and rankm.get("delta") is not None:
            move = rankm["delta"]
            verb = "up" if move > 0 else "down" if move < 0 else "flat"
            ev.append(Evidence("Market rank", f"#{rankm['current']}" + (f" of {rankm['of_n']}" if rankm['of_n'] else ""), f"{verb} {abs(move)} vs {comp}"))
            tk.append({"label": "Rank.", "text": f"Market rank {verb} {abs(move)} place(s) to #{rankm['current']}.", "tone": "good" if move > 0 else "danger" if move < 0 else "neutral"})
            what_changed.append(f"Rank {verb} {abs(move)} to #{rankm['current']}")
        if sowm and sowm.get("delta") is not None:
            ev.append(Evidence("Share of wallet", f"{sowm['current']:.1f}%", f"{sowm['delta']:+.1f} pts vs {comp}"))
        what_changed.insert(0, f"Premium {dir_word} {pct(p, signed=True) if p is not None else ''} to {money(totals['current'])}")
        # Time-based view: a trailing-12-month GWP trend (when monthly data exists)
        # PLUS the prior-vs-current bar — two visuals + a KPI band = a full slide.
        perf_visuals: List[Any] = []
        if ttm_data and ttm_data.get("values"):
            perf_visuals.append(ChartBlock("line", ttm_data["labels"], ttm_data["values"], "Trailing-12-month GWP"))
            if ttm_data.get("ttm_pct") is not None:
                tk.append({"label": "TTM.", "text": f"Trailing-12-month GWP is {pct(ttm_data['ttm_pct'], signed=True)} vs the prior twelve months.",
                           "tone": "good" if ttm_data["ttm_pct"] >= 0 else "danger"})
        perf_visuals.append(ChartBlock("bar", [comp, period], [totals["prior"], totals["current"]], "Prior vs current GWP"))
        findings.append(Finding(
            section="performance",
            question=f"How did {carrier} perform versus {comp}?",
            action_title=f"Premium {dir_word} {pct(p, signed=True) if p is not None else ''} to {money(totals['current'])} versus {comp}",
            implication="Performance is measured on the premium ledger; plan comparison is unavailable.",
            recommendation="Confirm the result against budget once plan figures are loaded.",
            owner="Regional placement lead", due_date=f"Q4 {totals['current_year']}", confidence="high",
            materiality=min(1.0, abs(p or 0) / 20 + 0.5),
            evidence=ev, takeaways=tk, kpis=list(result.kpis),
            visuals=perf_visuals,
        ))

    # ── Premium movement & drivers ───────────────────────────────────────────
    if movers and totals:
        pos = [m for m in movers if m["delta"] > 0][:3]
        neg = [m for m in movers if m["delta"] < 0][:3]
        total_abs = sum(abs(m["delta"]) for m in movers) or 1.0
        lead = movers[0]
        lead_share = abs(lead["delta"]) / total_abs * 100
        concentrated = lead_share >= 45
        tk = []
        if pos:
            tk.append({"label": "Tailwinds.", "text": "Growth led by " + ", ".join(_mover_label(m) for m in pos) + ".", "tone": "good"})
        if neg:
            tk.append({"label": "Headwinds.", "text": "Offset by " + ", ".join(_mover_label(m) for m in neg) + ".", "tone": "danger"})
        tk.append({"label": "Shape.", "text": f"{lead['name']} alone is {lead_share:.0f}% of the gross movement — the change is {'concentrated' if concentrated else 'broad-based'}.", "tone": "neutral"})
        findings.append(Finding(
            section="premium_movement",
            question="What drove the change in premium?",
            action_title=(f"{lead['name']} drove {lead_share:.0f}% of the premium movement"
                          if concentrated else "Premium movement is broad-based across the book"),
            implication=("Concentrated movement — a targeted intervention can move the number."
                         if concentrated else "Broad movement — portfolio-level levers matter more than single accounts."),
            recommendation=(f"Prioritise the {('at-risk' if lead['delta'] < 0 else 'high-growth')} {lead['name']} book."),
            owner="Regional placement lead", due_date=f"Q4 {totals['current_year']}", confidence="high",
            materiality=0.95,
            evidence=[Evidence(m["name"], _signed_money(m["delta"]), f"{money(m['prior'])} → {money(m['current'])}") for m in movers[:4]],
            takeaways=tk,
            # Premium bridge: each product line's contribution to the movement,
            # accumulating to the net change — then the detail table beneath it.
            visuals=[
                ChartBlock("waterfall", [m["name"] for m in movers], [m["delta"] for m in movers], "Premium movement bridge"),
                TableBlock(_MOVE_COLS, movers),
            ],
        ))

    # ── Portfolio & product mix — where premium sits and where to grow ───────
    if primary and primary.rows:
        conc = concentration(primary.rows)
        if conc:
            top = sorted(primary.rows, key=lambda r: r["premium"] or 0, reverse=True)[:6]
            # The clearest room to grow: the in-scope line with the lowest wallet
            # penetration (headroom against the market), else the smallest line.
            have_sow = [r for r in primary.rows if r.get("sow") is not None]
            grow = min(have_sow, key=lambda r: r["sow"]) if have_sow else min(primary.rows, key=lambda r: r["premium"] or 0)
            grow_sow = f" ({grow['sow']:.1f}% wallet share)" if grow.get("sow") is not None else ""
            lead = top[0]
            second = top[1] if len(top) > 1 else None
            anchors = lead["name"] + (f" and {second['name']}" if second else "")
            findings.append(Finding(
                section="portfolio_mix",
                question="Where does the premium sit, and where is the room to grow?",
                action_title=(f"{anchors} anchor the book ({conc['top3']:.0f}% of premium); "
                              f"{grow['name']} is the clearest line to grow"),
                implication="Premium is concentrated in a few lines; deepening an under-penetrated, "
                            "in-appetite line is the most reliable way to write more premium.",
                recommendation=f"Grow {grow['name']}{grow_sow} — lowest penetration, with headroom against the market.",
                owner="Portfolio strategy lead", due_date=f"Q1 {(int(year) + 1) if year else ''}".strip(), confidence="high",
                materiality=0.75,
                evidence=[
                    Evidence("Lead line", lead["name"], f"{conc['lead']:.0f}% of book"),
                    Evidence("Top-3 share", f"{conc['top3']:.0f}%"),
                    Evidence("Grow", grow["name"], grow_sow.strip(" ()") or "under-weight"),
                ],
                takeaways=[
                    {"label": "Anchors.", "text": f"{anchors} carry {conc['top3']:.0f}% of premium; {lead['name']} alone is {conc['lead']:.0f}% of the book.", "tone": "good"},
                    {"label": "Grow here.", "text": f"{grow['name']} is the least-penetrated in-scope line{grow_sow} — the clearest headroom to write more premium.", "tone": "warn"},
                ],
                visuals=[
                    ChartBlock("donut", [r["name"] for r in top], [r["premium"] for r in top], f"Mix by {primary.label}"),
                    TableBlock(
                        [{"key": "name", "label": primary.label, "align": "left"},
                         {"key": "premium", "label": "GWP", "kind": "money", "align": "right"},
                         {"key": "sow", "label": "Share of Wallet", "kind": "pct", "align": "right"}],
                        top, title=f"Top {primary.label.lower()}s",
                    ),
                ],
            ))

    # ── Country / industry performance ───────────────────────────────────────
    industry = next((b for b in result.breakdowns if b.column == "SIC_Major_Class"), None)
    if industry and industry.rows:
        top = sorted(industry.rows, key=lambda r: r["premium"] or 0, reverse=True)[:8]
        from studio.narrate import breakdown_takeaways
        geo_visuals: List[Any] = [ChartBlock("bar", [r["name"] for r in top], [r["premium"] for r in top], "Premium by industry")]
        hm = product_country_heatmap(flow, filters, engine)
        if hm and len(hm["columns"]) >= 2:  # only meaningful across ≥2 countries
            geo_visuals.append(HeatmapBlock(hm["rows"], hm["columns"], hm["values"], "Premium: product × country"))
        findings.append(Finding(
            section="geo_industry",
            question="Which industries carry the book?",
            action_title=f"{top[0]['name']} leads the industry book at {money(top[0]['premium'])}",
            implication="Industry concentration mirrors the product mix; diversification opportunities sit in mid-tier sectors.",
            recommendation="Target two adjacent mid-tier industries for planned growth.",
            owner="Industry practice lead", due_date=f"Q1 {(int(year) + 1) if year else ''}".strip(), confidence="high",
            materiality=0.6, evidence=[Evidence(r["name"], money(r["premium"]), (f"{r['sow']:.1f}% wallet" if r.get("sow") is not None else "")) for r in top[:4]],
            takeaways=breakdown_takeaways(industry),
            visuals=geo_visuals,
        ))

    # ── Share of wallet & market position ────────────────────────────────────
    pg = peer_gap(flow, filters, engine, peers=result.peers)
    if rankm or sowm or pg:
        ev = []
        tk = []
        if rankm:
            ev.append(Evidence("Market rank", f"#{rankm['current']}" + (f" of {rankm['of_n']}" if rankm['of_n'] else "")))
            tk.append({"label": "Position.", "text": f"Ranked #{rankm['current']}" + (f" of {rankm['of_n']}" if rankm['of_n'] else "") + " by premium.", "tone": "neutral"})
        if sowm:
            ev.append(Evidence("Share of wallet", f"{sowm['current']:.1f}%", (f"{sowm['delta']:+.1f} pts" if sowm.get('delta') is not None else "")))
            tk.append({"label": "Penetration.", "text": f"Share of Marsh book {sowm['current']:.1f}%" + (f" ({sowm['delta']:+.1f} pts vs {comp})" if sowm.get('delta') is not None else "") + ".", "tone": "good" if (sowm.get('delta') or 0) >= 0 else "danger"})
        if pg and pg.get("ratio"):
            ev.append(Evidence("Vs peer average", f"{pg['ratio']:.2f}x", "aggregate peer GWP (confidential)"))
            tk.append({"label": "Peers.", "text": f"Premium is {pg['ratio']:.2f}x the aggregate peer average.", "tone": "good" if pg["ratio"] >= 1 else "danger"})
        radar = position_radar(
            totals=totals, rankm=rankm, sowm=sowm, pg=pg,
            conc=concentration(primary.rows) if (primary and primary.rows) else None,
        )
        findings.append(Finding(
            section="share_position",
            question="What is the market position versus peers?",
            action_title=(f"Ranked #{rankm['current']}" + (f" of {rankm['of_n']}" if rankm and rankm['of_n'] else "") + " with " + (f"{sowm['current']:.1f}% wallet share" if sowm else "limited penetration")) if rankm else "Market position is mid-tier",
            implication="Wallet share is the clearest lever for rank improvement.",
            recommendation="Convert two large in-appetite accounts to lift wallet share.",
            owner="Distribution lead", due_date=f"Q4 {totals['current_year'] if totals else ''}".strip(), confidence="medium",
            materiality=0.65, evidence=ev, takeaways=tk,
            visual=RadarBlock(radar["labels"], radar["values"], "Competitive position") if radar else None,
        ))

    # ── Whitespace & growth opportunities (with feasibility) ─────────────────
    if result.whitespace:
        ws = result.whitespace
        rows = [{**w, "feasibility": "High" if w["market"] >= 100_000_000 else "Medium"} for w in ws]
        ws_total = sum(w["market"] for w in ws)
        ws_cols = [
            {"key": "name", "label": "Industry", "align": "left"},
            {"key": "market", "label": "Market GWP", "kind": "money", "align": "right"},
            {"key": "feasibility", "label": "Feasibility", "align": "right"},
        ]
        what_changed.append(f"{money(ws_total)} of unwritten whitespace identified")
        findings.append(Finding(
            section="whitespace",
            question="Where is the credible growth?",
            action_title=f"{money(ws_total)} of addressable whitespace across {len(ws)} industries",
            implication="Feasibility is indicative (market size + adjacency); confirm against appetite and capacity.",
            recommendation=f"Stand up appetite + capacity for {ws[0]['name']} (largest, {money(ws[0]['market'])}).",
            owner="New business lead", due_date=f"Q1 {(int(year) + 1) if year else ''}".strip(), confidence="medium",
            materiality=0.85,
            evidence=[Evidence(w["name"], money(w["market"]), f"feasibility {('High' if w['market'] >= 100_000_000 else 'Medium')}") for w in ws[:3]],
            takeaways=[
                {"label": "Size.", "text": f"{money(ws_total)} written by the market, nil by {carrier}.", "tone": "warn"},
                {"label": "Priority.", "text": f"{ws[0]['name']} is the largest single gap.", "tone": "warn"},
                {"label": "Caveat.", "text": "Feasibility indicative — validate against underwriting appetite.", "tone": "neutral"},
            ],
            # Opportunity matrix (premium potential × ease-to-win, both derived
            # from market premium — never random) above the whitespace detail.
            visuals=_whitespace_visuals(flow, filters, engine, ws, ws_cols, rows),
        ))

    # ── Material risks ───────────────────────────────────────────────────────
    risk_points = []
    if movers:
        neg = [m for m in movers if m["delta"] < 0][:2]
        risk_points += [{"label": "Erosion.", "text": f"{m['name']} down {_signed_money(m['delta'])} vs {comp}.", "tone": "danger"} for m in neg]
    if primary and primary.rows:
        conc = concentration(primary.rows)
        if conc and conc["top3"] >= 70:
            risk_points.append({"label": "Concentration.", "text": f"Top-3 lines = {conc['top3']:.0f}% of premium — a soft lead line would hit the book.", "tone": "warn"})
    if risk_points:
        neg_all = [m for m in movers if m["delta"] < 0] if movers else []
        risk_evidence = [Evidence(m["name"], _signed_money(m["delta"]), f"{money(m['prior'])} → {money(m['current'])}") for m in neg_all[:3]]
        risk_visual = (
            ChartBlock("bar", [m["name"] for m in neg_all[:6]], [abs(m["delta"]) for m in neg_all[:6]], "Premium erosion by line")
            if neg_all else None
        )
        findings.append(Finding(
            section="risks", question="What could derail the plan?",
            action_title="Concentration and line-level erosion are the principal risks",
            implication="Risks are identifiable and addressable at the account/line level.",
            recommendation="Assign owners to each risk and review monthly.",
            owner="Chief underwriting officer", due_date=f"Q4 {totals['current_year'] if totals else ''}".strip(),
            confidence="medium", materiality=0.6, takeaways=risk_points,
            evidence=risk_evidence, visual=risk_visual,
        ))

    # ── Actions / decisions ──────────────────────────────────────────────────
    actions = _build_actions(result, movers, year)
    decisions = [a.title for a in actions]

    # ── Data gaps (explicit, never faked) ────────────────────────────────────
    gaps = [
        DataGap("rate_volume_mix", "Rate–exposure–volume decomposition needs policy counts/exposure; the premium ledger holds amounts only."),
        DataGap("retention", "Retention, renewal and new-business analysis needs policy-level transactional data (not in the GPR ledger)."),
        DataGap("prior_actions", "No prior-quarter QBR loaded — previous-action progress cannot be tracked yet."),
    ]
    if flow == "gpr":
        gaps.append(DataGap("survey", "Broker/customer survey not in scope for this Premium view — add Survey scope to include service signals."))
    if not totals:
        gaps.append(DataGap("performance", "No reporting year selected — prior-period comparison unavailable."))

    # ── Thesis + assembly ────────────────────────────────────────────────────
    thesis = _thesis(carrier, totals, result, comp)
    return QBRContentSpec(
        carrier=carrier, country=country, period=period, comparison_period=comp,
        thesis=thesis, what_changed=what_changed[:4],
        findings=findings, actions=actions, decisions=decisions, data_gaps=gaps,
        sources=("GPR — premium ledger", "Peers — aggregate benchmark"),
    )


def _whitespace_visuals(flow, filters, engine, ws, ws_cols, rows) -> List[Any]:
    """Opportunity bubble matrix (if computable) then the whitespace detail table."""
    visuals: List[Any] = []
    points = opportunity_matrix(flow, filters, engine, ws)
    if points:
        visuals.append(MatrixBlock(points, "Opportunity matrix — potential × ease to win"))
    visuals.append(TableBlock(ws_cols, rows))
    return visuals


def _build_actions(result, movers, year) -> List[Action]:
    nxt = f"Q1 {int(year) + 1}" if year else "Next quarter"
    soon = f"Q4 {year}" if year else "This quarter"
    actions: List[Action] = []
    if result.whitespace:
        w = result.whitespace[0]
        actions.append(Action(title=f"Enter {w['name']}", owner="New business lead", due_date=nxt,
                              impact=f"{money(w['market'])} addressable", tag="ENTER", tone="warn"))
    pos = [m for m in movers if m["delta"] > 0]
    if pos:
        actions.append(Action(title=f"Scale {pos[0]['name']}", owner="Product head", due_date=soon,
                              impact=f"{('+' + money(pos[0]['delta']))} momentum", tag="SCALE", tone="good"))
    neg = [m for m in movers if m["delta"] < 0]
    if neg:
        actions.append(Action(title=f"Defend {neg[0]['name']}", owner="Regional placement lead", due_date=soon,
                              impact=f"{money(abs(neg[0]['delta']))} at risk", tag="DEFEND", tone="danger"))
    return actions[:3]


def _thesis(carrier, totals, result, comp) -> str:
    if not totals:
        return f"{carrier}'s position by premium, with the largest growth opportunities highlighted."
    d, p = totals["delta"], totals["pct"]
    dir_word = "grew" if d >= 0 else "declined"
    ws = ""
    if result.whitespace:
        ws_total = sum(w["market"] for w in result.whitespace)
        ws = f" The clearest upside is {money(ws_total)} of unwritten whitespace."
    return (f"{carrier} {dir_word} {pct(p, signed=True) if p is not None else ''} to {money(totals['current'])} versus {comp}, "
            f"with the movement concentrated in a handful of lines.{ws}")
