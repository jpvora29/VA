"""One sentence on the broker survey, for the page that carries the survey score tile.

The summary page reports the overall Carrier Survey score as a KPI tile
(:mod:`studio.template_fill.survey.kpi`), and a number on its own says nothing about
whether it is good, moving, or driven by anything. This composes the one line that reads
it — the same deterministic, every-claim-carries-its-figure contract as the premium
composers in :mod:`studio.template_fill.feedback`.

Generated on the SURVEY DATA BASIS only (Setup → "Premium + survey"), and only when the
survey book actually answers for the run's scope: a premium-basis deck is not asked about
the survey, and there is no premium figure that could stand in for a survey score.

The movement wording borrows the neutral threshold from
:mod:`studio.template_fill.survey.bands`, so the prose and the Carrier Survey table's own
band colours never disagree about whether a score moved.
"""
from __future__ import annotations

from typing import Optional, Tuple

from logger import get_logger

logger = get_logger(__name__)

# The Carrier Survey table paints |Δ| ≤ 0.2 as "no material change" (bands._BANDS' neutral
# row). Prose calling that a rise would contradict the colour on the very next page.
NEUTRAL_DELTA = 0.2

# Survey scores are reported to one decimal, the same as the tile's own ``x.x``.
def _score(value: float) -> str:
    return f"{value:.1f}"


def _movement(delta: Optional[float], prior_year: Optional[int]) -> str:
    """How the score moved since the last SURVEYED year, in the table's own terms."""
    if delta is None or prior_year is None:
        return ""
    since = f" on {int(prior_year)}"
    if abs(delta) <= NEUTRAL_DELTA:
        return f", broadly unchanged{since}"
    return f", {'up' if delta > 0 else 'down'} {abs(delta):.1f}{since}"


def _extremes(grid) -> str:
    """The strongest and weakest practice — only when they are genuinely apart.

    Naming a "strongest practice" across a spread of a tenth of a point is the survey-side
    version of naming a $145K move on a $208M book: arithmetically true, and not something
    an adviser would have said. The same neutral threshold the table's own band colours use
    (:data:`NEUTRAL_DELTA`) decides whether the spread is a finding or noise.
    """
    scored = [(s, grid.section_total(s)) for s in grid.sections]
    scored = [(s, v) for s, v in scored if v is not None]
    if len(scored) < 2:
        return ""
    best = max(scored, key=lambda row: row[1])
    worst = min(scored, key=lambda row: row[1])
    if best[0] == worst[0] or (best[1] - worst[1]) <= NEUTRAL_DELTA:
        return ""
    return (f", with {best[0]} its strongest practice at {_score(best[1])} and "
            f"{worst[0]} its weakest at {_score(worst[1])}")


def _subject(result) -> str:
    return str(getattr(result, "subject", "") or "The carrier")


def _one_country(result) -> Optional[str]:
    """The single country in scope, or ``None`` when the run spans several (or none).

    The section breakdown is loaded per country, so only a single-country run can name a
    strongest and weakest practice without silently reporting one market's grid as if it
    were the whole book's.
    """
    from studio.template_fill.bindings import selected_countries

    countries = tuple(selected_countries(result) or ())
    return str(countries[0]) if len(countries) == 1 else None


def _from_grid(result, country: str) -> Optional[str]:
    """The fuller sentence: score, movement since the last surveyed year, and the spread."""
    from studio.template_fill.survey import facts as survey_facts

    grid = survey_facts.load_grid(result, country)
    if grid is None or grid.overall is None:
        return None
    return (f"Brokers scored {_subject(result)} {_score(grid.overall)} in the "
            f"{int(grid.year)} carrier survey"
            f"{_movement(grid.overall_delta(), grid.prior_year)}"
            f"{_extremes(grid)}.")


def _from_score(result) -> Optional[str]:
    """The minimal sentence, for a run whose scope has no single country grid."""
    from studio.template_fill.bindings import selected_countries
    from studio.template_fill.survey import facts as survey_facts

    score = survey_facts.load_overall_score(result, selected_countries(result))
    if score is None:
        return None
    return f"Brokers scored {_subject(result)} {_score(score)} in the carrier survey."


def overall_point(result) -> Optional[str]:
    """The survey sentence for this run, or ``None`` when there is nothing to say.

    Never raises: the survey book is a second warehouse, and a page that cannot reach it
    ships without the line rather than failing the deck.
    """
    from studio.template_fill.survey import kpi

    if not kpi.on_survey_basis(result):
        return None
    try:
        country = _one_country(result)
        point = _from_grid(result, country) if country else None
        return point or _from_score(result)
    except Exception as exc:  # noqa: BLE001 — the survey line is never worth a broken deck
        logger.warning("survey.pointer: no survey line (%s)", exc)
        return None
