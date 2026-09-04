"""Choose the ONE evidence set that is the answer's table.

An analyst turn gathers several result sets — the literal answer, a peer
benchmark, a trend, a segment cut, and the discovery queries a solver ran to find
a valid filter value along the way. Exactly one of them is the table the user
should see under the answer.

It used to be whichever one arrived first:

    for item in evidence:
        if item["flow"] == target_flow and item["rows"]:
            return item["rows"]

Independent lenses fan out in parallel and merge through an add-reducer, so
"first" is decided by a race. That is how a premium question came back showing a
list of peer carrier names — a `SELECT DISTINCT Overall_Peer_Group` run to
resolve peer membership had simply finished first.

`select_answer_rows` replaces the race with a score over what an answer table
actually looks like: a signed-off computed metric beats hand-written SQL, the
lens that answers the literal question beats a supporting lens, a real measure
beats a list of names, and a value-discovery query is not an answer at all.
Ties break on the query text, so the same evidence always yields the same table.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

# `compute_metric` records its provenance instead of SQL (see analytics_tool).
_COMPUTED_PREFIX = "-- computed:"

# A value-discovery query ("which industries exist?") is a step towards the
# answer, never the answer itself.
_DISCOVERY_RE = re.compile(r"^\s*select\s+distinct\b", re.IGNORECASE)

# Column names that carry a business measure rather than a label.
_MEASURE_RE = re.compile(
    r"(?i)\b(premium|gwp|amount|value|revenue|score|nps|total|sum|avg|average|"
    r"share|sow|appetite|rank|growth|yoy|qoq|gap|count)\b"
)

# A table a person can read. Below this a result is a scalar (fine, still an
# answer); far above it, it is a dump that belongs in the export, not the card.
_PRESENTABLE_ROWS = 50
_DUMP_ROWS = 200


def _is_computed(sql: str) -> bool:
    return (sql or "").lstrip().startswith(_COMPUTED_PREFIX)


def _is_discovery(sql: str) -> bool:
    return bool(_DISCOVERY_RE.match(sql or ""))


def _columns(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _has_measure_column(rows: Sequence[Dict[str, Any]]) -> bool:
    """True when a column is NAMED like a business measure."""
    return any(_MEASURE_RE.search(str(c)) for c in _columns(rows))


def _has_numeric_column(rows: Sequence[Dict[str, Any]]) -> bool:
    """True when a column actually HOLDS numbers — a list of names has none."""
    sample = list(rows[:10])
    return any(any(_is_number(r.get(c)) for r in sample) for c in _columns(rows))


def score_evidence(evidence: Dict[str, Any], *, primary_lens: str = "") -> float:
    """How much this result set looks like the answer to the user's question."""
    rows = evidence.get("rows") or []
    if not rows:
        return 0.0
    sql = evidence.get("sql") or ""

    score = 1.0
    if _is_computed(sql):
        score += 4.0
    if primary_lens and evidence.get("lens") == primary_lens:
        score += 3.0
    if _has_measure_column(rows):
        score += 2.0
    if _has_numeric_column(rows):
        score += 2.0
    if _is_discovery(sql):
        score -= 6.0
    if len(rows) > _DUMP_ROWS:
        score -= 2.0
    elif len(rows) <= _PRESENTABLE_ROWS:
        score += 1.0
    return score


def select_answer_evidence(
    evidence: Sequence[Dict[str, Any]],
    flow: str,
    *,
    primary_lens: str = "",
) -> Dict[str, Any] | None:
    """The best-scoring non-empty result set for `flow`, or None if there is none.

    Deterministic: ties break on the query text, so a re-run of the same turn
    shows the same table regardless of the order the solvers finished in.
    """
    candidates = [
        e for e in evidence if e.get("flow") == flow and (e.get("rows") or [])
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda e: (-score_evidence(e, primary_lens=primary_lens), e.get("sql") or ""),
    )


def select_answer_rows(
    evidence: Sequence[Dict[str, Any]],
    flow: str,
    *,
    primary_lens: str = "",
) -> List[Any]:
    """The rows of the answer table for `flow` (empty when the flow found none)."""
    best = select_answer_evidence(evidence, flow, primary_lens=primary_lens)
    return list(best.get("rows") or []) if best else []
