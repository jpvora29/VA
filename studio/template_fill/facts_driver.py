"""The driver of the year's move, said the way an ICL opens with it — a fact family.

The composers already say THAT premium fell and name the lines that moved most. What they
never said is the sentence a consulting leader leads a decline with: which line the fall
came from, how much of it, whether Marsh's own market in that line fell too, and — on the
survey basis — whether the same line's survey score points the same way. This family adds
that sentence to the panels that argue the result (see ``feedback._FACT_FAMILIES``).

Pure: the facts dict in, sentences out. The facts it reads are the ones
``feedback._facts`` already loads (``carrier``, ``movers``, ``pool``, ``mover_dim``,
``survey_lines``), so it costs no query.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional

from studio.template_fill.render import _money

#: The driver is the second thing said on a panel, straight after the headline movement
#: (``feedback.points``) — a trimmed panel must keep it.
LEADS = True

#: Which panels hear about a decline, and which about growth.
_DECLINE_PANELS = ("challenges", "key_messages", "thesis")
_GROWTH_PANELS = ("working", "highlights", "key_messages", "thesis")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def driver(f: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """``{name, delta, total, share}`` for the mover behind most of the move, else ``None``."""
    carrier = f.get("carrier") or {}
    current, prior = _number(carrier.get("current")), _number(carrier.get("prior"))
    if current is None or prior is None or current == prior:
        return None
    total = current - prior
    same_way = [r for r in (f.get("movers") or [])
                if r.get("name") and _number(r.get("delta")) and r["delta"] * total > 0]
    if len(f.get("movers") or []) < 2 or not same_way:
        return None                      # one line cannot "drive" its own total
    top = max(same_way, key=lambda r: abs(r["delta"]))
    return {"name": str(top["name"]), "delta": float(top["delta"]), "total": total,
            "share": abs(top["delta"]) / abs(total) * 100}


def _market_clause(f: Mapping[str, Any], name: str, total: float) -> str:
    """Whether Marsh's own placements in the same line moved with the carrier or against it."""
    pool = next((r for r in (f.get("pool") or []) if _norm(r.get("name")) == _norm(name)), None)
    delta = _number((pool or {}).get("delta"))
    if delta is None or not delta:
        return ""
    if (delta > 0) != (total > 0):
        way = "grew" if delta > 0 else "shrank"
        return f", while Marsh's own {name} placements {way} by {_money(abs(delta))}"
    return f", in step with Marsh's own {name} placements, which also {'grew' if delta > 0 else 'fell'}"


def _survey_clause(f: Mapping[str, Any], name: str, total: float) -> str:
    """The same line's survey score, when the run draws on the survey and the survey has it.

    "The same way" means the score moved the way the premium did — down with a decline, up
    with growth. A score that fell in a line that grew reads DIFFERENTLY, and saying
    otherwise is the kind of slip a carrier's executives notice first.
    """
    row = next((r for r in (f.get("survey_lines") or [])
                if _norm(r.get("line")) == _norm(name) or _norm(r.get("practice")) == _norm(name)),
               None)
    score, delta = _number((row or {}).get("score")), _number((row or {}).get("delta"))
    if row is None or score is None:
        return ""
    practice = str(row.get("practice") or name)
    if delta is None or not row.get("prior_year"):
        return f" The carrier survey scores {practice} at {score:.2f}."
    if not delta:
        return f" The carrier survey scores {practice} at {score:.2f}, unchanged on {row['prior_year']}."
    way = "down" if delta < 0 else "up"
    agrees = (delta < 0) == (total < 0)
    lead = "points the same way" if agrees else "reads differently"
    return (f" The carrier survey {lead}: {practice} scored {score:.2f}, "
            f"{way} {abs(delta):.2f} on {row['prior_year']}.")


def decline_line(f: Mapping[str, Any]) -> str:
    found = driver(f)
    if not found or found["total"] >= 0:
        return ""
    name, lost, total = found["name"], abs(found["delta"]), abs(found["total"])
    if found["share"] > 100:
        head = (f"{name} is where the year went wrong: Marsh-placed premium there fell "
                f"{_money(lost)}, more than the carrier's {_money(total)} net fall")
    else:
        head = (f"{name} is where most of the fall came from: {_money(lost)} of the "
                f"carrier's {_money(total)} decline in Marsh-placed premium "
                f"({found['share']:.0f}%)")
    return (head + _market_clause(f, name, found["total"]) + "."
            + _survey_clause(f, name, found["total"]))


def growth_line(f: Mapping[str, Any]) -> str:
    found = driver(f)
    if not found or found["total"] <= 0:
        return ""
    name, gained, total = found["name"], found["delta"], found["total"]
    if found["share"] > 100:
        return (f"{name} carried the year: it added {_money(gained)}, more than the "
                f"carrier's {_money(total)} net gain, so the other lines gave ground.")
    return (f"{name} carried most of the growth: {_money(gained)} of the {_money(total)} "
            f"added ({found['share']:.0f}%)" + _market_clause(f, name, total) + "."
            + _survey_clause(f, name, total))


def lines_for(kind: str, f: Dict[str, Any]) -> List[str]:
    """The driver sentence for the panels that argue this year's result."""
    if kind in _DECLINE_PANELS:
        line = decline_line(f)
        if line:
            return [line]
    if kind in _GROWTH_PANELS:
        line = growth_line(f)
        if line:
            return [line]
    return []
