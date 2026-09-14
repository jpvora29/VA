"""The hand-checked business scenario the evaluation set is built on.

Numbers are declared here ONCE, at the grain the warehouse stores them
(product x industry x quarter), and every other figure in the suite —
annual totals, product contributions, quarterly gaps — is derived from
these rows by `oracles.py` using arithmetic written independently of
`core.analytics`. Nothing in this file imports application code, so a bug in
the library can never quietly redefine the expected answer.

The motivating question the plan is written around:

    "How was Zurich's performance in Singapore in 2025?"

The scenario is shaped so a good answer has something real to say:

  * the book declines year on year (1,700 -> 1,450, -250, -14.7%)
  * Property is the dominant negative contributor (-300)
  * Cyber GROWS and partly offsets it (+90) — an answer that reports only
    decline is wrong, not merely thin
  * the gap is concentrated in H2 (Q1 flat, Q4 -135), so the quarterly
    comparison carries real information
  * within Property the weakness concentrates in Manufacturing (-220)
  * Marine is Marsh-book premium Zurich does not write at all (whitespace)
  * the survey score falls, driven by Responsiveness, while Underwriting rises
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, Mapping, Tuple

CARRIER = "ZURICH GROUP"
COUNTRY = "Singapore"
CURRENT_YEAR = 2025
PRIOR_YEAR = 2024

#: Peers present in the same market. Named here only so the fixture can build a
#: Marsh book that is bigger than the subject's; answers must never name them.
PEERS = ("AIG", "CHUBB")

#: A second country and a second carrier, present purely so that a query which
#: leaks scope produces visibly wrong totals rather than a plausible one.
OTHER_COUNTRY = "Malaysia"

QUARTERS = (1, 2, 3, 4)

#: One representative billing month per quarter. The GPR flow derives quarters
#: from `Billing_Date`, so the fixture must carry real dates, not a Quarter
#: column the production schema does not have.
MONTH_OF_QUARTER: Mapping[int, Tuple[int, str]] = {
    1: (2, "February"),
    2: (5, "May"),
    3: (8, "August"),
    4: (11, "November"),
}


@dataclass(frozen=True)
class PremiumCell:
    """One premium figure at the grain the warehouse stores."""

    carrier: str
    country: str
    product: str
    industry: str
    year: int
    quarter: int
    premium: float


# --------------------------------------------------------------------------- #
# Subject book: ZURICH GROUP in Singapore.
# product -> year -> quarter -> industry -> premium
# --------------------------------------------------------------------------- #

SUBJECT_BOOK: Dict[str, Dict[int, Dict[int, Dict[str, float]]]] = {
    "Property": {
        2024: {
            1: {"Manufacturing": 150.0, "Financial Services": 100.0, "Retail": 50.0},
            2: {"Manufacturing": 150.0, "Financial Services": 100.0, "Retail": 50.0},
            3: {"Manufacturing": 150.0, "Financial Services": 100.0, "Retail": 50.0},
            4: {"Manufacturing": 150.0, "Financial Services": 100.0, "Retail": 50.0},
        },
        2025: {
            1: {"Manufacturing": 140.0, "Financial Services": 100.0, "Retail": 50.0},
            2: {"Manufacturing": 130.0, "Financial Services": 100.0, "Retail": 50.0},
            3: {"Manufacturing": 60.0, "Financial Services": 85.0, "Retail": 35.0},
            4: {"Manufacturing": 50.0, "Financial Services": 65.0, "Retail": 35.0},
        },
    },
    "Casualty": {
        2024: {
            1: {"Manufacturing": 60.0, "Financial Services": 40.0},
            2: {"Manufacturing": 60.0, "Financial Services": 40.0},
            3: {"Manufacturing": 60.0, "Financial Services": 40.0},
            4: {"Manufacturing": 60.0, "Financial Services": 40.0},
        },
        2025: {
            1: {"Manufacturing": 57.0, "Financial Services": 38.0},
            2: {"Manufacturing": 57.0, "Financial Services": 38.0},
            3: {"Manufacturing": 51.0, "Financial Services": 34.0},
            4: {"Manufacturing": 51.0, "Financial Services": 34.0},
        },
    },
    "Cyber": {
        2024: {
            1: {"Financial Services": 15.0, "Retail": 10.0},
            2: {"Financial Services": 15.0, "Retail": 10.0},
            3: {"Financial Services": 15.0, "Retail": 10.0},
            4: {"Financial Services": 15.0, "Retail": 10.0},
        },
        2025: {
            1: {"Financial Services": 24.0, "Retail": 16.0},
            2: {"Financial Services": 27.0, "Retail": 18.0},
            3: {"Financial Services": 30.0, "Retail": 20.0},
            4: {"Financial Services": 33.0, "Retail": 22.0},
        },
    },
}

# --------------------------------------------------------------------------- #
# Peer books, at a coarser grain (one industry per product). Their only jobs are
# to make the Marsh book larger than the subject's and to create a product the
# market writes and the subject does not.
# carrier -> product -> year -> quarter -> premium
# --------------------------------------------------------------------------- #

PEER_BOOKS: Dict[str, Dict[str, Dict[int, Dict[int, float]]]] = {
    "AIG": {
        "Property": {
            2024: {1: 200.0, 2: 200.0, 3: 200.0, 4: 200.0},
            2025: {1: 210.0, 2: 215.0, 3: 220.0, 4: 225.0},
        },
        "Marine": {
            2024: {1: 120.0, 2: 120.0, 3: 120.0, 4: 120.0},
            2025: {1: 130.0, 2: 130.0, 3: 135.0, 4: 135.0},
        },
    },
    "CHUBB": {
        "Casualty": {
            2024: {1: 150.0, 2: 150.0, 3: 150.0, 4: 150.0},
            2025: {1: 155.0, 2: 155.0, 3: 160.0, 4: 160.0},
        },
        "Marine": {
            2024: {1: 90.0, 2: 90.0, 3: 90.0, 4: 90.0},
            2025: {1: 95.0, 2: 95.0, 3: 100.0, 4: 100.0},
        },
    },
}

#: The industry every peer row is booked under. Peers exist for the denominator,
#: not for an industry story, so one class keeps the fixture small and the
#: Marsh-book arithmetic obvious.
PEER_INDUSTRY = "Financial Services"

#: Out-of-scope volume. Any query that loses the country filter picks this up and
#: the resulting total is nowhere near a correct one.
OTHER_COUNTRY_PREMIUM = 9_000.0


def subject_cells() -> Iterator[PremiumCell]:
    """Every subject premium row, at product x year x quarter x industry."""
    for product, by_year in SUBJECT_BOOK.items():
        for year, by_quarter in by_year.items():
            for quarter, by_industry in by_quarter.items():
                for industry, premium in by_industry.items():
                    yield PremiumCell(
                        CARRIER, COUNTRY, product, industry, year, quarter, premium
                    )


def peer_cells() -> Iterator[PremiumCell]:
    """Every peer premium row, at product x year x quarter."""
    for carrier, by_product in PEER_BOOKS.items():
        for product, by_year in by_product.items():
            for year, by_quarter in by_year.items():
                for quarter, premium in by_quarter.items():
                    yield PremiumCell(
                        carrier, COUNTRY, product, PEER_INDUSTRY, year, quarter, premium
                    )


def out_of_scope_cells() -> Iterator[PremiumCell]:
    """Subject volume in another country — the scope-leak tripwire."""
    for year in (PRIOR_YEAR, CURRENT_YEAR):
        yield PremiumCell(
            CARRIER, OTHER_COUNTRY, "Property", "Manufacturing", year, 1,
            OTHER_COUNTRY_PREMIUM,
        )


def all_cells() -> Iterator[PremiumCell]:
    yield from subject_cells()
    yield from peer_cells()
    yield from out_of_scope_cells()


# --------------------------------------------------------------------------- #
# Survey scenario.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SurveyCell:
    """One survey response row."""

    carrier: str
    country: str
    practice: str
    section: str
    attribute: str
    year: int
    score: float
    nps: float
    response_id: str


#: practice -> year -> attribute -> (score, response count)
#: Responsiveness falls hard, Underwriting rises — so an answer that reports the
#: composite alone loses the only actionable half of the survey story.
SURVEY_BOOK: Dict[str, Dict[int, Dict[str, Tuple[float, int]]]] = {
    "Property": {
        2024: {
            "Responsiveness": (7.0, 8),
            "Claims handling": (6.5, 8),
            "Underwriting expertise": (7.2, 8),
        },
        2025: {
            "Responsiveness": (6.0, 8),
            "Claims handling": (6.4, 8),
            "Underwriting expertise": (7.3, 8),
        },
    },
    # Thin practice: fewer than five responses, so the confidentiality rule must
    # withhold it rather than report a two-person average as a finding.
    "Cyber": {
        2024: {"Responsiveness": (8.0, 2)},
        2025: {"Responsiveness": (5.0, 2)},
    },
}

SECTION_OF_ATTRIBUTE: Mapping[str, str] = {
    "Responsiveness": "Service",
    "Claims handling": "Service",
    "Underwriting expertise": "Technical",
}

#: NPS moves with the composite but is a different measure; it must never be
#: averaged together with Score or summed like premium.
SURVEY_NPS: Mapping[int, float] = {2024: 30.0, 2025: 10.0}

#: A practice the survey covers but the premium book does not, and vice versa
#: ("Marine" is written but never surveyed). Both directions must be reported as
#: a coverage limitation rather than silently dropped or joined.
MIN_RESPONSES = 5


def survey_cells() -> Iterator[SurveyCell]:
    """One row per response, so response counts are real rather than asserted."""
    for practice, by_year in SURVEY_BOOK.items():
        for year, by_attribute in by_year.items():
            for attribute, (score, responses) in by_attribute.items():
                for index in range(responses):
                    yield SurveyCell(
                        carrier=CARRIER,
                        country=COUNTRY,
                        practice=practice,
                        section=SECTION_OF_ATTRIBUTE.get(attribute, "Service"),
                        attribute=attribute,
                        year=year,
                        score=score,
                        nps=SURVEY_NPS[year],
                        response_id=f"{practice}-{year}-{attribute}-{index}",
                    )
