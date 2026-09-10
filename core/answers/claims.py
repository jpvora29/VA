"""Compile factual sentences from evidence. Models can select, never rewrite them."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import re

from core.answers.facts import AnswerFact, FactPack, PERIOD_COLUMNS, format_value, label, stable_id


@dataclass(frozen=True)
class AnswerClaim:
    id: str
    text: str
    fact_ids: tuple[str, ...]
    kind: str = "observation"
    formula: str = ""
    priority: float = 0

    def as_dict(self) -> dict:
        return asdict(self)


def context(fact: AnswerFact, *, omit_period: bool = False) -> str:
    values = [v for k, v in fact.dimensions if not omit_period or k.lower() not in PERIOD_COLUMNS]
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
    dims = {key.lower(): value for key, value in fact.dimensions}
    return tuple((key, dims[key]) for key in ("year", "year_quarter", "yearquarter", "yearmonth", "quarter", "month", "date", "period") if key in dims)


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
            dims = tuple((k, v) for k, v in fact.dimensions if k.lower() not in PERIOD_COLUMNS)
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
    by_cut = defaultdict(dict)
    for fact in pack.facts:
        by_cut[(fact.dimensions, fact.lens, fact.source_id)][fact.metric.lower()] = fact
    for metrics in by_cut.values():
        for name, peer in metrics.items():
            if not name.startswith("peer_avg_"):
                continue
            subject = metrics.get(name.removeprefix("peer_avg_"))
            if subject is None or subject.unit != peer.unit:
                continue
            delta = subject.value - peer.value
            direction = "above" if delta > 0 else "below" if delta < 0 else "equal to"
            text = f"{label(subject.metric)} was {subject.rendered}, {direction} the peer average of {peer.rendered}"
            if delta:
                unit = "percentage_points" if subject.unit == "percent" else subject.unit
                text += f" by {format_value(abs(delta), unit)}"
            text += f" ({context(subject)})." if context(subject) else "."
            claims.append(AnswerClaim(stable_id("c_", [subject.id, peer.id, "peer_gap"]),
                text, (subject.id, peer.id), "peer_gap",
                f"{subject.value:g} - {peer.value:g} = {delta:g}", relevance(question, subject) + 8))
    return tuple(sorted(claims, key=lambda c: (-c.priority, c.id)))
