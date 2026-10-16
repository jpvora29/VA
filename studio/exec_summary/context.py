"""The AnalysisContext — the user's Setup selection, normalised once (design Section 3).

Every query, metric and sentence downstream reads this frozen object; nothing re-reads a
raw form value. It is built from the run's ``OverallResult`` because that already holds
the resolved filters, the working book (period applied) and the per-market peer pins the
Setup page produced, so the executive summary and the full QBR answer the same selection
the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from core.boardroom.money import currency_symbol, reporting_currency
from studio.period import display_period

CARRIER_COL = "Carrier_Group"
COUNTRY_COL = "Country"
PRODUCT_COL = "Product_Line"
INDUSTRY_COL = "SIC_Major_Class"
SEGMENT_COL = "Client_Segment"
YEAR_COL = "Year"

#: Filter columns that only say WHEN or WHO — everything else is a slice of the book
#: applied identically to the carrier, its peers and the Marsh book.
_NOT_A_SLICE = {CARRIER_COL, YEAR_COL}

DATA_BASIS_WITH_SURVEY = "premium_survey"


@dataclass(frozen=True)
class AnalysisContext:
    """One focal carrier, one or more countries, one matched pair of periods."""

    carrier: str
    countries: Tuple[str, ...]
    current_year: int
    prior_year: int
    current_label: str
    prior_label: str
    currency: str
    symbol: str
    slice_filters: Dict[str, Any] = field(default_factory=dict)
    peer_pins: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    survey_on: bool = False
    flow: str = "gpr"

    @property
    def multi_country(self) -> bool:
        return len(self.countries) > 1

    @property
    def run_id(self) -> str:
        """A stable id for this context — the same selection gives the same id."""
        import hashlib

        key = "|".join([self.carrier, ",".join(self.countries), str(self.current_year),
                        self.current_label, repr(sorted(self.slice_filters.items()))])
        return "es_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value in (None, "", "all", "All"):
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(v) for v in value if v not in (None, "", "all", "All"))
    return (str(value),)


def current_year_of(filters: Mapping[str, Any]) -> Optional[int]:
    """The reporting year a resolved filter set pins — the max of a multi-select."""
    years = [int(y) for y in _as_tuple(filters.get(YEAR_COL)) if str(y).strip().isdigit()]
    return max(years) if years else None


def slice_filters_of(filters: Mapping[str, Any]) -> Dict[str, Any]:
    """The filters that cut the book (country, product, industry …), minus who and when."""
    return {k: v for k, v in filters.items() if k not in _NOT_A_SLICE and _as_tuple(v)}


def build_analysis_context(result: Any, *, data_basis: Optional[str] = None,
                           latest_year: Optional[int] = None) -> AnalysisContext:
    """Normalise the run's result into the context every step reads.

    ``latest_year`` answers for a run that pinned no year (the latest year in the book);
    the caller looks it up, so this stays a pure mapping.
    """
    filters = dict(getattr(result, "resolved_filters", None) or {})
    carrier = str(getattr(result, "subject", None) or filters.get(CARRIER_COL) or "").strip()
    if not carrier:
        raise ValueError("an executive summary needs one focal carrier")
    year = current_year_of(filters) or latest_year
    if year is None:
        raise ValueError("an executive summary needs a reporting year")
    window = getattr(result, "period", None)
    pins = {str(c): tuple(p) for c, p in (getattr(result, "peers_by_country", None) or {}).items()}
    currency = reporting_currency()
    return AnalysisContext(
        carrier=carrier,
        countries=_as_tuple(filters.get(COUNTRY_COL)),
        current_year=int(year),
        prior_year=int(year) - 1,
        current_label=display_period(window, year),
        prior_label=display_period(window, year, prior=True),
        currency=currency,
        symbol=currency_symbol(currency) or "$",
        slice_filters=slice_filters_of(filters),
        peer_pins=pins,
        survey_on=str(data_basis or "") == DATA_BASIS_WITH_SURVEY,
        flow=str(getattr(result, "flow", "gpr") or "gpr"),
    )


def with_countries(context: AnalysisContext, countries: Sequence[str]) -> AnalysisContext:
    """The same context over an explicit country list (a run that pinned none)."""
    from dataclasses import replace

    return replace(context, countries=tuple(countries))
