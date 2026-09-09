"""The calculation, told as steps a business reader can follow.

The trust panel first showed the SQL. That is the wrong artefact for the person
who needs it: a relationship leader asking "can I trust this number?" cannot read
`SELECT SUM(Premium) ... GROUP BY Product_Line`, and showing it says "trust me,
here is proof you cannot check" — which is worse than showing nothing.

So the query is READ, and described. A SELECT is a small, regular language, and
everything a reader actually wants out of it is recoverable:

    where it started    FROM gpr_fact         -> "Started with premium records"
    what was excluded   WHERE Country='SG'    -> "Narrowed it to country Singapore"
    what was measured   SUM(Premium)          -> "Added up premium for each ..."
    what it was cut by  GROUP BY Product_Line -> "... product line"
    what came out       len(rows)             -> "That left 12 product lines"

Two things this module is deliberate about, both learned from reading the panel
as a user rather than as its author:

**Steps are merged, not enumerated.** Three filters became three lines, and a
measure and its grouping became two more. Eight one-clause lines is a wall; five
sentences that each say a whole thing is a method. So every equality filter joins
one "Narrowed it to ..." sentence, and the aggregate and the GROUP BY join one
"Added up X for each Y".

**The last step says what came out, in the units of the question.** "12 rows came
back" is the machine's unit and means nothing to the reader — it was the single
most confusing line in the panel. When the query grouped by product line, twelve
rows ARE twelve product lines, and the sentence should say so.

Where the SQL cannot be parsed the step list degrades to the honest minimum (the
source and the outcome) rather than guessing. The raw query is still available
for whoever wants it — behind one more click, where a technical detail belongs.

Pure: a query string and a row count in, sentences out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from core.answers import lenses

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
_AGG_CALL = re.compile(r"(?i)\b(sum|avg|mean|count|max|min)\s*\(\s*(?P<arg>[^()]*)\)")

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

# Suffixes a column carries for the database's benefit, not the reader's.
_NOISE_SUFFIX = re.compile(r"(?i)\s+(name|id|code|desc|description|key)$")

# Comparison operators, as words.
_COMPARISONS = {
    ">": "above", ">=": "at or above", "<": "below", "<=": "at or below",
    "<>": "other than", "!=": "other than", "between": "between", "like": "matching",
}


@dataclass(frozen=True)
class Calculation:
    """One query, told as the steps that produced it.

    `title` and `source` name the data in business terms; `steps` are the ordered
    actions; `outcome` says what came out in the units of the question rather
    than in rows. `sql` rides along for the reader who wants the real thing.
    """

    title: str
    steps: Tuple[str, ...] = field(default_factory=tuple)
    outcome: str = ""
    sql: str = ""
    row_count: int = 0

    @property
    def all_steps(self) -> Tuple[str, ...]:
        """The steps plus the outcome — how the panel numbers them."""
        return self.steps + ((self.outcome,) if self.outcome else ())


def humanise(name: str) -> str:
    """A column or table name as a person would say it."""
    text = re.sub(r'[\"`\[\]]', "", str(name or "")).strip()
    text = text.split(".")[-1]
    text = re.sub(r"(?i)^(dim|fact|tbl|vw|stg)_", "", text)
    text = re.sub(r"(?i)_(fact|dim|tbl|vw)$", "", text)
    return text.replace("_", " ").strip().lower()


def field_name(name: str) -> str:
    """A column as a person would REFER to it — "carrier", not "carrier name".

    The `_Name` / `_Id` suffixes are there so the schema can tell a label from a
    key. A reader already knows Zurich is a name.
    """
    return _NOISE_SUFFIX.sub("", humanise(name)).strip() or humanise(name)


def source_of(table: str, lens: str) -> str:
    """What the query read, in business words.

    The lens is trusted over the table because it is the thing the product has a
    name for (see :mod:`core.answers.lenses`); the table is the fallback,
    humanised, so an unmapped source still reads as English rather than as a
    schema object.
    """
    described = lenses.description_of(lens)
    if described:
        return described
    named = humanise(table)
    return f"the {named} data" if named else "the data"


def title_of(lens: str) -> str:
    """The heading for one block of steps.

    The same word the evidence tab uses, with "data" after it — the reader meets
    this source twice on one card and it must not have two names.
    """
    label = lenses.label_of(lens) or humanise(lens).capitalize()
    return f"{label} data" if label else "The data"


def _join(parts: Sequence[str]) -> str:
    """A list as a person writes it — "a, b and c"."""
    items = [p for p in parts if p]
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _plural(noun: str) -> str:
    """Enough pluralisation for the nouns a GROUP BY produces."""
    word = noun.strip()
    if not word or word.endswith("s"):
        return word
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _values_in(raw: str) -> List[str]:
    """The literal values a condition compares against."""
    inner = raw.strip().strip("()")
    parts = [p.strip().strip("'\"") for p in inner.split(",")]
    return [p for p in parts if p]


def _scope_phrase(column: str, value: str) -> str:
    """One equality filter as a phrase that can join the others."""
    name = field_name(column)
    values = _values_in(value)
    if not values:
        return name
    shown = ", ".join(values[:3])
    more = f" and {len(values) - 3} more" if len(values) > 3 else ""
    return f"{name} {shown}{more}"


def _comparison_step(column: str, operator: str, value: str) -> str:
    """One range or pattern filter, which cannot join the scope sentence."""
    values = _values_in(value)
    word = _COMPARISONS.get(operator.lower(), operator)
    target = " and ".join(values[:2]) if values else ""
    return f"Kept only {field_name(column)} {word} {target}".strip()


def _filter_steps(where_body: str) -> List[str]:
    """The WHERE clause as at most two sentences.

    Every equality joins ONE "Narrowed it to ..." — three filters used to be three
    lines, which is how a five-step explanation became an eight-line wall.
    """
    scopes: List[str] = []
    comparisons: List[str] = []
    seen: set = set()
    for condition in _CONDITION.finditer(where_body or ""):
        column, operator, value = condition.group("column", "op", "value")
        if (column.lower(), value) in seen:
            continue
        seen.add((column.lower(), value))
        if operator.lower() in ("=", "in"):
            scopes.append(_scope_phrase(column, value))
        else:
            comparisons.append(_comparison_step(column, operator, value))
    steps: List[str] = []
    if scopes:
        steps.append(f"Narrowed it to {_join(scopes)}")
    steps.extend(comparisons)
    return steps


def _measures(select_body: str) -> List[str]:
    """What the query measured — "Added up premium", deduplicated.

    A window function nests one aggregate inside another (`SUM(SUM(Premium))`),
    and the naive read of that produced a third measure step reading "Added up
    sum(premium". Arguments are matched without brackets in them so a nested call
    contributes nothing of its own; the plain `SUM(Premium)` beside it is the
    measure the reader means.
    """
    out: List[str] = []
    for match in _AGG_CALL.finditer(select_body or ""):
        verb = _AGGREGATES.get(match.group(1).lower(), "Computed")
        argument = match.group("arg").strip()
        phrase = (
            "Counted the matching records"
            if argument in ("*", "")
            else f"{verb} {field_name(argument)}"
        )
        if phrase not in out:
            out.append(phrase)
    return out


def _measure_step(select_body: str, cuts: Sequence[str]) -> List[str]:
    """The measure and the cut it was taken by, as ONE sentence.

    "Added up premium" then "Split it by product line" are two halves of one
    thought, and reading them as separate steps makes the calculation look longer
    and less deliberate than it is.
    """
    measures = _measures(select_body)
    if not measures:
        return [f"Split it by {_join(list(cuts))}"] if cuts else []
    if not cuts:
        return measures
    head = f"{measures[0]} for each {_join(list(cuts))}"
    return [head] + measures[1:]


def _order_step(order_body: str) -> Optional[str]:
    column = order_body.split(",")[0]
    direction = "highest first" if re.search(r"(?i)\bdesc\b", column) else "lowest first"
    cleaned = re.sub(r"(?i)\b(asc|desc)\b", "", column).strip()
    return f"Ranked them by {field_name(cleaned)}, {direction}" if cleaned else None


def _outcome(row_count: int, cuts: Sequence[str]) -> str:
    """What came out, in the units of the question.

    "12 rows came back" is the machine's unit. When the query grouped by product
    line, those twelve rows ARE twelve product lines — and a reader who is told
    that can sanity-check the answer against what they already know about the
    book. This is the line the panel exists to make meaningful.
    """
    if not row_count:
        return ""
    if cuts:
        if len(cuts) > 1:
            noun = "combinations" if row_count != 1 else "combination"
        else:
            noun = _plural(cuts[0]) if row_count != 1 else cuts[0]
        return f"That left {row_count:,} {noun} to report on"
    if row_count == 1:
        return "That gave us a single total"
    return f"That gave us {row_count:,} results"


def describe(sql: str, *, row_count: int = 0, lens: str = "") -> Calculation:
    """The query as an ordered list of plain-English steps.

    Never raises and never guesses: a query it cannot read still yields the two
    things that are always true — where the figures came from, and what came out.
    """
    query = str(sql or "").strip()
    title = title_of(lens)

    if query.lower().startswith(_COMPUTED):
        # A signed-off metric records its provenance instead of a query.
        detail = humanise(query[len(_COMPUTED):].strip()) or "metric"
        return Calculation(
            title=title,
            steps=(f"Used the approved {detail} calculation",),
            outcome=_outcome(row_count, []),
            sql="",
            row_count=row_count,
        )

    table = _FROM.search(query)
    steps: List[str] = [f"Started with {source_of(table.group('table') if table else '', lens)}"]

    where = _WHERE.search(query)
    if where:
        steps.extend(_filter_steps(where.group("body")))

    group = _GROUP.search(query)
    cuts = [field_name(c) for c in group.group("body").split(",") if c.strip()] if group else []

    select = _SELECT.search(query)
    steps.extend(_measure_step(select.group("body") if select else "", cuts))

    order = _ORDER.search(query)
    if order:
        ordered = _order_step(order.group("body"))
        if ordered:
            steps.append(ordered)

    limit = _LIMIT.search(query)
    if limit:
        steps.append(f"Kept the top {limit.group('n')}")

    return Calculation(
        title=title,
        steps=tuple(steps),
        outcome=_outcome(row_count, cuts),
        sql=query,
        row_count=row_count,
    )


def describe_all(queries: Sequence[dict], *, limit: Optional[int] = None) -> List[Calculation]:
    """Every query described, in the order it ran."""
    return [
        describe(
            query.get("sql", ""),
            row_count=int(query.get("row_count") or 0),
            lens=str(query.get("lens") or ""),
        )
        for query in list(queries or [])[:limit]
    ]
