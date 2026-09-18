"""Choosing the dimension a positioning table should cut by.

Cutting by a column the question already pinned produces a table with one row,
whose "share of portfolio" is 100% by construction. That is what
"Where is maximum penetration possible for Zurich in Canada for property?"
returned: the scope fixed Product_Line, the cut repeated it, and the answer had
nothing to compare.

The rule is a ladder. Take the finest dimension the scope has NOT already fixed:

    Product line  ->  Industry (SIC major)  ->  Industry (SIC minor)  ->  Segment

Ask about a carrier in a country and the table cuts by product. Ask about one
product and it cuts by industry *within* that product. Ask about one industry and
it cuts by sub-industry. Each answer is about the level below the question, which
is where an answer has something to add.

The ladder is read against the flow registry, so a flow without an industry
column simply steps past it rather than producing an empty cut.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

#: Coarse to fine. Cutting by a level the scope already fixed says nothing, so
#: the first UNFIXED level is the one worth showing.
LADDER: Tuple[str, ...] = (
    "Product_Line",
    "SIC_Major_Class",
    "SIC_Minor_Class",
    "Client_Segment",
)

#: What a level is called when the answer names it.
LABELS: Mapping[str, str] = {
    "Product_Line": "product",
    "SIC_Major_Class": "industry",
    "SIC_Minor_Class": "sub-industry",
    "Client_Segment": "segment",
}


def pinned_columns(filters: Mapping[str, Any]) -> set:
    """Columns the scope fixes to a SINGLE value.

    A filter holding several values is still a cut worth showing — "Property and
    Casualty" pins nothing about which of the two the answer is about — so only a
    single-valued filter counts as fixed.
    """
    fixed = set()
    for column, value in (filters or {}).items():
        if isinstance(value, (list, tuple, set)):
            if len(value) == 1:
                fixed.add(str(column))
        elif value not in (None, ""):
            fixed.add(str(column))
    return fixed


def available_columns(flow: str, engine: Any = None) -> List[str]:
    """Ladder columns this flow actually has, in ladder order.

    Checked against the physical table when an engine is available, so a
    warehouse without `SIC_Minor_Class` steps past it instead of returning an
    empty cut that looks like "no data".
    """
    from core.analytics.sql import flow_spec

    try:
        spec = flow_spec(flow)
    except Exception:  # noqa: BLE001 - an unknown flow has no ladder
        return []

    declared = set((getattr(spec, "columns", None) or {}))
    present = declared
    if engine is not None:
        try:
            from core.analytics.sql import table_columns

            physical = set(table_columns(engine, spec.primary_table) or ())
            if physical:
                present = declared & physical if declared else physical
        except Exception:  # noqa: BLE001 - fall back to what the registry declares
            present = declared
    return [column for column in LADDER if not present or column in present]


def choose_dimension(
    filters: Mapping[str, Any],
    *,
    flow: str = "gpr",
    engine: Any = None,
    ladder: Optional[Sequence[str]] = None,
) -> str:
    """The finest level the scope has not already fixed, or "" when none is left.

    Returning "" is a real answer: a question pinned all the way down to a
    sub-industry has nothing below it to break out, and an empty string tells the
    caller to skip the table rather than draw a single row.
    """
    columns = list(ladder) if ladder is not None else available_columns(flow, engine)
    fixed = pinned_columns(filters)
    return next((column for column in columns if column not in fixed), "")


def drilldown_dimension(
    current: str,
    *,
    flow: str = "gpr",
    engine: Any = None,
    ladder: Optional[Sequence[str]] = None,
) -> str:
    """The level below `current`, for a drill-down. "" when `current` is the last."""
    columns = list(ladder) if ladder is not None else available_columns(flow, engine)
    try:
        index = columns.index(current)
    except ValueError:
        return ""
    return columns[index + 1] if index + 1 < len(columns) else ""


def label_for(column: str) -> str:
    """"SIC_Major_Class" -> "industry". What a reader calls the level."""
    if column in LABELS:
        return LABELS[column]
    text = (column or "").replace("_", " ").strip()
    return text.lower() or "slice"


def describe_scope(filters: Mapping[str, Any], dimension: str) -> str:
    """"within Property" — the clause that says what the cut sits inside.

    Only the ladder levels above the chosen cut are named. The carrier, country
    and year are already on screen as scope chips, and repeating them in every
    table caption is the noise that made answers read as boilerplate.
    """
    fixed = pinned_columns(filters)
    above: List[str] = []
    for column in LADDER:
        if column == dimension:
            break
        if column in fixed:
            value = filters[column]
            if isinstance(value, (list, tuple, set)):
                value = next(iter(value))
            above.append(str(value))
    return f" within {', '.join(above)}" if above else ""
