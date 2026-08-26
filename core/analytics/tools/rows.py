"""Computed facts -> the tabular rows the rest of the turn already speaks.

The chart node, the insight writer, the Excel download and the UI table all take
"a list of row dicts". The tool path computes `AnalyticsFact`s instead of running a
SELECT, so this module is the single translation between the two — one pure
function, no side effects, deterministic ordering.

Shape: one row per distinct cut (`fact.dims`), with each fact contributing its own
labelled column. So a turn that computed premium AND its peer average AND share of
wallet for the same product lines renders as ONE table with three value columns,
which is exactly the comparison the reader wants — and something the old
one-SELECT-per-turn path could not produce without a hand-written join.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping, Tuple

from core.analytics.types import AnalyticsFact

# fact.name -> how to label its value column. A callable takes the fact so a
# measure-bearing fact can borrow the real measure name ("Premium", "Score").
_LABELS: Dict[str, Callable[[AnalyticsFact], str]] = {
    "breakdown": lambda f: f.unit or "Value",
    "attribute_breakdown": lambda f: f.unit or "Score",
    "market_presence": lambda f: f"Market_{f.unit or 'Value'}",
    "peer_average": lambda f: f"Peer_Avg_{f.unit or 'Value'}",
    "peer_average_total": lambda f: f"Peer_Avg_{f.unit or 'Value'}",
    "whitespace": lambda f: f"Market_{f.unit or 'Value'}",
    "period_series": lambda f: f.unit or "Value",
    "ttm": lambda f: "TTM",
    "rank": lambda _f: "Rank",
    "yoy": lambda _f: "YoY_%",
    # Named for the span it covers, so a partial-year comparison is self-describing
    # in the table and the reader is never shown a bare "YoY" over half a year.
    "yoy_to_date": lambda f: f"YoY_%_through_{f.dims.get('through') or 'period'}",
    "latest_year": lambda _f: "Latest_Year",
    "latest_quarter": lambda _f: "Latest_Quarter",
    "latest_month": lambda _f: "Latest_Month",
    "period_change": lambda _f: "Change_%",
    "share_of_portfolio": lambda _f: "Share_of_Portfolio_%",
    "share_of_wallet": lambda _f: "Share_of_Wallet_%",
    "nps": lambda _f: "NPS",
    "service_gap": lambda _f: "Gap_vs_Peer",
}


def column_label(fact: AnalyticsFact) -> str:
    """The column this fact's value belongs under."""
    label = _LABELS.get(fact.name)
    return label(fact) if label else fact.name


def _dim_values(facts: Iterable[AnalyticsFact]) -> Dict[str, set]:
    """Distinct value set per dimension key, across every fact."""
    values: Dict[str, set] = {}
    for fact in facts:
        for key, value in fact.dims.items():
            values.setdefault(str(key), set()).add(str(value))
    return values


def _dim_columns(facts: Iterable[AnalyticsFact]) -> Tuple[str, ...]:
    """Every dimension key present, in first-seen order (stable table layout)."""
    columns: List[str] = []
    for fact in facts:
        for key in fact.dims:
            if str(key) not in columns:
                columns.append(str(key))
    return tuple(columns)


def _merge_key(fact: AnalyticsFact, varying: Mapping[str, set]) -> Tuple:
    """The cut a row is keyed on: the dimensions that actually VARY.

    A dimension every fact agrees on (the carrier, when the turn is scoped to one
    carrier) is context, not a cut — keying on it would split "premium by product"
    and "share of wallet by product" into two half-empty tables instead of one
    comparable row per product.
    """
    return tuple(
        sorted(
            (str(k), str(v)) for k, v in fact.dims.items() if str(k) in varying
        )
    )


def facts_to_rows(facts: Iterable[AnalyticsFact]) -> List[Dict[str, Any]]:
    """Fold computed facts into row dicts, one row per distinct varying cut."""
    facts = list(facts)
    if not facts:
        return []

    dim_columns = _dim_columns(facts)
    varying = {key for key, values in _dim_values(facts).items() if len(values) > 1}
    rows: Dict[Tuple, Dict[str, Any]] = {}
    order: List[Tuple] = []

    for fact in facts:
        key = _merge_key(fact, varying)
        row = rows.get(key)
        if row is None:
            row = {
                column: fact.dims.get(column)
                for column in dim_columns
                if column in fact.dims
            }
            rows[key] = row
            order.append(key)
        else:
            # Carry any context dimension this fact adds (e.g. the carrier name a
            # rank fact names but a breakdown fact does not).
            for column in dim_columns:
                if column in fact.dims:
                    row.setdefault(column, fact.dims[column])
        label = column_label(fact)
        # A repeated label on the same cut means two calls computed the same
        # thing; the values are identical (the orchestrator caches), so last wins.
        row[label] = fact.value

    return [rows[key] for key in order]


def facts_digest(facts: Iterable[AnalyticsFact]) -> List[Dict[str, Any]]:
    """Facts as plain dicts — the provenance carried in graph state.

    Keeps `rendered` and `formula` so a reader (or an audit trail) can see both
    the business-ready label and the definition the number came from.
    """
    return [
        {
            "name": fact.name,
            "value": fact.value,
            "unit": fact.unit,
            "rendered": fact.rendered,
            "dims": dict(fact.dims),
            "formula": fact.formula,
        }
        for fact in facts
    ]
