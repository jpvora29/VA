"""What a survey movement can and cannot be said to show.

The premium side of a performance answer is arithmetic over one additive measure.
The survey side is not, and every one of its failure modes comes from treating it
as though it were:

  * a score is an average on a fixed scale, so it moves in POINTS. "Down 14%" on
    a 7.0 that became 6.0 is a number with no meaning — it is down 1.0 point;
  * a composite is a weighted blend whose weights this system does not publish,
    so attributing its movement to the attributes underneath is arithmetic
    nobody can check. Observed attribute movements can be described; a
    reconciled contribution cannot be claimed;
  * an average over four people is not a finding, it is a disclosure risk. The
    ">4 responses" rule is the same one the Studio deck applies;
  * two years of survey data may not be asking the same questions of the same
    population. A comparison across a changed questionnaire is not wrong so much
    as meaningless, and the change has to be visible;
  * the survey reaches only to a year. A quarterly survey figure does not exist,
    however convenient one would be next to a quarterly premium series.

Pure functions over dataclasses: no database, no model. The rules are the point,
and a rule that cannot be unit-tested with a planted violation is not a rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from core.analysis.alignment import YEAR, comparable_periods, shared_grain

#: A practice or attribute needs MORE than this many responses to be reported.
#: Mirrors `studio.template_fill.survey.facts.MIN_RESPONSES` — one rule, applied
#: the same way in the deck and in chat, because it is a confidentiality
#: commitment rather than a display preference.
MIN_RESPONSES = 4

#: A score moves in points. Named so the unit cannot be quietly changed to a
#: percentage by whoever writes the next formatter.
POINTS = "points"

#: How far the response base may shift before a comparison is worth qualifying.
#: A survey whose respondent count halves is measuring a different room.
POPULATION_SHIFT = 0.5


@dataclass(frozen=True)
class AttributeMovement:
    """One attribute's movement between two comparable survey years."""

    attribute: str
    prior: float
    current: float
    prior_responses: int = 0
    current_responses: int = 0

    @property
    def delta(self) -> float:
        """The movement, in points. There is deliberately no percent property."""
        return round(self.current - self.prior, 2)

    @property
    def reportable(self) -> bool:
        """Whether both years clear the response threshold.

        BOTH, not either: a movement is a statement about two numbers, and a
        thin base in the prior year makes the movement as unreliable as a thin
        base in the current one.
        """
        return (
            self.prior_responses > MIN_RESPONSES
            and self.current_responses > MIN_RESPONSES
        )

    @property
    def rendered(self) -> str:
        return f"{self.delta:+.2f} {POINTS}".replace("+0.00", "0.00")


@dataclass(frozen=True)
class SurveyComparison:
    """A survey movement and everything that qualifies it."""

    prior_year: Optional[int] = None
    current_year: Optional[int] = None
    movements: Tuple[AttributeMovement, ...] = ()
    limitations: Tuple[str, ...] = ()

    @property
    def is_comparable(self) -> bool:
        return self.prior_year is not None and self.current_year is not None

    @property
    def reportable(self) -> Tuple[AttributeMovement, ...]:
        return tuple(m for m in self.movements if m.reportable)

    @property
    def withheld(self) -> Tuple[AttributeMovement, ...]:
        return tuple(m for m in self.movements if not m.reportable)

    def largest(self) -> Optional[AttributeMovement]:
        """The biggest reportable movement in either direction, or None."""
        reportable = self.reportable
        if not reportable:
            return None
        return max(reportable, key=lambda m: abs(m.delta))


# --------------------------------------------------------------------------- #
# Comparability
# --------------------------------------------------------------------------- #


def comparable_survey_years(
    available: Sequence[int], *, requested: Sequence[int] = ()
) -> Tuple[Optional[int], Optional[int]]:
    """The two survey years to compare, or (None, None) when there is no pair.

    Returning a pair of Nones rather than a single year is the point: a lone
    survey year is a snapshot, and presenting it as a movement is the failure
    this function exists to make impossible.
    """
    years = sorted({int(y) for y in available})
    if requested:
        wanted = comparable_periods(sorted({int(y) for y in requested}), years)
        return (wanted[-1], wanted[-2]) if len(wanted) >= 2 else (None, None)
    return (years[-1], years[-2]) if len(years) >= 2 else (None, None)


def population_limitation(prior_responses: int, current_responses: int) -> str:
    """A sentence when the respondent base moved enough to qualify the comparison."""
    if not prior_responses or not current_responses:
        return ""
    smaller, larger = sorted((prior_responses, current_responses))
    if smaller / larger >= POPULATION_SHIFT:
        return ""
    return (
        f"The respondent base changed materially between the two years "
        f"({prior_responses} responses against {current_responses}), so the "
        f"comparison reflects a different population as well as a different score."
    )


def questionnaire_limitation(
    prior_attributes: Sequence[str], current_attributes: Sequence[str]
) -> str:
    """A sentence when the two years did not ask the same questions.

    An attribute present in only one year is not a score that moved to or from
    zero — it is a question that was not asked, and averaging across a changed
    questionnaire compares two different instruments.
    """
    prior, current = set(prior_attributes), set(current_attributes)
    added, dropped = sorted(current - prior), sorted(prior - current)
    if not (added or dropped):
        return ""
    parts = []
    if added:
        parts.append(f"{', '.join(added)} appear only in the later year")
    if dropped:
        parts.append(f"{', '.join(dropped)} only in the earlier one")
    return (
        "The questionnaire changed between the two years — "
        + "; ".join(parts)
        + " — so only the attributes common to both are compared."
    )


def composite_attribution_limitation(weights: Optional[Mapping[str, float]]) -> str:
    """The sentence that stops attribute movements being sold as an attribution.

    With published weights a composite's movement can be decomposed. Without
    them the attributes can only be DESCRIBED, and saying "responsiveness drove
    the score down" is an arithmetic claim nobody can check. This system does not
    publish the weights, so this normally returns its sentence.
    """
    if weights:
        return ""
    return (
        "The composite score's weighting is not published, so attribute movements "
        "are reported as observations and not as contributions to it."
    )


# --------------------------------------------------------------------------- #
# Building the comparison
# --------------------------------------------------------------------------- #


def build_comparison(
    *,
    scores_by_year: Mapping[int, Mapping[str, float]],
    responses_by_year: Optional[Mapping[int, Mapping[str, int]]] = None,
    requested_years: Sequence[int] = (),
    weights: Optional[Mapping[str, float]] = None,
) -> SurveyComparison:
    """Assemble a survey comparison and everything that qualifies it.

    Reads as the list of questions that have to be answered before a survey
    movement may be stated: are there two comparable years, did they ask the same
    questions of a similar population, is each attribute answered by enough
    people, and may the composite be attributed at all.
    """
    current, prior = comparable_survey_years(
        list(scores_by_year), requested=requested_years
    )
    if current is None or prior is None:
        return SurveyComparison(
            limitations=(
                "Only one survey year is available for this scope, so no "
                "perception movement can be stated.",
            )
        )

    prior_scores = dict(scores_by_year.get(prior) or {})
    current_scores = dict(scores_by_year.get(current) or {})
    responses = responses_by_year or {}
    prior_counts = dict(responses.get(prior) or {})
    current_counts = dict(responses.get(current) or {})

    movements = tuple(
        AttributeMovement(
            attribute=attribute,
            prior=float(prior_scores[attribute]),
            current=float(current_scores[attribute]),
            prior_responses=int(prior_counts.get(attribute, 0)),
            current_responses=int(current_counts.get(attribute, 0)),
        )
        # Only attributes BOTH years carry. The ones that differ are reported as
        # a questionnaire change instead, never as a movement from nothing.
        for attribute in sorted(set(prior_scores) & set(current_scores))
    )

    limitations = tuple(
        sentence
        for sentence in (
            questionnaire_limitation(list(prior_scores), list(current_scores)),
            population_limitation(sum(prior_counts.values()), sum(current_counts.values())),
            composite_attribution_limitation(weights),
            _withheld_limitation(movements),
        )
        if sentence
    )
    return SurveyComparison(prior, current, movements, limitations)


def _withheld_limitation(movements: Sequence[AttributeMovement]) -> str:
    withheld = [m.attribute for m in movements if not m.reportable]
    if not withheld:
        return ""
    return (
        f"{', '.join(sorted(withheld))} had {MIN_RESPONSES} or fewer responses in "
        f"one of the two years and is not reported."
    )


# --------------------------------------------------------------------------- #
# Reading premium and survey together
# --------------------------------------------------------------------------- #

AGREE = "agree"
DIVERGE = "diverge"
FLAT = "flat"


@dataclass(frozen=True)
class CrossReading:
    """What the two datasets say when read side by side, and nothing more."""

    relation: str
    text: str
    limitations: Tuple[str, ...] = ()


def read_together(
    *,
    premium_change: float,
    survey_change: Optional[float],
    grain: str = "",
) -> CrossReading:
    """Describe agreement or tension between the two datasets, asserting no cause.

    The one thing this must never produce is a sentence in which one dataset
    explains the other. Premium and perception moving together is a fact about
    two numbers; that either caused the other is a claim neither dataset can
    carry, and the wording here is built so there is nowhere for that claim to
    enter.
    """
    limitations = []
    if grain and grain != YEAR:
        limitations.append(
            "Survey data is only available annually, so the two are compared at "
            "year level even though premium is available more finely."
        )
    if survey_change is None:
        return CrossReading(
            FLAT,
            "No comparable perception movement is available alongside the premium movement.",
            tuple(limitations),
        )

    same_direction = (premium_change > 0) == (survey_change > 0)
    if premium_change == 0 or survey_change == 0:
        relation, phrase = FLAT, "one of the two measures did not move"
    elif same_direction:
        relation, phrase = AGREE, "both moved in the same direction"
    else:
        relation, phrase = DIVERGE, "they moved in opposite directions"

    return CrossReading(
        relation,
        (
            f"Premium moved {premium_change:+,.1f} and the survey score "
            f"{survey_change:+.2f} {POINTS} over the same scope; {phrase}. "
            "This is an observation about both measures, not evidence that "
            "either explains the other."
        ),
        tuple(limitations),
    )


def survey_grain_limitation(premium_flow: str = "gpr", survey_flow: str = "survey") -> str:
    """A sentence when premium is finer-grained than the survey can match.

    Read off the registry rather than asserted, so a warehouse that did start
    publishing quarterly survey data would stop emitting this by itself.
    """
    if shared_grain(premium_flow, survey_flow) == YEAR:
        return (
            "Survey results are annual, so no quarterly perception figure exists "
            "to place beside the quarterly premium comparison."
        )
    return ""
