"""Present verified statements without repeating the shared filter pills.

Only known template fragments are replaced. Values and formulas stay attached
to the original claim, and this same transformation is replayed by verification.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

from core.answers.claims import AnswerClaim, context, period_key
from core.answers.facts import AnswerFact, is_period_column, label
from core.answers.insights import PRODUCT_COLUMNS, common_dimensions
from core.answers.scope import DisplayScope, matching_scope_dimensions


CARRIER_COLUMNS = {"carrier", "carrier_group", "carrier_name", "insurer", "insurer_name"}
HIDDEN_COLUMNS = {"grain", "through"}

# Claim kinds whose SENTENCE does not carry the period itself, so their scope
# suffix has to. A growth sentence already reads "from $300 (2024) to $390
# (2025)"; a standing sentence says only where a carrier sits, and stripping the
# period from it leaves a finding with no date on it. Read in both places that
# decide what a suffix holds, so the suffix a claim was BUILT with is the one
# this recognises and removes — a mismatch leaves both on the page.
PERIOD_IN_SUFFIX = {"observation", "peer_gap", "survey_standing", "survey_trailing"}


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
    drop_period = kind not in PERIOD_IN_SUFFIX
    return list(dict.fromkeys(v for k, v in dims.items()
                              if (k, v) not in narration.shared and k not in hidden
                              and not (drop_period and is_period_column(k))))


def shared_dimensions(facts: tuple[AnswerFact, ...]) -> set[tuple[str, str]]:
    """What every fact agrees on — the context the reader already has.

    A BENCHMARK is excluded from the vote. A peer average is deliberately not
    filtered to one carrier, so counting its dimensions makes the carrier "not
    shared" and every other sentence in the answer starts spelling it out —
    "CHUBB · Canada" six times over, in an answer that is about Chubb throughout.
    Its missing carrier is a property of the measure, not of the turn's scope.
    """
    from core.answers.benchmark import benchmark_measure

    subjects = [f for f in facts if not benchmark_measure(f.metric)] or list(facts)
    shared = set(dimensions(subjects[0]).items())
    for fact in subjects[1:]:
        shared.intersection_update(dimensions(fact).items())
    return shared


def compact_claim(claim: AnswerClaim, inputs: tuple[AnswerFact, ...],
                  narration: NarrativeContext, *, lead: bool) -> AnswerClaim:
    subject = claim_dimensions(claim, inputs)
    dims, text = dimensions(subject), claim.text
    old_scope = context(subject, omit_period=claim.kind not in PERIOD_IN_SUFFIX)
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
    shared = shared_dimensions(facts)
    if not legacy:
        shared.update(matching_scope_dimensions([dimensions(f) for f in facts], scope))
    lead_facts = tuple(by_id[i] for i in claims[0].fact_ids)
    periods = {period_key(f) for f in lead_facts} if claims[0].kind in {"change", "portfolio_change"} else set()
    narration = NarrativeContext(frozenset(shared), frozenset(periods), legacy)
    return tuple(compact_claim(claim, tuple(by_id[i] for i in claim.fact_ids), narration, lead=index == 0)
                 for index, claim in enumerate(claims))
