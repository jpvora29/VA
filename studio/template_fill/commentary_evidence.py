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

import re
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

    def as_brief(self, focus: Tuple[str, ...] = ()) -> str:
        """The pack as a prompt block, one citable line per fact.

        ``focus`` is a tuple of fact-id prefixes this column should LEAD from. The pack is
        SPLIT rather than filtered, and that is deliberate: every column on a page was
        handed the same forty facts and, however differently briefed, kept reaching for
        the same six. Filtering the rest away would fix that and break something worse —
        the deterministic draft this column is shown cites whatever ITS composer selected,
        and ``check_numbers`` drops a sentence whose figure is not in the pack, so a family
        trimmed here would silently delete good lines. Leading with a column's own evidence
        steers the writing; keeping the rest keeps it verifiable.

        A focus that matches everything or nothing falls back to the flat list — two
        headings around one block say less than no headings at all.
        """
        if not focus:
            return "\n".join(e.as_line() for e in self.items)
        # The lead block is ordered by the FOCUS, not by the pack: the first prefix a
        # column names is the question it exists to answer, and a lead block that still
        # opens on the headline premium has told the model nothing it did not already
        # prefer. Ties keep pack order, which is why this sorts rather than groups.
        def priority(item: Evidence) -> int:
            return next((i for i, prefix in enumerate(focus)
                         if item.fact_id.startswith(prefix)), len(focus))

        lead = sorted((e for e in self.items if e.fact_id.startswith(focus)), key=priority)
        rest = [e for e in self.items if not e.fact_id.startswith(focus)]
        if not lead or not rest:
            return "\n".join(e.as_line() for e in self.items)
        return "\n".join([
            "LEAD FROM THESE — the facts this column exists to report:",
            *(e.as_line() for e in lead),
            "",
            "ALSO TRUE, for context or a closing line — do not build the column on them:",
            *(e.as_line() for e in rest),
        ])

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
    # The year is a NUMBER to the verifier, and almost every column names it ("Zurich wrote
    # $44M with Marsh in 2025"). Carried only in labels it was never an allowed value, so
    # any model sentence dating its own figure was dropped as unsupported — the same class
    # of silent failure as the "top-5" token below.
    if year:
        _add(out, "period.year", "The reporting year these figures cover",
             str(int(year)), "reporting_year")
        _add(out, "period.prior_year", "The year they are compared with",
             str(int(year) - 1), "reporting_year")
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
    # The rendered form carries the words "top-5" on purpose. ``verifier._TOKEN_RE`` reads
    # the "-5" in "top-5 peer average" as a numeric token and ``_norm`` strips the sign, so
    # a sentence saying "top-5" while citing only this fact was failing verification on an
    # unsupported number "5" and being dropped — silently, and every time, because that is
    # how the benchmark is named in English. Naming it inside the value makes the pack
    # self-describing and the sentence verifiable.
    if _num(peer, "sow") is not None:
        _add(out, "peer.sow", "Top-5 peer average share of wallet",
             f"{peer['sow']:.1f}% (top-5 peer average)", "peer_average")
    if _num(peer, "current") is not None:
        _add(out, "peer.premium", "Top-5 peer average premium in this scope",
             f"{_money(peer['current'])} (top-5 peer average)", "peer_average")
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
#
# This must cover every row a composer can reach, not just the ones it usually picks.
# ``feedback.movement_by_dim`` returns eight, ``_named_moves`` names any two of them and
# ``_capture_gap`` picks whichever pool row the carrier captured least of — which is often
# not in the top four by size. Capped below that, the composer names a mover the pack does
# not carry and ``check_numbers`` drops an otherwise good sentence.
_MAX_MOVERS = 8


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


# ── shape and direction: the two families that are not the headline again ──
#
# Every family above answers "how big" or "how much did it move on the year". These two
# answer "how is it distributed" and "where is it heading", and they are the reason a
# column can now say something the chart beside it does not already show.


def _mix_items(f: Mapping[str, Any], subject: str) -> List[Evidence]:
    """How concentrated the book is, as one citable finding.

    One compound value, not three: ``check_numbers`` scopes a sentence's allowed figures
    to the ids it CITES, so splitting the lead, the top-three share and the count into
    three facts would make a good sentence depend on citing all three correctly.
    """
    mix = f.get("mix") or {}
    lead, label = mix.get("lead"), mix.get("label", "lines")
    if not lead or mix.get("top3") is None:
        return []
    out: List[Evidence] = []
    _add(out, "mix.concentration",
         f"How {subject}'s premium is spread across the {label} it writes",
         f"{lead} is the largest at {mix['lead_share']:.1f}% of the book; the top three "
         f"carry {mix['top3']:.0f}% of {int(mix['n'])} {label}",
         "concentration")
    return out


def _trend_items(f: Mapping[str, Any], subject: str) -> List[Evidence]:
    """Where the book is heading — the only facts in the pack with a time axis.

    The pace fact deliberately carries BOTH figures it is derived from. The glossary
    entry for ``momentum`` requires a sentence to print them, and a figure a sentence may
    print has to be one the pack carries.
    """
    trend = f.get("trend") or {}
    out: List[Evidence] = []
    if trend.get("ttm") is not None and trend.get("ttm_pct") is not None:
        _add(out, "trend.ttm",
             f"{subject}'s premium over the trailing twelve months, against the twelve before",
             f"{_money(trend['ttm'])}, up {abs(trend['ttm_pct']):.1f}% on the prior twelve "
             f"months" if trend["ttm_pct"] >= 0 else
             f"{_money(trend['ttm'])}, down {abs(trend['ttm_pct']):.1f}% on the prior twelve "
             f"months",
             "trailing_twelve_months")
    quarter, pace = trend.get("quarter_pct"), trend.get("pace")
    if quarter is None or not trend.get("quarter_label"):
        return out
    _add(out, "trend.quarter", f"How {subject}'s book moved in the latest closed quarter",
         f"{abs(quarter):.1f}% in {trend['quarter_label']}", "momentum")
    if pace and trend.get("annual_pct") is not None:
        # The year's own movement and the quarter's — the two the reading rests on. NOT
        # the trailing-twelve figure above, which covers a different window: a sentence
        # that prints one while claiming the other is unevidenced in a way no verifier
        # scoped to cited facts can catch.
        _add(out, "trend.pace",
             "The latest quarter read against the pace of the year it closed",
             f"{abs(trend['annual_pct']):.1f}% across the year against "
             f"{abs(quarter):.1f}% in {trend['quarter_label']} — {pace}",
             "momentum")
    return out


# ── the decomposition: where inside the scope the book actually sits ────────
#
# Everything above describes the scope as one number. These describe its SHAPE, and they
# are the facts that let a column name an industry instead of restating the headline.
#
# One Evidence per finding, whose ``rendered`` carries EVERY number its sentence may use.
# ``commentary_verify.check_numbers`` scopes the allowed values to the ids a sentence
# CITES, so splitting a finding into "the share", "the pool" and "the benchmark" would
# force the model to cite three ids correctly or lose an otherwise good line. One compound
# value is one citation, and the sentence either matches it or does not.

_MAX_PER_KIND = 2       # how many of each kind reach the pack — see rules.segments


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def _fact_id(dim_label: str, kind: str, name: str) -> str:
    """``segment.industry.absent.renewable_energy`` — four parts, so it can never collide
    with the two-part ``mover.<name>`` / ``pool.<name>`` ids built above."""
    return f"segment.{_slug(dim_label)}.{kind}.{_slug(name)}"


def _absent_value(row) -> str:
    return (f"{_money(row.market)} placed by Marsh, {_money(row.carrier)} written"
            f"{_peer_value(row)}")


def _peer_value(row) -> str:
    """The aggregate benchmark, when the row has one.

    Carried on THIN and STRONG as well as BEHIND because the prose reaches for it on any
    of them - "and ahead of the top-5 peer average of 12.0%" is a true and useful clause
    on a strong position, and a figure the sentence may print has to be a figure the pack
    carries or ``check_numbers`` drops the whole bullet.
    """
    return (f", top-5 peer average {row.peer_sow:.1f}%"
            if row.peer_sow is not None else "")


def _thin_value(row) -> str:
    return (f"{row.sow:.1f}% of a {_money(row.market)} pool, against a "
            f"{row.placed_sow:.1f}% placed average{_peer_value(row)}, "
            f"{_money(row.stake)} at parity")


def _behind_value(row) -> str:
    # "top-5" spelled inside the value for the same reason peer.sow does it above.
    return (f"{row.sow:.1f}% of a {_money(row.market)} pool, against a "
            f"{row.peer_sow:.1f}% top-5 peer average, {_money(row.stake)} at parity")


def _strong_value(row) -> str:
    return (f"{row.sow:.1f}% of a {_money(row.market)} pool, against a "
            f"{row.placed_sow:.1f}% placed average{_peer_value(row)}")


def _losing_value(row) -> str:
    moved = U.points(row.sow_delta)
    pool = (f", on a pool that moved {abs(row.market_yoy):.1f}%"
            if row.market_yoy is not None else "")
    return (f"down {moved} to {row.sow:.1f}% of a {_money(row.market)} pool{pool}"
            f"{_peer_value(row)}")


# What each class is called in a label, and how its value renders. Dictionary dispatch so a
# new class is a new entry, not a new branch.
_SEGMENT_RENDER: Dict[str, Tuple[str, Any, str]] = {
    "absent": ("Marsh premium in {name} that {subject} writes none of", _absent_value,
               "whitespace"),
    "thin": ("{name} — {subject}'s share against its own placed average", _thin_value,
             "placed_average"),
    "behind": ("{name} — {subject}'s share against the top-5 peer average", _behind_value,
               "peer_average"),
    "strong": ("{name} — where {subject} places above its own average", _strong_value,
               "placed_average"),
    "losing": ("{name} — share given back year on year", _losing_value, "share_of_wallet"),
}


def _segment_items(f: Mapping[str, Any], subject: str) -> List[Evidence]:
    """The scope's industry / client-segment decomposition as citable facts."""
    out: List[Evidence] = []
    for found in (f.get("segments") or {}).values():
        rows = getattr(found, "rows", ())
        if not rows:
            continue
        label = getattr(found, "label", "segment")
        if getattr(found, "placed_sow", None) is not None:
            _add(out, f"segment.{_slug(label)}.placed_share",
                 f"{subject}'s average share across the {label} values it writes",
                 f"{found.placed_sow:.1f}%", "placed_average")
        top3 = getattr(found, "top3_share", None)
        if top3 is not None:
            _add(out, f"segment.{_slug(label)}.concentration",
                 f"Share of the book its three largest {label} groups carry",
                 f"{top3:.0f}%", "concentration")
        seen: Dict[str, int] = {}
        for row in rows:
            kind = row.placement.value
            spec = _SEGMENT_RENDER.get(kind)
            if spec is None or seen.get(kind, 0) >= _MAX_PER_KIND:
                continue
            seen[kind] = seen.get(kind, 0) + 1
            template, render, term = spec
            _add(out, _fact_id(label, kind, row.name),
                 template.format(name=row.name, subject=subject), render(row), term)
    return out


# One builder per fact family, in the order a column reads them. A new family is a new
# function in this tuple — the pack builder itself never changes.
_BUILDERS = (
    lambda f, subject: _carrier_items(f, subject),
    lambda f, subject: _market_items(f),
    lambda f, subject: _standing_items(f, subject),
    lambda f, subject: _gap_items(f),
    lambda f, subject: _mover_items(f, subject),
    lambda f, subject: _mix_items(f, subject),
    lambda f, subject: _trend_items(f, subject),
    lambda f, subject: _segment_items(f, subject),
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
