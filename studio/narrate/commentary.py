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

from studio import opportunity as O
from studio.page.format import money, pct
from studio.rules import load_rules

Point = Dict[str, Any]


def _observed(row: Dict[str, Any]) -> O.Opportunity:
    """A whitespace row as what the premium book actually evidences about it.

    The compute layer hands over ``{name, market}`` — Marsh premium placed in a line the
    account does not write. That is the ladder's OBSERVED rung and nothing above it: the
    warehouse holds no appetite or capacity input, so the deck may describe the gap and
    recommend validating it, never entering it (:mod:`studio.opportunity`).
    """
    return O.Opportunity(name=row["name"], pool=row["market"],
                         level=O.level_from_premium_only())


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
            # >100% growth always shows previous + current year premium (the YoY rule);
            # prior is derived exactly from current ÷ (1 + YoY) — no extra query.
            prior = p / (1 + y / 100) if (1 + y / 100) else 0.0
            hi.append(f"{r['name']}, up {pct(y)} from {money(prior)} to {money(p)}")
        elif y <= -10 and p >= cfg.significant_premium_floor:
            lo.append(f"{r['name']}, down {pct(abs(y))} to {money(p)}")
    return hi, lo


def _and(parts: List[str]) -> str:
    """``a``, ``a and b``, ``a, b and c`` — a list said the way it is spoken.

    An item carrying its own comma takes a comma before the "and" too, or the two run
    together; only the items before the last can blur the join.
    """
    if len(parts) < 2:
        return "".join(parts)
    tail = ", and " if any("," in p for p in parts[:-1]) else " and "
    return ", ".join(parts[:-1]) + tail + parts[-1]


def _named(mover: str) -> str:
    """The entity out of a mover phrase — ``"Cyber, up 97.3% …"`` → ``"Cyber"``."""
    return mover.split(",")[0].strip()


def _as_clause(mover: str) -> str:
    """A mover phrase with a verb in it, for prose that opens on the mover.

    ``"Cyber, up 97.3% from …"`` → ``"Cyber grew 97.3% from …"``. The list form keeps the
    appositive so several movers can be joined; a sentence that STARTS with one needs the
    verb, or it reads as a caption.
    """
    for tag, verb in ((", up ", " grew "), (", down ", " fell ")):
        if tag in mover:
            return mover.replace(tag, verb, 1)
    return mover


def _penetration(rows: List[Dict[str, Any]]) -> Optional[str]:
    have = [r for r in rows if r.get("sow") is not None]
    if not have:
        return None
    best = max(have, key=lambda r: r["sow"])
    worst = min(have, key=lambda r: r["sow"])
    return (
        f"The account is best penetrated in {best['name']}, at {best['sow']:.1f}% of the "
        f"wallet, and thinnest in {worst['name']}, at {worst['sow']:.1f}%."
    )


def breakdown_takeaways(section) -> List[Point]:
    """Left-rail commentary for one breakdown section (top/movers/penetration)."""
    rows = section.rows
    pts: List[Point] = []
    if rows:
        top = max(rows, key=lambda r: r["premium"] or 0)
        sow = (f", where the account holds {top['sow']:.1f}% of the wallet"
               if top.get("sow") is not None else "")
        pts.append({"label": "Leader.",
                    "text": f"{top['name']} is the largest book at {money(top['premium'])}{sow}.",
                    "tone": "good"})
    hi, lo = _significant_movers(rows)
    if hi:
        pts.append({"label": "Growth.",
                    "text": f"The fastest material growth came in {_and(hi)}.", "tone": "good"})
    if lo:
        pts.append({"label": "Decline.",
                    "text": f"Premium was given back in {_and(lo)}.", "tone": "danger"})
    pen = _penetration(rows)
    if pen:
        pts.append({"label": "Penetration.", "text": pen, "tone": "neutral"})
    return pts[:4]


def whitespace_takeaways(result) -> List[Point]:
    pts: List[Point] = []
    if result.whitespace:
        ws_total = sum(w["market"] for w in result.whitespace)
        biggest = result.whitespace[0]
        gap = _observed(biggest)
        pts.append({"label": "Scale.",
                    "text": f"Marsh places {money(ws_total)} across "
                            f"{len(result.whitespace)} industries the account does not write.",
                    "tone": "warn"})
        pts.append({"label": "Priority.", "text": O.describe(gap, money=money), "tone": "warn"})
        pts.append({"label": "Action.", "text": O.recommend(gap, money=money),
                    "tone": "neutral"})
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

    # Strengths lead with where the carrier is BIG and well-positioned: high premium
    # (scale), high share of portfolio (appetite), strong wallet penetration, momentum.
    total_prem = sum((r.get("premium") or 0) for r in rows) or 1.0
    top_prem = sorted(rows, key=lambda r: r.get("premium") or 0, reverse=True)[:2]
    strengths = []
    if rank:
        strengths.append(f"The account ranks {rank} within the Marsh book.")
    strengths += [
        f"{r['name']} carries {money(r['premium'])} of the book, "
        f"{(r.get('premium') or 0) / total_prem * 100:.0f}% of everything written."
        for r in top_prem if (r.get("premium") or 0) > 0
    ]
    strengths += [f"Penetration is strongest in {r['name']}, at {r['sow']:.1f}% of the wallet."
                  for r in top_sow]
    if hi:
        strengths.append(f"The momentum is in {hi[0]}.")

    weaknesses = [f"The account holds only {r['sow']:.1f}% of the wallet in {r['name']}, so "
                  f"most of that market is placed elsewhere." for r in low_sow]
    weaknesses += [f"The book is eroding in {m}." for m in lo]

    opportunities = [O.describe(_observed(w), money=money) for w in result.whitespace[:3]]
    if hi:
        opportunities.append(f"There is room to put capacity behind {_and(hi)}.")

    threats = []
    if result.whitespace:
        ws_total = sum(w["market"] for w in result.whitespace)
        threats.append(f"{money(ws_total)} of premium in scope is written by other carriers.")
    threats += [f"Continued erosion in {m} would compound." for m in lo]
    if sow_total:
        threats.append(f"Overall share of wallet is only {sow_total}, which leaves the "
                       f"relationship easy to displace.")

    return SwotBlock(
        strengths=strengths[:4] or ["The account has an established book in its core lines."],
        weaknesses=weaknesses[:4] or ["The book is concentrated in a few lines."],
        opportunities=opportunities[:4] or ["There is room to deepen existing relationships."],
        threats=threats[:4] or ["Competitive pricing pressure is a standing risk."],
    )


def build_initiatives(result) -> List[Mapping[str, Any]]:
    """Strategic-initiative cards from whitespace, momentum and soft spots."""
    cards: List[Mapping[str, Any]] = []
    rows = _primary_breakdown(result).rows if result.breakdowns else []
    hi, lo = _significant_movers(rows)

    if result.whitespace:
        gap = _observed(result.whitespace[0])
        verb = O.action_for(gap.level)
        cards.append({"tag": verb.split()[0].upper(), "tone": "warn",
                      "title": f"{verb} {gap.name}",
                      "body": O.describe(gap, money=money) + " "
                              + O.recommend(gap, money=money)})
    if hi:
        cards.append({"tag": "SCALE", "tone": "good", "title": f"Scale {_named(hi[0])}",
                      "body": f"{_as_clause(hi[0])}, and the rate environment still supports "
                              f"putting capacity behind it."})
    if lo:
        cards.append({"tag": "DEFEND", "tone": "danger", "title": f"Defend {_named(lo[0])}",
                      "body": f"{_as_clause(lo[0])}, so pricing and the renewal book both need "
                              f"reviewing before the next cycle."})
    # Pad with a penetration play.
    have_sow = [r for r in rows if r.get("sow") is not None]
    if have_sow and len(cards) < 3:
        low = min(have_sow, key=lambda r: r["sow"])
        cards.append({"tag": "DEEPEN", "tone": "neutral", "title": f"Deepen {low['name']}",
                      "body": f"The account holds {low['sow']:.1f}% of the wallet here, so most "
                              f"of the growth is available from clients it already serves."})
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
        points.append({"label": "Momentum.",
                       "text": f"The growth is concentrated in {_and(hi)}.", "tone": "good"})
        actions.append(f"Put capacity behind {_named(hi[0])} while the growth and the rate "
                       f"environment still support it.")
    if lo:
        points.append({"label": "Soft spots.",
                       "text": f"Premium was given back in {_and(lo)}.", "tone": "danger"})
        actions.append(f"Review pricing in {_named(lo[0])} and defend the renewal book there.")

    # Penetration.
    pen = _penetration(rows)
    if pen:
        points.append({"label": "Penetration.", "text": pen, "tone": "neutral"})

    # Opportunity (whitespace).
    if result.whitespace:
        ws_total = sum(w["market"] for w in result.whitespace)
        names = _and([w["name"] for w in result.whitespace])
        points.append(
            {
                "label": "Opportunity.",
                "text": f"{names} are placed with other carriers rather than {subject}, "
                f"which is {money(ws_total)} of Marsh premium the account does not write.",
                "tone": "warn",
            }
        )
        actions.append(O.recommend(_observed(result.whitespace[0]), money=money))

    # Headline.
    lead = rows[0]["name"] if rows else None
    movement = f", {'up' if yoy >= 0 else 'down'} {pct(abs(yoy))} on the year" if yoy is not None else ""
    headline = (
        f"{subject} wrote {total}{movement}"
        + (f", led by {lead} across {dim_label}." if lead else ".")
    )
    if result.whitespace:
        headline += (f" {len(result.whitespace)} material {dim_label.split()[0]} "
                     f"opportunities remain unwritten.")

    if not points:
        points.append({"label": "",
                       "text": "The current filters surface no material signals.",
                       "tone": "neutral"})

    return headline, points, actions
