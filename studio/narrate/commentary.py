"""Deterministic, rule-based executive commentary.

Reads the computed page result (numbers placed by the renderers / fact store) and
assembles QBR-style commentary by TEMPLATE — no LLM, so it is 100% faithful by
construction. Every page gets commentary from the same generator. The future LLM
narrator (build step 6) can replace this behind the same return contract, with the
faithfulness verifier guarding it.

Returns ``(headline, points, actions)`` where ``points`` = ``[{label, text, tone}]``
— the exact shape ``studio.page.render.commentary`` consumes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from studio.page.format import money, pct
from studio.rules import load_rules

Point = Dict[str, Any]


def _fmt_total(result) -> str:
    for k in result.kpis:
        if k["label"] == "Total GWP":
            return k["value"]
    return "—"


def _total_yoy(result) -> Optional[float]:
    facts = result.store.by_cut("total_yoy")
    if not facts:
        return None
    return max(facts, key=lambda f: int(f.dims.get("year", 0) or 0)).value


def _primary_breakdown(result):
    """The first breakdown section (the page's headline cut)."""
    return result.breakdowns[0] if result.breakdowns else None


def _significant_movers(rows: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """(high-growth, sharp-decline) names, gated by the YoY significance rule."""
    cfg = load_rules().yoy
    hi, lo = [], []
    for r in rows:
        y, p = r.get("yoy"), r.get("premium") or 0.0
        if y is None:
            continue
        if y >= cfg.high_growth_pct and p >= cfg.significant_premium_floor:
            hi.append(f"{r['name']} ({pct(y, signed=True)})")
        elif y <= -10 and p >= cfg.significant_premium_floor:
            lo.append(f"{r['name']} ({pct(y, signed=True)})")
    return hi, lo


def _penetration(rows: List[Dict[str, Any]]) -> Optional[str]:
    have = [r for r in rows if r.get("sow") is not None]
    if not have:
        return None
    best = max(have, key=lambda r: r["sow"])
    worst = min(have, key=lambda r: r["sow"])
    return (
        f"Share of wallet is strongest in {best['name']} ({best['sow']:.1f}%) "
        f"and weakest in {worst['name']} ({worst['sow']:.1f}%)."
    )


def breakdown_takeaways(section) -> List[Point]:
    """Left-rail commentary for one breakdown section (top/movers/penetration)."""
    rows = section.rows
    pts: List[Point] = []
    if rows:
        top = max(rows, key=lambda r: r["premium"] or 0)
        sow = f" at {top['sow']:.1f}% wallet share" if top.get("sow") is not None else ""
        pts.append({"label": "Leader.", "text": f"{top['name']} leads with {money(top['premium'])}{sow}.", "tone": "good"})
    hi, lo = _significant_movers(rows)
    if hi:
        pts.append({"label": "Growth.", "text": f"Fast, material growth in {', '.join(hi)}.", "tone": "good"})
    if lo:
        pts.append({"label": "Decline.", "text": f"Material declines in {', '.join(lo)}.", "tone": "danger"})
    pen = _penetration(rows)
    if pen:
        pts.append({"label": "Penetration.", "text": pen, "tone": "neutral"})
    return pts[:4]


def whitespace_takeaways(result) -> List[Point]:
    pts: List[Point] = []
    if result.whitespace:
        ws_total = sum(w["market"] for w in result.whitespace)
        biggest = result.whitespace[0]
        pts.append({"label": "Scale.", "text": f"{money(ws_total)} of market premium across {len(result.whitespace)} industries you don't write.", "tone": "warn"})
        pts.append({"label": "Priority.", "text": f"{biggest['name']} is the largest single gap at {money(biggest['market'])}.", "tone": "warn"})
        pts.append({"label": "Action.", "text": f"Build a dedicated appetite statement and underwriting capacity for {biggest['name']}.", "tone": "neutral"})
    return pts


def build_swot(result):
    """Deterministic SWOT (DESIGN.md §1 fact-driven quadrant rules)."""
    from studio.deck.model import SwotBlock

    rows = _primary_breakdown(result).rows if result.breakdowns else []
    rank = next((k["value"] for k in result.kpis if k["label"] == "Market Rank"), None)
    sow_total = next((k["value"] for k in result.kpis if k["label"] == "Share of Marsh Book"), None)
    hi, lo = _significant_movers(rows)
    have_sow = [r for r in rows if r.get("sow") is not None]
    top_sow = sorted(have_sow, key=lambda r: r["sow"], reverse=True)[:2]
    low_sow = sorted(have_sow, key=lambda r: r["sow"])[:2]

    strengths = []
    if rank:
        strengths.append(f"Market position at {rank}")
    strengths += [f"Strong penetration in {r['name']} ({r['sow']:.1f}%)" for r in top_sow]
    if hi:
        strengths.append(f"Momentum in {hi[0]}")

    weaknesses = [f"Low share in {r['name']} ({r['sow']:.1f}%)" for r in low_sow]
    weaknesses += [f"Declining {m}" for m in lo]

    opportunities = [f"Whitespace: {w['name']} ({money(w['market'])} market)" for w in result.whitespace[:3]]
    if hi:
        opportunities.append(f"Scale high-growth lines: {', '.join(hi)}")

    threats = []
    if result.whitespace:
        ws_total = sum(w["market"] for w in result.whitespace)
        threats.append(f"{money(ws_total)} written by competitors, not you")
    threats += [f"Erosion risk in {m}" for m in lo]
    if sow_total:
        threats.append(f"Overall wallet share only {sow_total}")

    return SwotBlock(
        strengths=strengths[:4] or ["Established book in core lines"],
        weaknesses=weaknesses[:4] or ["Concentration in a few lines"],
        opportunities=opportunities[:4] or ["Deepen existing relationships"],
        threats=threats[:4] or ["Competitive pricing pressure"],
    )


def build_initiatives(result) -> List[Mapping[str, Any]]:
    """Strategic-initiative cards from whitespace, momentum and soft spots."""
    cards: List[Mapping[str, Any]] = []
    rows = _primary_breakdown(result).rows if result.breakdowns else []
    hi, lo = _significant_movers(rows)

    if result.whitespace:
        w = result.whitespace[0]
        cards.append({"tag": "ENTER", "tone": "warn", "title": f"Enter {w['name']}",
                      "body": f"{money(w['market'])} addressable market, zero current premium. Stand up appetite + capacity."})
    if hi:
        name = hi[0].split(" (")[0]
        cards.append({"tag": "SCALE", "tone": "good", "title": f"Scale {name}",
                      "body": f"Outsized growth ({hi[0].split('(')[1].rstrip(')') if '(' in hi[0] else 'high'}) in a favourable rate environment."})
    if lo:
        name = lo[0].split(" (")[0]
        cards.append({"tag": "DEFEND", "tone": "danger", "title": f"Defend {name}",
                      "body": f"Book contracting ({lo[0].split('(')[1].rstrip(')') if '(' in lo[0] else 'declining'}). Review pricing and protect renewals."})
    # Pad with a penetration play.
    have_sow = [r for r in rows if r.get("sow") is not None]
    if have_sow and len(cards) < 3:
        low = min(have_sow, key=lambda r: r["sow"])
        cards.append({"tag": "DEEPEN", "tone": "neutral", "title": f"Deepen {low['name']}",
                      "body": f"Wallet share only {low['sow']:.1f}% — room to grow with existing clients."})
    return cards[:3]


def build_commentary(result, *, page: str = "overall") -> Tuple[str, List[Point], List[str]]:
    """Assemble (headline, points, actions) for a page from its computed result."""
    subject = result.subject or "The carrier"
    total = _fmt_total(result)
    yoy = _total_yoy(result)
    section = _primary_breakdown(result)
    rows = section.rows if section else []
    dim_label = section.label.lower() if section else "segment"

    points: List[Point] = []
    actions: List[str] = []

    # Momentum / soft spots from the significance-gated movers.
    hi, lo = _significant_movers(rows)
    if hi:
        points.append({"label": "Momentum.", "text": f"Fast, material growth in {', '.join(hi)}.", "tone": "good"})
        actions.append(f"Scale {hi[0].split(' (')[0]} while growth and rate environment are favourable.")
    if lo:
        points.append({"label": "Soft spots.", "text": f"Material declines in {', '.join(lo)}.", "tone": "danger"})
        actions.append(f"Review pricing and defend renewals in {lo[0].split(' (')[0]}.")

    # Penetration.
    pen = _penetration(rows)
    if pen:
        points.append({"label": "Penetration.", "text": pen, "tone": "neutral"})

    # Opportunity (whitespace).
    if result.whitespace:
        ws_total = sum(w["market"] for w in result.whitespace)
        names = ", ".join(w["name"] for w in result.whitespace)
        points.append(
            {
                "label": "Opportunity.",
                "text": f"{names} are written by the market but not by {subject} — "
                f"{money(ws_total)} of whitespace.",
                "tone": "warn",
            }
        )
        actions.append(
            f"Build an appetite statement for {result.whitespace[0]['name']} — "
            f"largest single whitespace ({money(result.whitespace[0]['market'])})."
        )

    # Headline.
    lead = rows[0]["name"] if rows else None
    growth_clause = f" {('up ' + pct(yoy, signed=True)) if yoy is not None else ''}".rstrip()
    headline = (
        f"{subject} wrote {total}{(' (' + growth_clause.strip() + ' YoY)') if yoy is not None else ''}"
        + (f", led by {lead} across {dim_label}." if lead else ".")
    )
    if result.whitespace:
        headline += f" {len(result.whitespace)} material {dim_label.split()[0]} opportunities remain unwritten."

    if not points:
        points.append({"label": "", "text": "No material signals for the current filters.", "tone": "neutral"})

    return headline, points, actions
