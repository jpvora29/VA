"""Independent reference calculations — the numerical authority for the suite.

These are computed in plain Python straight from `scenario.py`, never through
`core.analytics`. That independence is the whole point: a check that derived its
expected value from the same primitive it is auditing would pass by construction.
`tests/evaluation/test_warehouse.py` closes the loop by proving that hand-written
SQL over the built warehouse agrees with these, so a faithful warehouse and a
faithful oracle are each verified without either trusting the library.

Everything returns plain numbers and dicts. Rounding is applied only where a
figure is quoted to a reader.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from tests.evaluation import scenario


def _subject_rows():
    return [
        cell
        for cell in scenario.subject_cells()
        if cell.country == scenario.COUNTRY and cell.carrier == scenario.CARRIER
    ]


# --------------------------------------------------------------------------- #
# Premium totals
# --------------------------------------------------------------------------- #


def annual_premium(year: int) -> float:
    """Subject premium for one year, in the evaluated country."""
    return sum(cell.premium for cell in _subject_rows() if cell.year == year)


def premium_by_product(year: int) -> Dict[str, float]:
    totals: Dict[str, float] = defaultdict(float)
    for cell in _subject_rows():
        if cell.year == year:
            totals[cell.product] += cell.premium
    return dict(totals)


def premium_by_quarter(year: int) -> Dict[int, float]:
    totals: Dict[int, float] = defaultdict(float)
    for cell in _subject_rows():
        if cell.year == year:
            totals[cell.quarter] += cell.premium
    return dict(totals)


def premium_by_industry(year: int, *, product: str = "") -> Dict[str, float]:
    totals: Dict[str, float] = defaultdict(float)
    for cell in _subject_rows():
        if cell.year == year and (not product or cell.product == product):
            totals[cell.industry] += cell.premium
    return dict(totals)


def marsh_book_by_product(year: int) -> Dict[str, float]:
    """Every carrier's premium in the market, by product — the whitespace base.

    Only the carrier filter is removed; country and year still apply. Removing
    more would compare the subject's market against a different population.
    """
    totals: Dict[str, float] = defaultdict(float)
    for cell in scenario.all_cells():
        if cell.country == scenario.COUNTRY and cell.year == year:
            totals[cell.product] += cell.premium
    return dict(totals)


# --------------------------------------------------------------------------- #
# Movement
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Movement:
    """A year-on-year movement and the two figures behind it."""

    prior: float
    current: float

    @property
    def absolute(self) -> float:
        return self.current - self.prior

    @property
    def percent(self) -> float:
        """Undefined on a zero base — callers must check, never divide blindly."""
        if self.prior == 0:
            raise ZeroDivisionError("percentage change on a zero prior value")

        return self.absolute / self.prior * 100


def headline_movement() -> Movement:
    return Movement(annual_premium(scenario.PRIOR_YEAR), annual_premium(scenario.CURRENT_YEAR))


def product_movements() -> Dict[str, Movement]:
    """Movement per product across the union of both years' products."""
    prior, current = premium_by_product(scenario.PRIOR_YEAR), premium_by_product(scenario.CURRENT_YEAR)
    return {
        product: Movement(prior.get(product, 0.0), current.get(product, 0.0))
        for product in sorted(set(prior) | set(current))
    }


def quarter_movements() -> Dict[int, Movement]:
    """Corresponding-quarter movement: Q1 against Q1, not Q4 against Q1."""
    prior, current = premium_by_quarter(scenario.PRIOR_YEAR), premium_by_quarter(scenario.CURRENT_YEAR)
    return {
        quarter: Movement(prior.get(quarter, 0.0), current.get(quarter, 0.0))
        for quarter in scenario.QUARTERS
    }


def industry_movements(product: str) -> Dict[str, Movement]:
    prior = premium_by_industry(scenario.PRIOR_YEAR, product=product)
    current = premium_by_industry(scenario.CURRENT_YEAR, product=product)
    return {
        industry: Movement(prior.get(industry, 0.0), current.get(industry, 0.0))
        for industry in sorted(set(prior) | set(current))
    }


def contribution_points(movement: Movement, prior_total: float) -> float:
    """A slice's share of the headline change, in points of the prior total.

    Not clamped. A single slice can exceed the headline percentage when other
    slices move the other way, and hiding that is how an offset disappears.
    """
    if prior_total == 0:
        raise ZeroDivisionError("contribution against a zero prior total")
    return movement.absolute / prior_total * 100


def product_contributions() -> Dict[str, float]:
    prior_total = annual_premium(scenario.PRIOR_YEAR)
    return {
        product: contribution_points(movement, prior_total)
        for product, movement in product_movements().items()
    }


def largest_negative_contributor() -> Tuple[str, Movement]:
    movements = product_movements()
    name = min(movements, key=lambda product: movements[product].absolute)
    return name, movements[name]


def largest_positive_contributor() -> Tuple[str, Movement]:
    movements = product_movements()
    name = max(movements, key=lambda product: movements[product].absolute)
    return name, movements[name]


def widest_quarter_gap() -> Tuple[int, Movement]:
    movements = quarter_movements()
    quarter = min(movements, key=lambda q: movements[q].absolute)
    return quarter, movements[quarter]


def decomposition_residual(parts: Mapping[Any, Movement]) -> float:
    """Headline change minus the summed parts. Zero means the cut reconciles."""
    return headline_movement().absolute - sum(part.absolute for part in parts.values())


# --------------------------------------------------------------------------- #
# Whitespace
# --------------------------------------------------------------------------- #


def whitespace_products(year: int) -> Dict[str, float]:
    """Products with Marsh-book premium the subject does not write at all.

    Absence here is genuine: the subject has no row, which in this fixture means
    no participation rather than unknown participation. Production data cannot
    assume that, which is why the deferred whitespace phase needs a rule for it.
    """
    subject = premium_by_product(year)
    return {
        product: total
        for product, total in marsh_book_by_product(year).items()
        if subject.get(product, 0.0) == 0.0
    }


def carrier_share_of_market(year: int, product: str) -> float:
    market = marsh_book_by_product(year).get(product, 0.0)
    if market == 0:
        raise ZeroDivisionError("share of an empty market")
    return premium_by_product(year).get(product, 0.0) / market * 100


# --------------------------------------------------------------------------- #
# Survey
# --------------------------------------------------------------------------- #


def survey_attribute_scores(year: int, practice: str = "Property") -> Dict[str, float]:
    book = scenario.SURVEY_BOOK.get(practice, {}).get(year, {})
    return {attribute: score for attribute, (score, _n) in book.items()}


def survey_response_counts(year: int, practice: str = "Property") -> Dict[str, int]:
    book = scenario.SURVEY_BOOK.get(practice, {}).get(year, {})
    return {attribute: count for attribute, (_score, count) in book.items()}


def survey_practice_score(year: int, practice: str = "Property") -> float:
    """Mean score across the practice's attributes, weighted by responses.

    The real composite's weights are not published, so this is the observable
    response-weighted mean and nothing more. A claim that attributes "explain"
    the composite needs the real formula; this oracle deliberately does not
    supply one.
    """
    book = scenario.SURVEY_BOOK.get(practice, {}).get(year, {})
    total = sum(count for _score, count in book.values())
    if not total:
        raise ZeroDivisionError("no responses for this practice and year")
    return sum(score * count for score, count in book.values()) / total


def survey_attribute_movements(practice: str = "Property") -> Dict[str, float]:
    """Point change per attribute. Points, never percent — a score is not a rate."""
    prior = survey_attribute_scores(scenario.PRIOR_YEAR, practice)
    current = survey_attribute_scores(scenario.CURRENT_YEAR, practice)
    return {
        attribute: round(current.get(attribute, 0.0) - prior.get(attribute, 0.0), 2)
        for attribute in sorted(set(prior) & set(current))
    }


def reportable_practices(year: int) -> Tuple[str, ...]:
    """Practices with enough responses to report without identifying a respondent."""
    return tuple(
        practice
        for practice, by_year in sorted(scenario.SURVEY_BOOK.items())
        if sum(count for _s, count in by_year.get(year, {}).values()) >= scenario.MIN_RESPONSES
    )


def survey_only_practices() -> Tuple[str, ...]:
    """Surveyed practices with no premium book — a coverage limitation, not a zero."""
    return tuple(sorted(set(scenario.SURVEY_BOOK) - set(scenario.SUBJECT_BOOK)))


def premium_only_products() -> Tuple[str, ...]:
    """Products written but never surveyed. The other half of the same limitation."""
    market = set(marsh_book_by_product(scenario.CURRENT_YEAR))
    return tuple(sorted(market - set(scenario.SURVEY_BOOK)))
