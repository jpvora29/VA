"""Apply the turn's period to a HAND-WRITTEN query.

The rule itself — *a question that names no time reference means the latest year,
never an all-years aggregate* — lives in `core.analytics.tools.scope.pin_latest_year`
and is applied by every path that builds its own filters: the deterministic rails,
the analytics tool the solver calls by name, and the position table.

The one path it could not reach is the one where a MODEL writes the SQL. There the
period is a prompt instruction, and an instruction is followed most of the time.
The result is the mismatch this module exists to close: on a question naming no
year, the insight above the table says "2025, the latest year in the data" — it was
computed through the pinned scope — while the table under it silently sums every
year in the book.

So the rule is applied to the query text instead, after the model has written it.

The latest year is read **within the query's own WHERE condition**, not across the
whole table, because that is what every other path already does: `pin_latest_year`
takes the turn's filters. A carrier that stopped writing in 2024 has a latest year
of 2024, and pinning the book's 2025 onto its query would turn a wrong number into
an empty table — a worse answer, not a better one.

Deliberately timid about the rewrite itself. Editing SQL is only safe on a shape
you can be certain about, so `scope_to_year` refuses anything with a CTE, a set
operation, a join, a window function, a subquery or a second statement, and
refuses a query that already names a date column at all. A refusal leaves the
caller running exactly what it ran before — this can narrow a query that was
wrong, and it can decline, but it cannot produce a query that means something else.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)

#: Statement shapes this module will not touch. Each one either makes "where does
#: the WHERE condition end" ambiguous (set operations, subqueries, window ORDER BY)
#: or makes a bare `Year = 2025` ambiguous between two tables (joins).
_UNSAFE = (
    ("a common table expression", re.compile(r"(?i)\bWITH\b")),
    ("a set operation", re.compile(r"(?i)\b(UNION|INTERSECT|EXCEPT)\b")),
    ("a join", re.compile(r"(?i)\bJOIN\b")),
    ("a window function", re.compile(r"(?i)\bOVER\s*\(")),
)

_SELECT = re.compile(r"(?i)\bSELECT\b")
_WHERE = re.compile(r"(?i)\bWHERE\b")

#: The clauses that follow WHERE. The period predicate goes before the first of
#: them, which is also where the WHERE condition ends.
_TAIL = re.compile(r"(?i)\b(GROUP\s+BY|HAVING|WINDOW|ORDER\s+BY|LIMIT|OFFSET|FETCH)\b")


def mentions_column(sql: str, column: str) -> bool:
    """Whether `sql` names `column` anywhere — the test for "this query says when".

    Deliberately not "is there a year PREDICATE": a query that selects, groups by
    or orders on the year has said something about the period, and narrowing it to
    one year would answer a different question than the one it was written for.
    """
    if not column:
        return False
    return bool(re.search(rf"(?i)\b{re.escape(column)}\b", sql or ""))


def unsafe_reason(sql: str) -> str:
    """Why this query must not be rewritten, or "" when it may be.

    Returned as prose rather than a bool so the log line says which shape stopped
    it — the difference between "the guard is off" and "the guard declined this
    query, correctly" is otherwise invisible.
    """
    text = (sql or "").strip().rstrip(";")
    if not text:
        return "an empty statement"
    if ";" in text:
        return "more than one statement"
    for reason, pattern in _UNSAFE:
        if pattern.search(text):
            return reason
    selects = len(_SELECT.findall(text))
    if selects != 1:
        return "a subquery" if selects > 1 else "no SELECT"
    return ""


def _parts(sql: str) -> Tuple[str, str, str]:
    """`sql` split into (everything up to the condition, the condition, the tail).

    The one piece of parsing here, shared so `where_condition` and `scope_to_year`
    cannot disagree about where a WHERE clause ends — the scope the period is READ
    over and the scope it is WRITTEN into have to be the same one.

    A query with no WHERE has an empty condition and a head ending where its tail
    clauses begin.
    """
    text = (sql or "").strip().rstrip(";").rstrip()
    where = _WHERE.search(text)
    tail = _TAIL.search(text, where.end() if where else 0)
    cut = tail.start() if tail else len(text)
    if not where:
        return text[:cut].rstrip(), "", text[cut:].strip()
    return text[:where.end()], text[where.end():cut].strip(), text[cut:].strip()


def where_condition(sql: str) -> str:
    """The slice this query asks about, as its own WHERE condition (or "")."""
    return _parts(sql)[1]


def scope_to_year(sql: str, year_column: str, year: int) -> Optional[str]:
    """`sql` narrowed to one year, or ``None`` when it must be left alone.

    ``None`` on any query that already names the year column, or whose shape this
    module cannot rewrite with certainty (`unsafe_reason`).

    An existing condition is WRAPPED before the predicate is added. Appending a
    bare ``AND`` to ``WHERE a = 1 OR b = 2`` would change what the query means,
    because AND binds tighter than OR — the one mistake a rewrite like this is
    actually likely to make.
    """
    text = (sql or "").strip()
    trailing = ";" if text.endswith(";") else ""
    if unsafe_reason(text) or mentions_column(text, year_column):
        return None

    head, condition, tail = _parts(text)
    predicate = f'"{year_column}" = {int(year)}'
    if _WHERE.search(head):
        if not condition:
            return None
        scoped = f"{head} ({condition}) AND {predicate}"
    else:
        scoped = f"{head} WHERE {predicate}"
    return f"{scoped} {tail}".strip() + trailing


def wants_default_period(question: str) -> bool:
    """Whether this turn left the period for us to choose.

    False the moment the question names one — an explicit year, a quarter, or a
    multi-period term like YoY or trend. The same guard `pin_latest_year` applies,
    read from the same module, so the two cannot drift apart.
    """
    from core.analytics.timeframe import explicit_years, names_a_timeframe

    text = question or ""
    return not (explicit_years(text) or names_a_timeframe(text))


def latest_year_in(
    flow: str, condition: str, *, engine: Optional[object] = None
) -> Optional[int]:
    """The latest year the flow holds WITHIN `condition`, or ``None``.

    Scoped rather than table-wide, matching `pin_latest_year`: the year the insight
    is computed for is the latest one in the turn's scope, so the year the table is
    computed for has to be read the same way or the two disagree again — and a
    table-wide year pinned onto a slice that ended earlier returns no rows at all.

    Never raises. A period this cannot read is a worse answer, not a failed turn.
    """
    from core.analytics.sql import flow_spec, resolve_engine, run_rows

    try:
        spec = flow_spec(flow)
        year_column = spec.date_columns.get("year") or ""
        if not year_column:
            return None
        where = f" WHERE {condition}" if condition else ""
        rows = run_rows(
            resolve_engine(engine),
            f'SELECT MAX("{year_column}") AS latest FROM "{spec.primary_table}"{where}',
            {},
        )
    except Exception:  # noqa: BLE001 - see above
        logger.warning("period guard could not read the latest %s year", flow)
        return None
    latest = rows[0].get("latest") if rows else None
    return int(latest) if latest is not None else None


def may_scope(flow: str, sql: str) -> bool:
    """Whether the period may be applied to this query at all.

    Two refusals, and they are different in kind. The query already names one of
    the flow's date columns — by year, by billing date or by month — so it has
    said WHEN it means and a second period could only contradict it. Or its shape
    is one this module will not edit (`unsafe_reason`).
    """
    if not _year_column(flow) or _states_a_period(flow, sql):
        return False
    reason = unsafe_reason(sql)
    if reason:
        logger.info(
            "period guard declined to scope a %s query: it contains %s", flow, reason
        )
        return False
    return True


def scope_sql_to_year(flow: str, sql: str, year: int) -> Optional[str]:
    """`sql` narrowed to `year` for this flow, or ``None`` to leave it alone.

    For a caller that already knows the year — the analyst solver reads it once
    per slice and applies it to every query it writes over that slice.
    """
    if not may_scope(flow, sql):
        return None
    return scope_to_year(sql, _year_column(flow), year)


def scope_sql_to_default_year(
    flow: str,
    sql: str,
    *,
    question: str,
    engine: Optional[object] = None,
) -> Tuple[str, Optional[int]]:
    """The query, and the year it was narrowed to — or unchanged, and ``None``.

    The whole rule in the order it is decided: did the turn leave the period to
    us, is this a query we may touch, what is the latest year in the slice it asks
    about, and then the rewrite. The cheap questions come first so a query that
    will be declined never costs a `SELECT MAX(year)`.

    The year is returned as well as applied because a default the reader cannot
    see is worse than no default — it is what the answer's scope line states
    (`core.answers.scope.defaulted_period`).
    """
    if not wants_default_period(question) or not may_scope(flow, sql):
        return sql, None

    year = latest_year_in(flow, where_condition(sql), engine=engine)
    if year is None:
        return sql, None
    scoped = scope_to_year(sql, _year_column(flow), year)
    if scoped is None:
        return sql, None
    logger.info(
        "period guard scoped a %s query to %s: the question named no period", flow, year
    )
    return scoped, year


def _year_column(flow: str) -> str:
    """The flow's year column, or "" when the registry cannot be read."""
    from core.analytics.sql import flow_spec

    try:
        return flow_spec(flow).date_columns.get("year") or ""
    except Exception:  # noqa: BLE001 - an unreadable registry never costs the query
        return ""


def _states_a_period(flow: str, sql: str) -> bool:
    """Whether `sql` already names ANY of the flow's date columns."""
    from core.analytics.sql import flow_spec

    try:
        date_columns = flow_spec(flow).date_columns or {}
    except Exception:  # noqa: BLE001 - as above
        return True
    return any(mentions_column(sql, column) for column in date_columns.values())
