"""Compile factual sentences from evidence. Models can select, never rewrite them."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import re

from core.answers.facts import (AnswerFact, FactPack, format_value, is_period_column,
                               label, period_rank, stable_id)


@dataclass(frozen=True)
class AnswerClaim:
    id: str
    text: str
    fact_ids: tuple[str, ...]
    kind: str = "observation"
    formula: str = ""
    priority: float = 0
    focus_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


def context(fact: AnswerFact, *, omit_period: bool = False) -> str:
    values = [v for k, v in fact.dimensions if not omit_period or not is_period_column(k)]
    return " · ".join(dict.fromkeys(values))


def relevance(question: str, fact: AnswerFact) -> float:
    words = set(re.findall(r"[a-z]+", question.lower()))
    names = set(re.findall(r"[a-z]+", fact.metric.lower()))
    score = len(words & names) * 3
    for _, value in fact.dimensions:
        if value.lower() in question.lower():
            score += 1
    return score


def observation(fact: AnswerFact, question: str) -> AnswerClaim:
    scope = context(fact)
    text = f"{label(fact.metric)} was {fact.rendered}"
    if scope:
        text += f" ({scope})"
    return AnswerClaim(stable_id("c_", [fact.id, "observation"]), text + ".", (fact.id,),
                       formula=fact.formula, priority=relevance(question, fact))


def period_key(fact: AnswerFact) -> tuple:
    """This fact's period dimensions, coarse to fine — its position in time.

    Read by predicate rather than from a fixed list of names, so a flow that
    spells its year column `Survey_Year` has a period at all. Ordering is shared
    (`facts.period_rank`) so two facts always compare on the same axes.
    """
    periods = [(key.lower(), value) for key, value in fact.dimensions if is_period_column(key)]
    return tuple(sorted(periods, key=lambda pair: period_rank(pair[0])))


def period_order(fact: AnswerFact) -> tuple:
    return tuple(tuple(int(n) for n in re.findall(r"\d+", value)) for _, value in period_key(fact))


def change_claim(prior: AnswerFact, current: AnswerFact, question: str) -> AnswerClaim:
    delta = current.value - prior.value
    verb = "increased" if delta > 0 else "decreased" if delta < 0 else "was unchanged"
    when = " · ".join(value for _, value in period_key(current))
    before = " · ".join(value for _, value in period_key(prior))
    scope = context(current, omit_period=True)
    text = f"{label(current.metric)} {verb} from {prior.rendered} ({before}) to {current.rendered} ({when})"
    formula = f"{current.value:g} - {prior.value:g} = {delta:g}"
    if delta and current.unit == "currency" and prior.value > 0:
        pct = delta / prior.value * 100
        text += f", a {format_value(abs(pct), 'percent')} {'increase' if delta > 0 else 'decrease'}"
        formula += f"; ({current.value:g} - {prior.value:g}) / {prior.value:g} × 100 = {pct:g}%"
    elif delta and current.unit == "percent":
        text += f", a change of {format_value(delta, 'percentage_points')}"
    elif prior.value == 0 and delta and current.unit == "currency":
        text += "; percentage change is undefined because the prior value is zero"
    if scope:
        text += f" ({scope})"
    boost = 8 if re.search(r"change|grow|growth|trend|year|increas|declin", question, re.I) else 2
    return AnswerClaim(stable_id("c_", [prior.id, current.id, "change"]), text + ".",
                       (prior.id, current.id), "change", formula, relevance(question, current) + boost)


def compile_claims(pack: FactPack, question: str) -> tuple[AnswerClaim, ...]:
    claims = [observation(fact, question) for fact in pack.facts]
    groups = defaultdict(list)
    for fact in pack.facts:
        if period_key(fact):
            dims = tuple((k, v) for k, v in fact.dimensions if not is_period_column(k))
            groups[(fact.metric, fact.unit, dims, fact.lens)].append(fact)
    for facts in groups.values():
        # Ambiguous duplicate periods are not a valid time series.
        unique = {period_key(f): f for f in facts}
        if len(unique) != len(facts) or len(facts) < 2:
            continue
        if any(not all(period_order(f)) for f in facts):
            continue
        ordered = sorted(facts, key=period_order)
        claims.append(change_claim(ordered[-2], ordered[-1], question))
    # Benchmarks pair across result sets, so they are matched on what makes two
    # figures comparable rather than on arriving together — see
    # `core.answers.benchmark`.
    from core.answers.benchmark import benchmark_claims
    claims.extend(benchmark_claims(pack.facts, question))
    return tuple(sorted(claims, key=lambda c: (-c.priority, c.id)))
