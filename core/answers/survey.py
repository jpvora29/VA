"""What the broker survey actually says, rather than a list of its scores.

The premium side of the ledger has a decomposition — a total, a leader, a
laggard, breadth, mix (:mod:`core.answers.insights`). The survey side had
nothing, so every score arrived as its own bare reading:

    - Score was 72 (Claims).
    - Score was 51 (Appetite).
    - Score was 64 (Underwriting).

Three true sentences and no finding. A reader has to sort them in their head to
learn the one thing the rows say, which is where this carrier is strong and where
it is weak. So the same two questions the premium side asks are asked here:

    where does it stand   the strongest and weakest returned cut, and the spread
    which way is it going  how many cuts improved, and which moved most

Both are order statistics and differences between two returned values. Nothing is
averaged across cuts: a survey score is already a mean over responses, and a mean
of means weighted by nothing is a number with no owner. "Of the N returned" is on
every sentence for the same reason it is on the premium ones — the evidence is
what came back, not the whole survey.

Pure: a `FactPack` in, claims out. No model, no database.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Sequence

from core.answers.claims import AnswerClaim, context, period_order, relevance
from core.answers.facts import (AnswerFact, FactPack, format_value, is_period_column,
                               stable_id)
from core.answers.insights import common_dimensions
from core.answers.language import count_of

# The columns a survey result is cut BY. Both spellings of each are live across
# warehouses — see the note in `core/registry/flows.yaml`.
SURVEY_CUT_COLUMNS = {
    "section", "sections", "attribute", "attributes",
    "surveypractice", "practice", "surveysegment", "segment",
}

# The units a survey answer is measured in.
SURVEY_UNITS = {"score"}

# A question that is about perception. The standing claim is then the direct
# answer and sits beside the premium headline rather than under the whole
# decomposition.
SURVEY_WORDS = re.compile(
    r"(?i)\bsurvey|\bscores?\b|\bnps\b|\bperception|\bsatisfaction|\bbroker|\bservice\b"
)
#: Where perception ranks. Unasked it sits above the premium decomposition's tail
#: (35-40) for the reason set out in `core.answers.benchmark`: a ten-claim answer
#: drawn from three books should say something from each of them before it says a
#: seventh thing about one. `trailing` is this book's own tail and ranks there.
ASKED = 46
UNASKED = 42
TAIL = 36


@dataclass(frozen=True)
class ScoreGroup:
    """One comparable set of survey scores: same measure, same cut, one period."""

    column: str
    facts: tuple[AnswerFact, ...]

    @property
    def ranked(self) -> tuple[AnswerFact, ...]:
        """Highest first; ties broken by name so the sentence is deterministic."""
        return tuple(sorted(self.facts, key=lambda f: (-f.value, cut_value(f, self.column))))

    @property
    def noun(self) -> str:
        return self.column.replace("_", " ").removeprefix("survey").strip().lower() or "cut"


def cut_value(fact: AnswerFact, column: str) -> str:
    """The name of the section/attribute/practice this fact is for."""
    return next((v for k, v in fact.dimensions if k.lower() == column), "")


def cut_column(fact: AnswerFact) -> str:
    """The survey cut column this fact is broken down by, or ""."""
    return next((k.lower() for k, _ in fact.dimensions if k.lower() in SURVEY_CUT_COLUMNS), "")


def score_groups(pack: FactPack) -> tuple[ScoreGroup, ...]:
    """Comparable score sets: one measure, one cut column, one period, 2+ values.

    Grouped on everything that has to match for two scores to be rankable against
    each other — the measure, its unit, the lens, the period and every other
    dimension — so a Section breakdown for 2025 never ranks against one for 2024,
    or against another country's.

    When the evidence carries several periods only the LATEST is ranked. Where a
    carrier stands is one statement about now; repeating it for each year on file
    says the same thing again in older numbers, and the movement claim already
    covers what changed.
    """
    grouped = defaultdict(list)
    for fact in pack.facts:
        column = cut_column(fact)
        if fact.unit not in SURVEY_UNITS or not column:
            continue
        base = tuple((k, v) for k, v in fact.dimensions
                     if not is_period_column(k) and k.lower() != column)
        grouped[(fact.metric, fact.unit, fact.lens, column, base)].append(fact)
    groups = []
    for (_, _, _, column, _), facts in grouped.items():
        latest = max((period_order(f) for f in facts), default=())
        current = [f for f in facts if period_order(f) == latest]
        named = {cut_value(f, column): f for f in current}
        if len(named) < 2 or len(named) != len(current):
            continue  # one value is not a ranking; a duplicate cut is ambiguous
        groups.append(ScoreGroup(column, tuple(current)))
    return tuple(groups)


def survey_insight(facts: Sequence[AnswerFact], kind: str, text: str, formula: str,
                   priority: float, focus: Sequence[str] = ()) -> AnswerClaim:
    """A claim over a set of score facts, scoped by what they all share."""
    ids = tuple(sorted(f.id for f in facts))
    scope = context(replace(facts[0], dimensions=common_dimensions(tuple(facts))))
    return AnswerClaim(stable_id("c_", [ids, kind]), text + (f" ({scope})." if scope else "."),
                       ids, kind, formula, priority, tuple(focus))


def standing(group: ScoreGroup, question: str) -> AnswerClaim:
    """Where this carrier is strong and where it is weak, and by how much."""
    ranked = group.ranked
    best, worst = ranked[0], ranked[-1]
    spread = best.value - worst.value
    text = (f"Its strongest returned {group.noun} is {cut_value(best, group.column)} at "
            f"{best.rendered} and its weakest is {cut_value(worst, group.column)} at "
            f"{worst.rendered}, a spread of {format_value(spread, 'score')} across the "
            f"{count_of(len(ranked), group.noun)} returned")
    formula = (f"max = {best.value:g}; min = {worst.value:g}; "
               f"spread = {best.value:g} - {worst.value:g} = {spread:g}")
    asked = bool(question and SURVEY_WORDS.search(question))
    return survey_insight(ranked, "survey_standing", text, formula,
                          (ASKED if asked else UNASKED) + relevance(question, best),
                          (best.id, worst.id))


def trailing(group: ScoreGroup, question: str) -> AnswerClaim | None:
    """How much of the book sits nearer the weak end than the strong one.

    Stated as a count against the midpoint of the two returned extremes, which is
    a position between two real values rather than an average of the set.
    """
    ranked = group.ranked
    if len(ranked) < 4:
        return None  # "3 of 3 sit below the midpoint" is arithmetic, not a finding
    best, worst = ranked[0], ranked[-1]
    midpoint = (best.value + worst.value) / 2
    below = [f for f in ranked if f.value < midpoint]
    if not below or len(below) == len(ranked):
        return None
    names = ", ".join(cut_value(f, group.column) for f in below[:3])
    more = f" and {len(below) - 3} more" if len(below) > 3 else ""
    text = (f"{len(below)} of the {count_of(len(ranked), group.noun)} returned score below the "
            f"midpoint of that spread ({format_value(midpoint, 'score')}): {names}{more}")
    formula = (f"midpoint = ({best.value:g} + {worst.value:g}) / 2 = {midpoint:g}; "
               f"count below = {len(below)} of {len(ranked)}")
    return survey_insight(ranked, "survey_trailing", text, formula,
                          TAIL + relevance(question, worst),
                          tuple(f.id for f in below))


@dataclass(frozen=True)
class ScoreMove:
    """One cut's movement between the two most recent returned periods."""

    name: str
    prior: AnswerFact
    current: AnswerFact

    @property
    def delta(self) -> float:
        return self.current.value - self.prior.value


def score_moves(pack: FactPack) -> tuple[tuple[str, tuple[ScoreMove, ...]], ...]:
    """Per cut column, the movements the evidence can actually pair up."""
    grouped = defaultdict(list)
    for fact in pack.facts:
        column = cut_column(fact)
        if fact.unit not in SURVEY_UNITS or not column or not all(period_order(fact)):
            continue
        base = tuple((k, v) for k, v in fact.dimensions
                     if not is_period_column(k) and k.lower() != column)
        grouped[(fact.metric, fact.unit, fact.lens, column, base)].append(fact)
    out = []
    for (_, _, _, column, _), facts in grouped.items():
        periods = sorted({period_order(f) for f in facts})
        if len(periods) < 2:
            continue
        before, after = periods[-2:]
        pairs: dict[str, dict] = defaultdict(dict)
        ambiguous = False
        for fact in facts:
            period = period_order(fact)
            if period not in {before, after}:
                continue
            name = cut_value(fact, column)
            if period in pairs[name]:
                ambiguous = True
            pairs[name][period] = fact
        moves = tuple(ScoreMove(name, values[before], values[after])
                      for name, values in sorted(pairs.items())
                      if before in values and after in values)
        if ambiguous or len(moves) < 2:
            continue
        out.append((column, moves))
    return tuple(out)


def movement(column: str, moves: Sequence[ScoreMove], question: str) -> AnswerClaim:
    """How broad the shift was, and which cut carried it."""
    noun = column.replace("_", " ").removeprefix("survey").strip().lower() or "cut"
    up = [m for m in moves if m.delta > 0]
    down = [m for m in moves if m.delta < 0]
    mover = max(moves, key=lambda m: (abs(m.delta), m.name))
    direction = "up" if mover.delta > 0 else "down" if mover.delta < 0 else "unchanged"
    text = (f"{len(up)} of the {count_of(len(moves), noun)} returned improved and "
            f"{len(down)} declined; {mover.name} moved most, {direction} from "
            f"{mover.prior.rendered} to {mover.current.rendered}")
    formula = (f"Count current - prior > 0: {len(up)}; < 0: {len(down)}; "
               f"largest absolute move = {mover.current.value:g} - {mover.prior.value:g} "
               f"= {mover.delta:g}")
    facts = [f for move in moves for f in (move.prior, move.current)]
    asked = bool(question and SURVEY_WORDS.search(question))
    return survey_insight(facts, "survey_movement", text, formula,
                          (ASKED if asked else UNASKED) - 1 + relevance(question, mover.current),
                          (mover.prior.id, mover.current.id))


def compile_survey_claims(pack: FactPack, question: str) -> list[AnswerClaim]:
    """Every survey finding this evidence supports, in no particular order."""
    claims = []
    for group in score_groups(pack):
        claims.append(standing(group, question))
        trail = trailing(group, question)
        if trail is not None:
            claims.append(trail)
    for column, moves in score_moves(pack):
        claims.append(movement(column, moves, question))
    return claims
