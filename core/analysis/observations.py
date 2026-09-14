"""Reading follow-up decisions out of evidence that has already been gathered.

`core.analysis.progress` decides WHETHER a drill-down is justified, given a list
of findings and a headline. This module produces that list from the rows a turn
actually retrieved, so the decision is driven by results rather than by the
question's wording.

The job is deliberately narrow, because the alternative is a parser that grows a
branch for every query shape a solver can invent. Two sources are read, in order
of trust:

  1. rows produced by `compute_contribution`, which already carry the slice, its
     change and its contribution — the intended path, since the tool exists;
  2. rows carrying a dimension and one numeric column per year, which is what a
     hand-written `run_sql` comparison looks like.

Anything else yields nothing, and yielding nothing is safe: no findings means no
drill-down, which is a bounded answer rather than a wrong one.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.analysis.progress import Finding

#: Column names `compute_contribution` writes through `facts_to_rows`.
CHANGE_COLUMNS = ("contribution", "Contribution", "change", "Change")
CONTRIBUTION_COLUMNS = ("contribution_pp", "Contribution Pp", "Contribution_pp")
HEADLINE_NAMES = ("headline_change", "Headline Change")

#: A bare four-digit year used as a column name, which is how a per-year
#: comparison comes back from a hand-written query.
_YEAR_COLUMN = re.compile(r"^(?:FY)?(19|20)\d{2}$")

#: Columns that are never the SUBJECT of a finding, only its context.
_NOT_A_DIMENSION = frozenset(
    {
        "year", "prior_year", "period", "grain", "position", "coverage",
        "comparable", "percent", "presence", "scope", "contribution_pp",
        "measure_name", "prior_total", "value", "premium", "score",
    }
)


def _number(value: Any) -> Optional[float]:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row: Mapping[str, Any], names: Sequence[str]) -> Optional[float]:
    for name in names:
        if name in row:
            number = _number(row[name])
            if number is not None:
                return number
    return None


def _dimension_of(row: Mapping[str, Any]) -> Tuple[str, str]:
    """The column and value this row is ABOUT, or ("", "") when unclear.

    A row with several candidate dimensions is ambiguous, and an ambiguous
    drill-down target is worse than none — "investigate Property in
    Manufacturing" is a different query from either alone.
    """
    candidates = [
        (column, value)
        for column, value in row.items()
        if isinstance(value, str)
        and value.strip()
        and column.lower() not in _NOT_A_DIMENSION
        and not _YEAR_COLUMN.match(column)
    ]
    return candidates[0] if len(candidates) == 1 else ("", "")


def _year_columns(row: Mapping[str, Any]) -> List[str]:
    return sorted(
        column for column in row
        if _YEAR_COLUMN.match(str(column)) and _number(row[column]) is not None
    )


def finding_from_row(row: Mapping[str, Any], *, source_step: str = "") -> Optional[Finding]:
    """One finding from one result row, or None when the row is not a comparison."""
    dimension, value = _dimension_of(row)
    if not dimension:
        return None

    change = _first(row, CHANGE_COLUMNS)
    if change is None:
        years = _year_columns(row)
        if len(years) < 2:
            return None
        change = _number(row[years[-1]]) - _number(row[years[0]])

    return Finding(
        dimension=dimension,
        value=value,
        change=change,
        contribution_pp=_first(row, CONTRIBUTION_COLUMNS),
        source_step=source_step,
    )


def headline_from_rows(rows: Iterable[Mapping[str, Any]]) -> Optional[float]:
    """The total movement the parts are measured against, if a row states it.

    Preferred over summing the slices: a decomposition that does not reconcile
    would otherwise define its own headline and always appear complete.
    """
    for row in rows:
        name = str(row.get("name") or row.get("Name") or "")
        if name in HEADLINE_NAMES:
            change = _first(row, CHANGE_COLUMNS) or _number(row.get("value"))
            if change is not None:
                return change
        if str(row.get("scope", "")).lower() == "total":
            change = _first(row, CHANGE_COLUMNS)
            if change is not None:
                return change
    return None


def observe(evidence: Sequence[Mapping[str, Any]]) -> Tuple[Tuple[Finding, ...], float]:
    """Findings and the headline they explain, read from gathered evidence.

    Rows from records that did not validate are ignored: a failed query's
    partial output must not steer where the turn looks next.
    """
    from core.analysis.evidence_ledger import quotable

    findings: List[Finding] = []
    headline: Optional[float] = None
    for record in quotable(evidence):
        rows = [row for row in (record.get("rows") or []) if isinstance(row, Mapping)]
        if headline is None:
            headline = headline_from_rows(rows)
        step = str(record.get("step_id", ""))
        for row in rows:
            finding = finding_from_row(row, source_step=step)
            if finding is not None:
                findings.append(finding)

    if headline is None:
        # Fall back to the net of the slices. Weaker, because an incomplete cut
        # then judges its own materiality against an incomplete total — so it is
        # used only when no row stated the whole.
        headline = sum(finding.change for finding in findings)
    return _deduplicate(findings), headline


def _deduplicate(findings: Sequence[Finding]) -> Tuple[Finding, ...]:
    """One finding per (dimension, value); the largest movement wins.

    Two lenses cutting the same way produce the same slice twice, and counting
    it twice would make it look more material than it is.
    """
    best: Dict[Tuple[str, str], Finding] = {}
    for finding in findings:
        key = (finding.dimension, finding.value)
        if key not in best or finding.magnitude > best[key].magnitude:
            best[key] = finding
    return tuple(best.values())
