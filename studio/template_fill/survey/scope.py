"""What the survey book is asked about: the run's country, year and carrier, in ITS terms.

Setup states a run in the PREMIUM book's language — ``Country``, ``Year``, ``Carrier_Group``.
The survey book has its own columns (``SurveyCountry``, ``Survey_Year``, ``Carrier``) and,
market by market, its own spellings. Translating the selection is therefore the first thing
the page does, and doing it in ONE place is what stops the three ways it used to go wrong:

  * the year was never translated at all, so the page reported the latest year the BOOK
    held while every other slide in the deck reported the year the author picked;
  * the country was passed through verbatim, so a book that writes it differently answered
    nothing — or, worse, the page fell back to a wider cut;
  * the carrier came from the premium side (see :mod:`studio.template_fill.survey.identity`).

The prior year is the previous SURVEYED year, not ``year - 1``. A book surveyed every other
year has no ``year - 1``, and treating that as "nothing to compare with" is what left every
cell on the page without its band colour.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

# What the premium-side selection is keyed by on ``result.resolved_filters``.
PREMIUM_COUNTRY = "Country"
PREMIUM_YEAR = "Year"


@dataclass(frozen=True)
class SurveyScope:
    """The one cut of the survey book a Carrier Survey page reports on.

    Every field is already in the book's own vocabulary, so a holder of this needs no
    further translation — it can go straight into a filter dict.
    """

    country: str
    carrier: str
    year: int
    prior_year: Optional[int] = None

    def filters(self, year: Optional[int] = None) -> Dict[str, Any]:
        """The book filters for this scope's country and carrier at ``year``.

        Defaults to the reporting year; pass :attr:`prior_year` for the comparison cut.
        """
        from studio.template_fill.survey import facts

        return {facts.COUNTRY_COL: self.country,
                facts.CARRIER_COL: self.carrier,
                facts.YEAR_COL: int(self.year if year is None else year)}


# ── the selection, as the run states it ──────────────────────────────────────


def _selected(result, key: str) -> Tuple[Any, ...]:
    """The values pinned for one premium filter, as a tuple (a form hands over lists)."""
    value = (getattr(result, "resolved_filters", None) or {}).get(key)
    values = list(value) if isinstance(value, (list, tuple, set)) else ([value] if value else [])
    return tuple(v for v in values if v not in (None, "", "all", "All"))


def selected_countries(result) -> Tuple[str, ...]:
    """Every country the run pins, in the PREMIUM book's spelling."""
    return tuple(str(v) for v in _selected(result, PREMIUM_COUNTRY))


def selected_years(result) -> Tuple[int, ...]:
    """Every year the run pins. Non-numeric pins are dropped rather than guessed at."""
    out = []
    for value in _selected(result, PREMIUM_YEAR):
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            logger.debug("survey.scope: ignoring non-numeric year pin %r", value)
    return tuple(out)


# ── the book's own vocabulary ────────────────────────────────────────────────


def book_countries(result) -> Tuple[str, ...]:
    """Every country the survey book holds, in its own spelling."""
    from studio.template_fill.survey import facts

    rows = facts._breakdown(result, (facts.COUNTRY_COL,), {})
    return tuple(sorted({str(f.dims[facts.COUNTRY_COL]) for f in rows
                         if f.dims.get(facts.COUNTRY_COL) is not None}))


def book_country(result, country: Any) -> Optional[str]:
    """``country`` as the SURVEY book spells it, or ``None`` when it does not hold it.

    Typography only, the same rule the score labels are matched on: "Hong Kong SAR" is not
    "Hong Kong", and must not be — a page of the wrong market's scores is worse than none.
    """
    from studio.template_fill.survey import facts

    wanted = facts.norm_label(country)
    if not wanted:
        return None
    return next((c for c in book_countries(result) if facts.norm_label(c) == wanted), None)


def book_country_scope(result, countries: Sequence[Any]) -> Tuple[str, ...]:
    """``countries`` in the book's spelling, dropping the ones it has never heard of."""
    matched = [book_country(result, c) for c in countries]
    return tuple(c for c in matched if c)


# ── which year the page reports ──────────────────────────────────────────────


def reporting_years(surveyed: Sequence[Any],
                    selected: Sequence[Any] = ()) -> Tuple[Optional[int], Optional[int]]:
    """``(the year to report, the surveyed year before it)`` — pure, and the whole rule.

    With a year pinned in Setup the page reports THAT year, so the survey table agrees with
    every other slide in the deck. A pinned year the book has no rows for falls back to the
    latest surveyed year BEFORE it — never after: a 2025 score under a deck titled 2024 is
    the failure this replaces. A run that pins no year reports the latest survey there is.
    """
    years = sorted({int(y) for y in surveyed if y is not None})
    if not years:
        return None, None
    wanted = max((int(y) for y in selected), default=None)
    if wanted is None:
        year = years[-1]
    elif wanted in years:
        year = wanted
    else:
        earlier = [y for y in years if y < wanted]
        if not earlier:
            logger.warning("survey.scope: the book's first survey (%d) is after the selected "
                           "year (%d) — the page is not generated", years[0], wanted)
            return None, None
        year = earlier[-1]
        logger.info("survey.scope: no %d survey — reporting the latest before it (%d)",
                    wanted, year)
    before = [y for y in years if y < year]
    return year, (before[-1] if before else None)


def surveyed_years(result, filters: Dict[str, Any]) -> Tuple[int, ...]:
    """Every year the book has rows for under ``filters``."""
    from studio.template_fill.survey import facts

    rows = facts._breakdown(result, (facts.YEAR_COL,), filters)
    return tuple(sorted({int(f.dims[facts.YEAR_COL]) for f in rows
                         if f.dims.get(facts.YEAR_COL) is not None}))


# ── the whole translation, in one call ───────────────────────────────────────


def resolve(result, country: Any) -> Optional[SurveyScope]:
    """The survey cut for ``country``, or ``None`` when the book cannot answer this run.

    ``None`` at any step is a real answer — an unsurveyed market, a carrier the book does
    not hold, a year before its first survey — and the caller drops the page rather than
    reporting a cut it was not asked for.
    """
    from studio.template_fill.survey import facts, identity

    if facts.section_column(result) is None:
        return None
    market = book_country(result, country)
    if market is None:
        logger.info("survey.scope: %r is not in the survey book — no survey page", country)
        return None
    carrier = identity.resolve_carrier(result, (market,))
    if carrier is None:
        return None
    base = {facts.COUNTRY_COL: market, facts.CARRIER_COL: carrier}
    year, prior = reporting_years(surveyed_years(result, base), selected_years(result))
    if year is None:
        return None
    return SurveyScope(country=market, carrier=carrier, year=year, prior_year=prior)
