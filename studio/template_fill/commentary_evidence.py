"""The facts a commentary column may argue from, as citable evidence.

``feedback._facts`` returns a nested dict of raw numbers. That is the right shape for the
rule composers, which reach into it by key, and the wrong shape for a model: it carries no
labels, no units, no rendered forms, and nothing that says what a number MEANS — so a model
handed it invents its own reading ("rank 5" becomes "fifth in the market") and the verifier
can only check that the digits survived.

An :class:`EvidencePack` is the same facts with an id, a label, a rendered value and a
glossary term attached to each. That buys three things at once:

* the model writes from evidence rather than from pre-written sentences, so it can drop a
  claim, merge two, or lead with the consequence — the editorial moves a partner makes;
* every sentence cites the ids behind it, so verification asks "is this claim supported"
  rather than "did the digits survive";
* the ICG definition of each term travels with it (:mod:`core.definitions`), so "share of
  wallet" cannot quietly become "market share" on the way to the page.

Pure: a dict in, a frozen pack out. No IO, no LLM, no formatting policy beyond the words.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from studio.template_fill import units as U
from studio.template_fill.render import _money


@dataclass(frozen=True)
class Evidence:
    """One citable fact."""

    fact_id: str
    label: str
    rendered: str
    term: str = ""              # glossary key, when the fact IS a defined concept

    def as_line(self) -> str:
        return f"[{self.fact_id}] {self.label}: {self.rendered}"


@dataclass(frozen=True)
class EvidencePack:
    """Everything one column is allowed to say, and nothing else."""

    subject: str
    items: Tuple[Evidence, ...] = ()

    def get(self, fact_id: str) -> Optional[Evidence]:
        return next((e for e in self.items if e.fact_id == fact_id), None)

    def terms(self) -> Tuple[str, ...]:
        """The glossary keys in play — what the writer needs defined."""
        return tuple(dict.fromkeys(e.term for e in self.items if e.term))

    def as_brief(self) -> str:
        """The pack as a prompt block, one citable line per fact."""
        return "\n".join(e.as_line() for e in self.items)

    def rendered_values(self, fact_ids: Tuple[str, ...] = ()) -> Tuple[str, ...]:
        """The rendered forms of the cited facts (or all of them) — the verifier's source."""
        wanted = [e for e in self.items if not fact_ids or e.fact_id in fact_ids]
        return tuple(e.rendered for e in wanted)


def _num(mapping: Mapping[str, Any], key: str) -> Optional[float]:
    value = (mapping or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _add(out: List[Evidence], fact_id: str, label: str, rendered: str, term: str = "") -> None:
    """Append a fact, skipping the ones that rendered to nothing."""
    if rendered and rendered.strip():
        out.append(Evidence(fact_id, label, rendered.strip(), term))


def _carrier_items(f: Mapping[str, Any], subject: str) -> List[Evidence]:
    out: List[Evidence] = []
    c = f.get("carrier") or {}
    year = c.get("current_year")
    when = f" in {int(year)}" if year else ""
    if _num(c, "current") is not None:
        _add(out, "carrier.premium", f"Premium {subject} placed with Marsh{when}",
             _money(c["current"]), "premium")
    if _num(c, "pct") is not None:
        _add(out, "carrier.yoy", f"{subject}'s premium movement year on year",
             f"{abs(c['pct']):.1f}%", "yoy")
    if _num(c, "delta") is not None:
        _add(out, "carrier.delta", f"{subject}'s premium movement in money",
             _money(abs(c["delta"])), "premium")
    return out


def _market_items(f: Mapping[str, Any]) -> List[Evidence]:
    out: List[Evidence] = []
    m = f.get("marsh") or {}
    if _num(m, "current") is not None:
        _add(out, "marsh.premium", "Total premium Marsh placed in this scope, all carriers",
             _money(m["current"]), "marsh_book")
    if _num(m, "pct") is not None:
        _add(out, "marsh.yoy", "The wider Marsh book's movement year on year",
             f"{abs(m['pct']):.1f}%", "yoy")
    carrier, market = _num(f.get("carrier") or {}, "current"), _num(m, "current")
    if carrier is not None and market is not None and market > carrier:
        _add(out, "headroom", "Marsh premium in this scope placed with OTHER carriers",
             _money(market - carrier), "headroom")
    return out


def _standing_items(f: Mapping[str, Any], subject: str) -> List[Evidence]:
    out: List[Evidence] = []
    r, s, peer = f.get("rank") or {}, f.get("sow") or {}, f.get("peer") or {}
    if r.get("current") is not None:
        field = f" of {int(r['of_n'])}" if r.get("of_n") else ""
        _add(out, "rank.current", f"{subject}'s position by premium within the Marsh book",
             f"#{int(r['current'])}{field}", "rank")
    if _num(r, "delta") is not None and r["delta"]:
        way = "improved" if r["delta"] > 0 else "slipped"
        _add(out, "rank.delta", f"Rank {way} by",
             f"{abs(int(r['delta']))} place" + ("s" if abs(r["delta"]) != 1 else ""), "rank")
    if _num(s, "current") is not None:
        _add(out, "sow.current", f"{subject}'s share of the Marsh book in this scope",
             f"{s['current']:.1f}%", "share_of_wallet")
    if _num(s, "delta") is not None and not U.is_flat(s["delta"]):
        way = "rose" if s["delta"] > 0 else "fell"
        _add(out, "sow.delta", f"Share of wallet {way} by",
             U.points(s["delta"]), "percentage_point")
    if _num(peer, "sow") is not None:
        _add(out, "peer.sow", "Top-5 peer average share of wallet",
             f"{peer['sow']:.1f}%", "peer_average")
    if _num(peer, "current") is not None:
        _add(out, "peer.premium", "Top-5 peer average premium in this scope",
             _money(peer["current"]), "peer_average")
    return out


def _gap_items(f: Mapping[str, Any]) -> List[Evidence]:
    """What the distance to the peer benchmark is, and what closing it is worth."""
    out: List[Evidence] = []
    share = _num(f.get("sow") or {}, "current")
    peer_share = _num(f.get("peer") or {}, "sow")
    market = _num(f.get("marsh") or {}, "current")
    if share is None or peer_share is None:
        return out
    gap = peer_share - share
    if abs(gap) >= 0.05:
        side = "below" if gap > 0 else "above"
        _add(out, "peer.gap", f"Share of wallet sits this far {side} the peer average",
             U.points(gap), "percentage_point")
    if market:
        point = market / 100.0
        _add(out, "share.point_value", "What one point of share of wallet is worth",
             _money(point), "share_of_wallet")
        if abs(gap) >= 0.05:
            _add(out, "peer.gap_value", "Premium value of closing the gap to the peer average",
                 _money(abs(gap) * point), "premium")
    return out


# Named movers are worth a fact each: a decomposition is the only thing that lets a column
# say WHY the headline moved, and a model with no line-level evidence can only restate it.
_MAX_MOVERS = 4


def _mover_items(f: Mapping[str, Any], subject: str) -> List[Evidence]:
    out: List[Evidence] = []
    for row in (f.get("movers") or [])[:_MAX_MOVERS]:
        name, delta = row.get("name"), row.get("delta")
        if not name or not isinstance(delta, (int, float)):
            continue
        way = "added" if delta > 0 else "gave back"
        pct = f" ({abs(row['pct']):.1f}%)" if isinstance(row.get("pct"), (int, float)) else ""
        _add(out, f"mover.{name}", f"{subject} {way} premium in {name}",
             f"{_money(abs(delta))}{pct}", "premium")
    for row in (f.get("pool") or [])[:_MAX_MOVERS]:
        name, delta = row.get("name"), row.get("delta")
        if not name or not isinstance(delta, (int, float)) or delta <= 0:
            continue
        _add(out, f"pool.{name}", f"The Marsh book in {name} grew by",
             _money(delta), "marsh_book")
    return out


# One builder per fact family, in the order a column reads them. A new family is a new
# function in this tuple — the pack builder itself never changes.
_BUILDERS = (
    lambda f, subject: _carrier_items(f, subject),
    lambda f, subject: _market_items(f),
    lambda f, subject: _standing_items(f, subject),
    lambda f, subject: _gap_items(f),
    lambda f, subject: _mover_items(f, subject),
)


def build_pack(facts: Mapping[str, Any]) -> EvidencePack:
    """Turn one :func:`studio.template_fill.feedback.facts_for` dict into citable evidence."""
    subject = str((facts or {}).get("subject") or "The carrier")
    items: List[Evidence] = []
    for build in _BUILDERS:
        items += build(facts or {}, subject)
    seen: Dict[str, Evidence] = {}
    for item in items:                       # first writer of an id wins; order preserved
        seen.setdefault(item.fact_id, item)
    return EvidencePack(subject=subject, items=tuple(seen.values()))
