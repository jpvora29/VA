"""Pure pivot computation over the working frame — deterministic in and out.

``slice_frame`` applies a pivot's filters (the same slice that scopes the deck
when the dataset is submitted); ``build_pivot`` aggregates the sliced frame.
Everything is pandas server-side — AG Grid only displays the result.
"""
from __future__ import annotations

import pandas as pd

from studio.dataset.model import PivotSpec

_AGG = {"sum": "sum", "avg": "mean", "count": "count"}


def slice_frame(frame: pd.DataFrame, spec: PivotSpec) -> pd.DataFrame:
    """Rows matching every pivot filter — the deck's row-level slice."""
    out = frame
    for column, values in spec.filters:
        if column in out.columns and values:
            out = out[out[column].astype(str).isin([str(v) for v in values])]
    return out


def build_pivot(frame: pd.DataFrame, spec: PivotSpec) -> pd.DataFrame:
    """The pivot table as a flat frame (rows first, deterministic order).

    Raises ``ValueError`` when the spec references missing columns so the UI
    can show the reason instead of a stack trace.
    """
    if not spec.is_runnable:
        raise ValueError("Pick at least one row dimension and a values column.")
    missing = [c for c in (*spec.rows, spec.cols, spec.values) if c and c not in frame.columns]
    if missing:
        raise ValueError(f"Column(s) not in the dataset: {', '.join(missing)}")
    sliced = slice_frame(frame, spec)
    if sliced.empty:
        return pd.DataFrame(columns=list(spec.rows))
    agg = _AGG.get(spec.aggregation, "sum")
    table = pd.pivot_table(
        sliced,
        index=list(spec.rows),
        columns=spec.cols or None,
        values=spec.values,
        aggfunc=agg,
        fill_value=0,
    )
    # Flatten to a plain grid-friendly frame with stable ordering.
    if isinstance(table, pd.Series):
        table = table.to_frame(spec.values)
    table = table.sort_index()
    flat = table.reset_index()
    flat.columns = [str(c) for c in flat.columns]
    return flat
