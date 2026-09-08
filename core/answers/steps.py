"""The calculation, told as steps a business reader can follow.

The trust panel first showed the SQL. That is the wrong artefact for the person
who needs it: a relationship leader asking "can I trust this number?" cannot read
`SELECT SUM(Premium) ... GROUP BY Product_Line`, and showing it says "trust me,
here is proof you cannot check" — which is worse than showing nothing.

So the query is READ, and described. A SELECT is a small, regular language, and
the four things a reader actually wants out of it are all recoverable:

    what was measured   SUM(Premium)          -> "Added up premium"
    what it was cut by  GROUP BY Product_Line -> "Split it by product line"
    what was excluded   WHERE Country='SG'    -> "Limited to Singapore"
    how much came back  len(rows)             -> "12 rows came back"

Where the SQL cannot be parsed the step list degrades to the honest minimum (the
table and the row count) rather than guessing. The raw query is still available
for whoever wants it — behind one more click, where a technical detail belongs.

Pure: a query string and a row count in, sentences out.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence

# The clauses worth describing. Anything else in the query is machinery.
_SELECT = re.compile(r"(?is)\bselect\b(?P<body>.*?)\bfrom\b")
_FROM = re.compile(r"(?is)\bfrom\b\s+(?P<table>[\w\.\"\[\]`]+)")
_WHERE = re.compile(r"(?is)\bwhere\b(?P<body>.*?)(?:\bgroup\s+by\b|\border\s+by\b|\blimit\b|$)")
_GROUP = re.compile(r"(?is)\bgroup\s+by\b(?P<body>.*?)(?:\bhaving\b|\border\s+by\b|\blimit\b|$)")
_ORDER = re.compile(r"(?is)\border\s+by\b(?P<body>.*?)(?:\blimit\b|$)")
_LIMIT = re.compile(r"(?is)\blimit\b\s+(?P<n>\d+)")

# An aggregate and the verb a person would use for it.
_AGGREGATES = {
    "sum": "Added up",
    "avg": "Averaged",
    "mean": "Averaged",
    "count": "Counted",
    "max": "Took the highest",
    "min": "Took the lowest",
}
_AGG_CALL = re.compile(r"(?i)\b(sum|avg|mean|count|max|min)\s*\(\s*(?P<arg>[^)]*)\)")

# A filter as `column op 'value'`, which is what a WHERE clause is made of.
_CONDITION = re.compile(
    r"""(?ix)
    (?P<column>[\w\."\[\]`]+)\s*
    (?P<op>=|<>|!=|>=|<=|>|<|\bin\b|\blike\b|\bbetween\b)\s*
    (?P<value>\([^)]*\)|'[^']*'|"[^"]*"|[\w\.\-]+)
    """
)

# `-- computed: ...` is the provenance a signed-off metric records instead of SQL.
_COMPUTED = "-- computed:"


def humanise(name: str) -> str:
    """A column or table name as a person would say it."""
    text = re.sub(r'[\"`\[\]]', "", str(name or "")).strip()
    text = text.split(".")[-1]
    text = re.sub(r"(?i)^(dim|fact|tbl|vw)_", "", text)
    return text.replace("_", " ").strip().lower()


def _values_in(raw: str) -> List[str]:
    """The literal values a condition compares against."""
    inner = raw.strip().strip("()")
    parts = [p.strip().strip("'\"") for p in inner.split(",")]
    return [p for p in parts if p]


def _filter_sentence(column: str, operator: str, value: str) -> str:
    name = humanise(column)
    values = _values_in(value)
    if not values:
        return f"Filtered on {name}"
    if operator.lower() in ("in", "="):
        shown = ", ".join(values[:3])
        more = f" and {len(values) - 3} more" if len(values) > 3 else ""
        return f"Limited to {name} {shown}{more}"
    words = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below",
             "<>": "excluding", "!=": "excluding", "between": "between",
             "like": "matching"}
    return f"Limited to {name} {words.get(operator.lower(), operator)} {values[0]}"


def _measure_sentences(select_body: str) -> List[str]:
    """What the query measured, one sentence per aggregate."""
    out: List[str] = []
    for match in _AGG_CALL.finditer(select_body or ""):
        verb = _AGGREGATES.get(match.group(1).lower(), "Computed")
        argument = match.group("arg").strip()
        if argument in ("*", ""):
            out.append("Counted the matching records")
        else:
            out.append(f"{verb} {humanise(argument)}")
    return out


def describe(sql: str, *, row_count: int = 0, lens: str = "") -> List[str]:
    """The query as an ordered list of plain-English steps.

    Never raises and never guesses: a query it cannot read still yields the two
    steps that are always true — where the figures came from, and how many
    came back.
    """
    query = str(sql or "").strip()
    steps: List[str] = []

    if query.lower().startswith(_COMPUTED):
        # A signed-off metric records its provenance instead of a query.
        detail = query[len(_COMPUTED):].strip()
        steps.append(f"Used the approved {detail or 'metric'} calculation")
        if row_count:
            steps.append(_rows_sentence(row_count))
        return steps

    table = _FROM.search(query)
    if table:
        steps.append(f"Read the {humanise(table.group('table'))} data")
    elif lens:
        steps.append(f"Read the {lens} data")

    where = _WHERE.search(query)
    if where:
        seen: set = set()
        for condition in _CONDITION.finditer(where.group("body")):
            sentence = _filter_sentence(*condition.group("column", "op", "value"))
            if sentence not in seen:
                seen.add(sentence)
                steps.append(sentence)

    select = _SELECT.search(query)
    steps.extend(_measure_sentences(select.group("body") if select else ""))

    group = _GROUP.search(query)
    if group:
        cuts = [humanise(c) for c in group.group("body").split(",") if c.strip()]
        if cuts:
            steps.append("Split it by " + ", ".join(cuts))

    order = _ORDER.search(query)
    if order:
        column = order.group("body").split(",")[0]
        direction = "highest first" if re.search(r"(?i)\bdesc\b", column) else "lowest first"
        cleaned = re.sub(r"(?i)\b(asc|desc)\b", "", column).strip()
        if cleaned:
            steps.append(f"Ordered by {humanise(cleaned)}, {direction}")

    limit = _LIMIT.search(query)
    if limit:
        steps.append(f"Kept the top {limit.group('n')}")

    if row_count:
        steps.append(_rows_sentence(row_count))
    return steps


def _rows_sentence(row_count: int) -> str:
    return f"{row_count:,} row{'s' if row_count != 1 else ''} came back"


def describe_all(queries: Sequence[dict], *, limit: Optional[int] = None) -> List[dict]:
    """Every query described, in the order it ran.

    Each entry keeps its lens and row count so the panel can label the step list
    without re-deriving them.
    """
    described = []
    for query in list(queries or [])[:limit]:
        described.append(
            {
                "lens": query.get("lens", ""),
                "row_count": query.get("row_count", 0),
                "sql": query.get("sql", ""),
                "steps": describe(
                    query.get("sql", ""),
                    row_count=int(query.get("row_count") or 0),
                    lens=str(query.get("lens") or ""),
                ),
            }
        )
    return described
