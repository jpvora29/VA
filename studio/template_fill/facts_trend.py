"""Comparable quarterly observations with reporting-date and coverage checks.

Annual YoY and quarterly QoQ have different bases; their difference is never a
momentum measure. Missing monthly records remain missing rather than becoming zero.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Dict, Mapping, Optional

from logger import get_logger
from studio import compute as C

logger = get_logger(__name__)


def _year_of(label: Optional[str]) -> Optional[int]:
    head = str(label or "").split("-", 1)[0]
    return int(head) if head.isdigit() else None


def _pace(annual: Optional[float], latest_quarter: Optional[float]) -> str:
    """Legacy callers cannot infer a trend from incompatible growth bases."""
    return ""


def _change(current: float, prior: float) -> Optional[float]:
    return (current - prior) / prior * 100 if prior > 0 else None


def load(result, filters: Mapping[str, Any], *, annual_pct: Optional[float] = None
         ) -> Dict[str, Any]:
    year = C._current_year(filters)
    try:
        series = C.period_series(result.flow, dict(filters), result.engine, grain="month") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("facts_trend: monthly coverage unavailable: %s", exc)
        return {}
    months = {}
    for label, value in zip(series.get("labels", ()), series.get("values", ())):
        try:
            y, m = map(int, str(label).split("-"))
            if not 1 <= m <= 12 or not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            if year is None or y <= year:
                months[y * 12 + m - 1] = float(value)
        except (TypeError, ValueError):
            continue
    if not months:
        return {}
    today = date.today()
    current_month = today.year * 12 + today.month - 1
    ends = sorted((i for i in months if i % 3 == 2 and i < current_month
                   and all(j in months for j in range(i - 2, i + 1))), reverse=True)
    if year is not None:
        ends = [i for i in ends if i // 12 == year]
    if not ends:
        return {}
    end = ends[0]
    quarter = f"{end // 12}-Q{end % 12 // 3 + 1}"
    current = sum(months[i] for i in range(end - 2, end + 1))
    out = {"quarter_label": quarter, "quarter_current": current,
           "quarter_prior_label": f"{end // 12 - 1}-Q{end % 12 // 3 + 1}",
           "coverage": "Three observed months per quarter; compared with the same quarter a year earlier",
           "pace": ""}
    if all(i in months for i in range(end - 14, end - 11)):
        prior = sum(months[i] for i in range(end - 14, end - 11))
        out.update(quarter_prior=prior, quarter_delta=current - prior,
                   quarter_yoy=_change(current, prior))
    if all(i in months for i in range(end - 23, end + 1)):
        ttm = sum(months[i] for i in range(end - 11, end + 1))
        prior_ttm = sum(months[i] for i in range(end - 23, end - 11))
        out.update(ttm=ttm, ttm_prior=prior_ttm, ttm_pct=_change(ttm, prior_ttm),
                   ttm_end=f"{end // 12}-{end % 12 + 1:02d}")
    # A very small positive denominator is valid arithmetic but a poor headline.
    prior = out.get("quarter_prior")
    if prior is not None and (prior <= 0 or (current > 0 and prior < current * .05)):
        out["quarter_yoy"] = None
        out["comparison_note"] = "Prior-quarter base is zero, negative or very small; use absolute premiums, not a percentage headline"
    return out


def lines_for(kind: str, facts: Mapping[str, Any]) -> tuple:
    """An observation on the same quarter last year; never an invented trajectory."""
    from studio.template_fill.units import money_level as _money

    trend = (facts or {}).get("trend") or {}
    current, prior = trend.get("quarter_current"), trend.get("quarter_prior")
    if current is None or prior is None or not trend.get("quarter_label"):
        return ()
    delta = current - prior
    if kind not in ({"performance", "thesis", "working"} if delta > 0
                    else {"performance", "thesis", "challenges"} if delta < 0
                    else {"performance", "thesis"}):
        return ()
    subject = facts.get("subject") or "The carrier"
    return (f"{subject} placed {_money(current)} through Marsh in {trend['quarter_label']}, "
            f"compared with {_money(prior)} in {trend['quarter_prior_label']}.",)
