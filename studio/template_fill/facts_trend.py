"""Where the book is heading — the fact family that puts a TIME axis in the evidence.

Every other fact a commentary column can cite is a LEVEL or a year-on-year delta: premium,
share, rank, and the same three a year earlier. Two points make a line and nothing more, so
no column could say whether a year's growth was still running at the end of it. That is why
the deck's prose kept landing on "the book grew 28.6%" — from the evidence it had, there
was nothing else true to say about the movement.

Trailing twelve months answers it directly. A book up 28.6% on the year whose latest
quarter moved 5.1% is decelerating, and saying so is worth more to a carrier's board than
the headline repeated a third time. Two cheap primitives (:func:`studio.compute.ttm`,
:func:`studio.compute.qoq`), both of which drop the year filter on purpose so the series
spans the whole history.

Guarded on the reporting year: those primitives return the latest period IN THE DATA, which
is not this page's period when the deck reports on a closed prior year. A trend that ran
past the year being reported is dropped rather than quietly dated wrong.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from logger import get_logger
from studio import compute as C

logger = get_logger(__name__)

# How far the latest quarter must sit from the year's own pace before the difference is
# worth a sentence. Below this the two readings agree and "decelerating" would be noise.
_PACE_GAP = 5.0


def _year_of(label: Optional[str]) -> Optional[int]:
    """The year in a ``2025-Q4`` / ``2025-12`` period label."""
    head = str(label or "").split("-", 1)[0]
    return int(head) if head.isdigit() else None


def _pace(annual: Optional[float], latest_quarter: Optional[float]) -> str:
    """How the latest quarter reads against the year it closed — the whole point.

    Deliberately three words and no more: the judgement belongs to the writer, and the
    numbers behind it travel with it so a sentence can always be verified.
    """
    if annual is None or latest_quarter is None:
        return ""
    gap = latest_quarter - annual
    if abs(gap) < _PACE_GAP:
        return "holding"
    return "accelerating" if gap > 0 else "slowing"


def load(result, filters: Mapping[str, Any], *, annual_pct: Optional[float] = None
         ) -> Dict[str, Any]:
    """``{ttm, ttm_pct, quarter_pct, quarter_label, pace}`` for this scope, or ``{}``.

    ``annual_pct`` is the scope's year-on-year move (``facts["carrier"]["pct"]``), passed
    in rather than re-queried: the pace read is a COMPARISON against it, and re-deriving a
    number the caller already holds is how two figures on one page stop agreeing.
    """
    year = C._current_year(filters)
    try:
        ttm = C.ttm(result.flow, dict(filters), result.engine) or {}
        quarters = C.qoq(result.flow, dict(filters), result.engine) or {}
    except Exception as exc:  # noqa: BLE001 — one fact family must not sink the page
        logger.warning("facts_trend: trend load failed: %s", exc)
        return {}

    quarter_label = quarters.get("latest_label")
    # A series that runs past the year on the page is describing a different period.
    if year is not None and _year_of(quarter_label) not in (None, year):
        return {}

    quarter_pct = quarters.get("latest")
    out = {
        "ttm": ttm.get("current"),
        "ttm_pct": ttm.get("ttm_pct"),
        "quarter_pct": quarter_pct,
        "quarter_label": quarter_label,
        # Carried, not just used: the pace read is a comparison BETWEEN these two, and the
        # glossary's ``momentum`` entry says a sentence describing it must print both. A
        # figure a sentence may print has to be one the evidence carries, so the number the
        # judgement was made on travels with the judgement.
        "annual_pct": annual_pct,
        "pace": _pace(annual_pct, quarter_pct),
    }
    return out if any(v not in (None, "") for v in out.values()) else {}


# Which composer kinds this family deepens, by what the reading MEANS: a book still running
# at the year end is something that is working; one that stopped is a challenge. Both are
# part of where the account stands, so the thesis takes either.
_KINDS_BY_PACE = {
    "slowing": frozenset({"challenges", "thesis"}),
    "accelerating": frozenset({"working", "thesis"}),
    "holding": frozenset({"thesis"}),
}

_PACE_CLAUSE = {
    "slowing": "so the year's growth was not still running when the year closed",
    "accelerating": "so the book was moving faster at the year end than across the year as a whole",
    "holding": "so the year's pace held to the end of it",
}


def lines_for(kind: str, facts: Mapping[str, Any]) -> tuple:
    """The sentences this family contributes to a ``kind`` panel — ``()`` for the rest.

    Prints the two figures the reading REST ON — the year's own movement and the latest
    quarter's — not the trailing-twelve-month total, which is a different window and a
    different number. Printing one figure while judging on another is how a true sentence
    ends up supporting a claim it does not actually evidence.
    """
    trend = (facts or {}).get("trend") or {}
    pace, annual, quarter = trend.get("pace"), trend.get("annual_pct"), trend.get("quarter_pct")
    if not pace or annual is None or quarter is None or not trend.get("quarter_label"):
        return ()
    if kind not in _KINDS_BY_PACE.get(pace, frozenset()):
        return ()
    return (f"The book moved {abs(annual):.1f}% across the year while "
            f"{trend['quarter_label']} moved {abs(quarter):.1f}%, {_PACE_CLAUSE[pace]}.",)
