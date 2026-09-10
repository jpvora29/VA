"""Present verified statements without repeating the shared filter pills.

Only known template fragments are replaced. Values and formulas stay attached
to the original claim, and this same transformation is replayed by verification.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

from core.answers.claims import AnswerClaim, context, period_key
from core.answers.facts import AnswerFact, PERIOD_COLUMNS, label
from core.answers.insights import PRODUCT_COLUMNS, common_dimensions
from core.answers.scope import DisplayScope, matching_scope_dimensions


CARRIER_COLUMNS = {"carrier", "carrier_group", "carrier_name", "insurer", "insurer_name"}
HIDDEN_COLUMNS = {"grain", "through"}


@dataclass(frozen=True)
class NarrativeContext:
    shared: frozenset[tuple[str, str]]
    lead_periods: frozenset[tuple]
    legacy: bool = False


def dimension_key(key: str) -> str:
    key = key.lower()
    if key in CARRIER_COLUMNS:
        return "carrier"
    if key in PRODUCT_COLUMNS:
        return "product"
    return key


def dimensions(fact: AnswerFact) -> dict[str, str]:
    return {dimension_key(k): v for k, v in fact.dimensions}


def display_entity(value: str) -> str:
    return " ".join(word.capitalize() if word.isupper() and len(word) > 3 else word
                    for word in value.split())


def claim_dimensions(claim: AnswerClaim, facts: tuple[AnswerFact, ...]) -> AnswerFact:
    if claim.kind in {"observation", "peer_gap"}:
        return facts[0]
    if claim.kind == "change":
        return facts[-1]
    return replace(facts[0], dimensions=common_dimensions(facts))


def name_subject(text: str, subject: AnswerFact, narration: NarrativeContext, lead: bool) -> tuple[str, set[str]]:
    metric, consumed = label(subject.metric), set()
    if not text.startswith(metric):
        return text, consumed
    dims = dimensions(subject)
    noun = metric.replace("Premium", "premium")
    if not narration.legacy or not lead:
        noun = noun.removeprefix("Marsh-placed ")
    if not narration.legacy and subject.metric.lower() in {"marsh_premium", "marsh_placed_premium"}:
        noun = re.sub(r"(?i)^marsh(?: placed)?\s+", "", noun)
    carrier, product = dims.get("carrier"), dims.get("product")
    qualifiers = []
    owns_metric = not subject.metric.lower().startswith(("market_", "peer_avg_"))
    if carrier and owns_metric and (lead or ("carrier", carrier) not in narration.shared):
        qualifiers.append(display_entity(carrier) + "'s")
        consumed.add("carrier")
    if product and (lead or ("product", product) not in narration.shared):
        qualifiers.append(product)
        consumed.add("product")
    replacement = " ".join([*qualifiers, noun])
    return replacement[:1].upper() + replacement[1:] + text[len(metric):], consumed


def distinguishing_context(dims: dict, kind: str, consumed: set, narration: NarrativeContext) -> list[str]:
    hidden = HIDDEN_COLUMNS | consumed
    if kind != "observation":
        hidden = hidden | PERIOD_COLUMNS
    return list(dict.fromkeys(v for k, v in dims.items() if (k, v) not in narration.shared and k not in hidden))


def compact_claim(claim: AnswerClaim, inputs: tuple[AnswerFact, ...],
                  narration: NarrativeContext, *, lead: bool) -> AnswerClaim:
    subject = claim_dimensions(claim, inputs)
    dims, text = dimensions(subject), claim.text
    old_scope = context(subject, omit_period=claim.kind not in {"observation", "peer_gap"})
    suffix = f" ({old_scope})."
    if old_scope and text.endswith(suffix):
        text = text.removesuffix(suffix) + "."
    text, consumed = name_subject(text, subject, narration, lead)
    if not lead and claim.kind == "change" and {period_key(f) for f in inputs} == narration.lead_periods:
        for fact in inputs:
            text = text.replace(" (" + " · ".join(v for _, v in period_key(fact)) + ")", "")
    remaining = distinguishing_context(dims, claim.kind, consumed, narration)
    if remaining:
        text = text.removesuffix(".") + f" ({' · '.join(remaining)})."
    through = dims.get("through")
    if through and (lead or ("through", through) not in narration.shared):
        text = text.removesuffix(".") + f"; through {through} in both years."
    return replace(claim, text=text)


def compact_claims(claims: tuple[AnswerClaim, ...], facts: tuple[AnswerFact, ...],
                   scope: DisplayScope = (), *, legacy: bool = False) -> tuple[AnswerClaim, ...]:
    if not claims:
        return ()
    by_id = {f.id: f for f in facts}
    shared = set(dimensions(facts[0]).items())
    for fact in facts[1:]:
        shared.intersection_update(dimensions(fact).items())
    if not legacy:
        shared.update(matching_scope_dimensions([dimensions(f) for f in facts], scope))
    lead_facts = tuple(by_id[i] for i in claims[0].fact_ids)
    periods = {period_key(f) for f in lead_facts} if claims[0].kind in {"change", "portfolio_change"} else set()
    narration = NarrativeContext(frozenset(shared), frozenset(periods), legacy)
    return tuple(compact_claim(claim, tuple(by_id[i] for i in claim.fact_ids), narration, lead=index == 0)
                 for index, claim in enumerate(claims))
