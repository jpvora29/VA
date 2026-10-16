"""The premium cube — the ONE data load the executive summary's commercial facts read.

Two grouped queries (current and prior period) at country × product × SIC major ×
segment × carrier grain, over the WHOLE Marsh book of the selected scope. Every metric
downstream (carrier, peers, Marsh, rank, whitespace) is a pure pandas cut of this frame,
so the carrier and the Marsh book can never be filtered differently (design Section 3),
and a zero-participation industry is visible because the carrier is never filtered in
the query (design Section 10: "a carrier only dataset cannot reveal absent business").
"""
from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

import pandas as pd

from logger import get_logger
from studio.exec_summary.context import (
    CARRIER_COL,
    COUNTRY_COL,
    INDUSTRY_COL,
    PRODUCT_COL,
    SEGMENT_COL,
    YEAR_COL,
    AnalysisContext,
)

logger = get_logger(__name__)

UNMAPPED = "Unmapped"

#: Frame columns, in the order every cut groups by.
DIMS: Tuple[str, ...] = ("country", "product", "industry", "segment", "carrier")
_SOURCE = {"country": COUNTRY_COL, "product": PRODUCT_COL, "industry": INDUSTRY_COL,
           "segment": SEGMENT_COL, "carrier": CARRIER_COL}
COLUMNS: Tuple[str, ...] = (*DIMS, "year", "premium")


def _breakdown_rows(engine: Any, flow: str, group_by: Sequence[str],
                    filters: Dict[str, Any]) -> list:
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    return compute_breakdown(PrimitiveArgs(flow=flow, metric="premium",
                                           group_by=tuple(group_by), filters=filters),
                             engine=engine)


def _rows_for_year(engine: Any, flow: str, filters: Dict[str, Any], year: int) -> list:
    """One period's grouped premium; a book without industry/segment columns still loads."""
    full = [_SOURCE[d] for d in DIMS]
    scoped = {**filters, YEAR_COL: year}
    try:
        return _breakdown_rows(engine, flow, full, scoped)
    except Exception as exc:  # noqa: BLE001 — an uploaded book may lack SIC/segment
        logger.warning("exec_summary.cube: full grain unavailable (%s) — loading without "
                       "industry and segment; both read as Unmapped", exc)
        lean = [_SOURCE[d] for d in DIMS if d not in ("industry", "segment")]
        return _breakdown_rows(engine, flow, lean, scoped)


def _frame(rows: list, year: int) -> pd.DataFrame:
    records = []
    for fact in rows:
        dims = fact.dims or {}
        rec = {d: str(dims.get(_SOURCE[d]) or UNMAPPED) for d in DIMS}
        rec["year"] = year
        rec["premium"] = float(fact.value or 0.0)
        records.append(rec)
    return pd.DataFrame.from_records(records, columns=list(COLUMNS))


def load_premium_cube(context: AnalysisContext, engine: Any) -> pd.DataFrame:
    """Current and prior premium for every carrier in the selected slice."""
    filters = dict(context.slice_filters)
    if context.countries:
        filters[COUNTRY_COL] = list(context.countries)
    frames = [_frame(_rows_for_year(engine, context.flow, filters, y), y)
              for y in (context.current_year, context.prior_year)]
    cube = pd.concat(frames, ignore_index=True)
    return cube.groupby([*DIMS, "year"], as_index=False)["premium"].sum()


def carrier_countries(cube: pd.DataFrame, carrier: str, year: int) -> Tuple[str, ...]:
    """Countries where the carrier writes in ``year``, largest carrier premium first."""
    own = cube[(cube["carrier"].str.lower() == carrier.lower()) & (cube["year"] == year)]
    totals = own.groupby("country")["premium"].sum()
    return tuple(totals[totals > 0].sort_values(ascending=False).index)
