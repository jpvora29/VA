"""Which PRODUCT LINE an industry or client-segment finding is actually about.

:mod:`studio.segments` decomposes one scope by ONE dimension. On a product page that is
enough, because the product is already pinned by the scope and the commentary can read it
off ``scope.Product_Line``. On a Trading Summary or a country page it is not: the scope
spans every product, so "Transportation & Public Utilities is absent" is a total across
products and a reader cannot tell whether the gap is Marine, Property or Casualty — which
is the difference between a finding somebody can act on and a line they have to go and
research.

This module answers exactly that question and nothing else: for the segment values a
column is going to talk about, which product line carries most of the Marsh premium inside
them, and what the carrier writes in that same cell. One grouped query for the whole set.

It is deliberately NOT part of the classification in :mod:`studio.segments`. Which product
drives a segment does not change whether the segment is absent, thin or behind — it is
detail hung on a finding that already exists, and keeping it separate means the
classification rules stay readable and this stays a lookup.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from core.analytics.library import compute_breakdown
from core.analytics.types import PrimitiveArgs
from logger import get_logger

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_YEAR_COL = "Year"
PRODUCT_COL = "Product_Line"

#: A product carrying less than this share of a segment's Marsh premium is not what that
#: segment is "about" — naming it would trade one misleading summary for another. Set
#: where a plurality is still meaningful but a near-even spread is reported as such.
MIN_SHARE = 35.0


def reset_cache() -> None:
    """Forget every cached breakdown — for tests, and a process that reloads its data."""
    _query.cache_clear()


@dataclass(frozen=True)
class SegmentDriver:
    """The product line that carries a segment, and what the carrier writes in it."""

    segment: str
    product: str
    marsh: float                      # Marsh premium for this product inside this segment
    marsh_share: float                # % of the segment's Marsh premium it carries
    carrier: float = 0.0              # the subject's own premium in the same cell

    @property
    def concentrated(self) -> bool:
        """True when one product genuinely carries the segment."""
        return self.marsh_share >= MIN_SHARE


def scope_pins_one_product(filters: Mapping[str, Any]) -> bool:
    """True when the scope already names a single product line.

    A product page needs none of this: the product is in the scope and the commentary
    reads it off ``scope.Product_Line``. Running the query anyway would cost a breakdown
    to be told what the filters already say.
    """
    value = (filters or {}).get(PRODUCT_COL)
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)):
        return len(value) == 1
    return True


def drivers_for(flow: str, dim: str, filters: Mapping[str, Any], engine: Any, *,
                subject: str, names: Sequence[str] = (),
                year: Optional[int] = None) -> Dict[str, SegmentDriver]:
    """``{segment value: SegmentDriver}`` for the segment values in ``names``.

    One grouped query over ``(dim, product, carrier)`` for the whole scope, then the
    winner per segment. Returns ``{}`` — never raises — when the scope already pins a
    product, when nothing is asked for, or when the query fails: a missing driver costs
    the commentary a product name, and must never cost it the finding.
    """
    wanted = {str(n).strip() for n in names if str(n).strip()}
    if not wanted or scope_pins_one_product(filters):
        return {}
    try:
        rows = _premium_by_product(flow, dim, filters, engine, year=year)
    except Exception as exc:  # noqa: BLE001 — detail on a finding, never a gate
        logger.warning("segment_drivers: no product decomposition (%s)", exc)
        return {}
    return _winners(rows, wanted, subject=subject)


def _filters_key(filters: Mapping[str, Any]) -> Tuple[Tuple[str, Any], ...]:
    """``filters`` as something hashable, so the query below can be cached."""
    out = []
    for col, val in sorted((filters or {}).items()):
        out.append((col, tuple(val) if isinstance(val, (list, set)) else val))
    return tuple(out)


def _premium_by_product(flow: str, dim: str, filters: Mapping[str, Any], engine: Any, *,
                        year: Optional[int]) -> Tuple[Tuple[str, str, str, float], ...]:
    """``(segment, product, carrier, premium)`` for the scope, one query."""
    scoped = {k: v for k, v in (filters or {}).items() if k != _CARRIER_COL}
    if year is not None:
        scoped[_YEAR_COL] = year
    return _query(flow, dim, _filters_key(scoped), engine)


@lru_cache(maxsize=256)
def _query(flow: str, dim: str, key: Tuple[Tuple[str, Any], ...],
           engine: Any) -> Tuple[Tuple[str, str, str, float], ...]:
    """The one query this module runs, cached per scope.

    Cached for the same reason :func:`studio.segments._premium_by_carrier` is: a deck asks
    for the same scope once per country row and again per commentary section, and this is
    a three-way grouped breakdown. Uncached it added a query per scope per dimension to
    every build. A process that reloads its data must call :func:`reset_cache`.
    """
    filters = {col: (list(val) if isinstance(val, tuple) else val) for col, val in key}
    facts = compute_breakdown(
        PrimitiveArgs(flow=flow, metric="premium",
                      group_by=(dim, PRODUCT_COL, _CARRIER_COL), filters=filters),
        engine=engine,
    )
    return tuple(
        (str(f.dims.get(dim)), str(f.dims.get(PRODUCT_COL)),
         str(f.dims.get(_CARRIER_COL)), float(f.value or 0.0))
        for f in facts
        if f.dims.get(dim) is not None and f.dims.get(PRODUCT_COL) is not None
    )


def _winners(rows: Sequence[Tuple[str, str, str, float]], wanted: set, *,
             subject: str) -> Dict[str, SegmentDriver]:
    """The largest product inside each wanted segment, with the subject's own premium."""
    marsh: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    mine: Dict[Tuple[str, str], float] = defaultdict(float)
    low = (subject or "").strip().lower()
    for segment, product, carrier, premium in rows:
        if segment not in wanted:
            continue
        marsh[segment][product] += premium
        if carrier.strip().lower() == low:
            mine[(segment, product)] += premium

    out: Dict[str, SegmentDriver] = {}
    for segment, products in marsh.items():
        total = sum(products.values())
        if not total:
            continue
        # Ties broken by name so two identical runs cannot disagree about which product
        # a finding names — the deck has to be reproducible before it is interesting.
        product = max(sorted(products), key=lambda p: products[p])
        out[segment] = SegmentDriver(
            segment=segment, product=product, marsh=products[product],
            marsh_share=products[product] / total * 100.0,
            carrier=mine.get((segment, product), 0.0),
        )
    return out
