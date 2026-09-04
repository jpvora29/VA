"""How concentrated this book is — the fact family that answers "how few lines is this?".

Everything else :func:`studio.template_fill.feedback._facts` loads describes the scope as a
level or a year-on-year move. None of it says how the premium is DISTRIBUTED, so no column
could ever write the sentence a carrier board actually wants to hear about a book: that
three lines carry two thirds of it, and what that means for the one that is shrinking.

One query (:func:`studio.compute.premium_by_dim`) and a pure calculation
(:func:`studio.compute.concentration`), because the whole family is a decomposition of a
single breakdown.

Reported on the dimension the scope is NOT already pinned to: a product sub-deck already
knows it is Cyber, so its concentration question is about countries, not product lines.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from logger import get_logger
from studio import compute as C

logger = get_logger(__name__)

_PRODUCT_COL = "Product_Line"
_COUNTRY_COL = "Country"

# How much of the book the top three lines must carry before it is worth remarking on.
# Below this the book is genuinely spread and "concentrated" would be a false reading.
_CONCENTRATED_TOP3 = 55.0


def _is_pinned(filters: Mapping[str, Any], column: str) -> bool:
    value = (filters or {}).get(column)
    values = tuple(value) if isinstance(value, (list, tuple, set)) else ((value,) if value else ())
    return len(values) == 1


def mix_dimension(filters: Mapping[str, Any]) -> Optional[str]:
    """Which axis this scope's mix is worth reading on, or None when neither is left.

    A scope pinned to one product asks how its premium spreads across MARKETS; anything
    else asks how it spreads across LINES. A scope pinned to both has no mix to report —
    it is already a single cell — and returns None rather than a one-row distribution.
    """
    if _is_pinned(filters, _PRODUCT_COL):
        return None if _is_pinned(filters, _COUNTRY_COL) else _COUNTRY_COL
    return _PRODUCT_COL


def load(result, filters: Mapping[str, Any]) -> Dict[str, Any]:
    """``{dim, label, lead, lead_share, top3, n, concentrated}`` for this scope, or ``{}``.

    ``{}`` on any failure or on a scope with nothing to decompose — the caller folds this
    into the fact dict, and a missing family must cost its own facts and nothing else.
    """
    dim = mix_dimension(filters)
    if dim is None:
        return {}
    try:
        rows = C.premium_by_dim(result.flow, dim, dict(filters), result.engine)
        stats = C.concentration(rows) if rows else None
    except Exception as exc:  # noqa: BLE001 — one fact family must not sink the page
        logger.warning("facts_mix: %s mix failed: %s", dim, exc)
        return {}
    if not stats or not rows or stats.get("n", 0) < 2:
        return {}
    return {
        "dim": dim,
        # Plural, because every sentence this reaches counts them ("62% of 6 lines of
        # business"). "line of business" + "s" is not the plural of "line of business".
        "label": "lines of business" if dim == _PRODUCT_COL else "markets",
        "lead": rows[0]["name"],
        "lead_share": stats["lead"],
        "top3": stats["top3"],
        "n": int(stats["n"]),
        "concentrated": stats["top3"] >= _CONCENTRATED_TOP3,
    }


# Which composer kinds this family deepens. Bucketed rather than pooled, for the reason
# ``stance.PortfolioExtras`` documents: a single shared list is drained by whichever column
# is filled first, and every later column is left where it started.
_LINE_KINDS = frozenset({"thesis", "key_messages", "growth"})


def lines_for(kind: str, facts: Mapping[str, Any]) -> tuple:
    """The sentences this family contributes to a ``kind`` panel — ``()`` for the rest.

    Composed here rather than in :mod:`studio.template_fill.feedback` so one module owns
    the family end to end: how the fact is loaded, and how it is said. The glossary's
    ``concentration`` entry rules the wording — state the shape and let the reader draw
    the conclusion, never call a concentrated book risky.
    """
    mix = (facts or {}).get("mix") or {}
    if kind not in _LINE_KINDS or not mix.get("lead") or mix.get("top3") is None:
        return ()
    lead, label, n = mix["lead"], mix["label"], int(mix["n"])
    if mix.get("concentrated"):
        return (f"{lead} is the largest of {n} {label} at {mix['lead_share']:.1f}% of the "
                f"book, and the top three carry {mix['top3']:.0f}% of everything written.",)
    return (f"Premium is spread across {n} {label} with no single one dominant, {lead} the "
            f"largest at {mix['lead_share']:.1f}% of the book.",)
