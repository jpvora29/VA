"""A readable answer pipeline with two small, optional model adapters.

Two separable jobs, and the pipeline runs without either:

    select    which of the verified claims answer this question
    narrate   how those claims read as an answer a person wants to read

Neither model may supply a value, an entity or a calculation. Selection returns
claim IDs; narration returns prose that is re-checked against the same claims
(:mod:`core.answers.narration`) and discarded whole if a figure in it is not
supported. `ledger` is the deterministic render — the answer when there is no
narrator, the fallback when there is, and the text a stored record verifies
against — so an offline pipeline produces exactly what it always did.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from core.answers.claims import AnswerClaim, compile_claims
from core.answers.facts import AnswerFact, FactPack, build_fact_pack
from core.answers.insights import compile_answer_claims
from core.answers.narrative import compact_claims
from core.answers.narration import (Narration, Writer, build_brief, narrate,
                                    supported_numbers, unsupported_in)
from core.answers.comparison_inputs import build_answer_fact_pack
from core.answers.scope import DisplayScope


ANALYST_CLAIM_LIMIT = 10
ANSWER_VERSION = 4

#: Versions whose `content` is the deterministic ledger verbatim. Version 4 may
#: also carry narrated prose, which verifies by figure support instead.
LEDGER_VERSIONS = {1, 2, 3}


@dataclass(frozen=True)
class AnswerRequest:
    question: str
    evidence: tuple[Mapping, ...]
    shape: str = "analyst"
    presentation: str = "prose"
    scope: DisplayScope = ()
    #: The period the turn chose because the question named none. The reader has
    #: to be told: a figure for one year, presented as though it were the whole
    #: book, is the same failure as an all-years total presented as this year's.
    defaulted_period: str = ""


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    facts: tuple[AnswerFact, ...] = ()
    claims: tuple[AnswerClaim, ...] = ()
    selection_rejected: bool = False
    limitation: str = ""
    scope: DisplayScope = ()
    ledger: str = ""
    narrated: bool = False
    dropped_figures: tuple[str, ...] = ()
    narration_rejected: str = ""

    def as_dict(self) -> dict:
        return {"version": ANSWER_VERSION, "content": self.text, "facts": [f.as_dict() for f in self.facts],
                "claims": [c.as_dict() for c in self.claims], "limitation": self.limitation,
                "selection_rejected": self.selection_rejected, "scope": self.scope,
                "ledger": self.ledger or self.text, "narrated": self.narrated}


ClaimSelector = Callable[[tuple[AnswerClaim, ...]], Sequence[str]]


def distinct_claims(candidates: Sequence[AnswerClaim], limit: int,
                    facts: Sequence[AnswerFact] = ()) -> tuple[AnswerClaim, ...]:
    identities = {f.id: (f.metric, f.unit, f.dimensions, f.value) for f in facts}
    chosen, covered, detailed, seen = [], set(), set(), set()
    for claim in candidates:
        inputs = frozenset(identities.get(i, i) for i in claim.fact_ids)
        identity = (claim.kind, inputs)
        if identity in seen:
            continue
        if claim.kind == "observation" and inputs <= covered:
            continue
        if claim.kind == "change" and inputs <= detailed:
            continue
        chosen.append(claim)
        seen.add(identity)
        covered.update(inputs)
        focus = claim.focus_ids or (claim.fact_ids if claim.kind in {"change", "peer_gap"} else ())
        detailed.update(identities.get(i, i) for i in focus)
        if len(chosen) == limit:
            break
    return tuple(chosen)


def select_claims(candidates: tuple[AnswerClaim, ...], limit: int,
                  select: ClaimSelector | None, facts: Sequence[AnswerFact] = ()) -> tuple[tuple[AnswerClaim, ...], bool]:
    if select is None:
        return distinct_claims(candidates, limit, facts), False
    try:
        identifiers = list(select(candidates))
    except Exception:
        return distinct_claims(candidates, limit, facts), True
    allowed = {c.id: c for c in candidates}
    if not identifiers or any(not isinstance(i, str) or i not in allowed for i in identifiers):
        return distinct_claims(candidates, limit, facts), True
    # Always retain the direct answer and fill useful evidence the selector left
    # out. A small model choosing one ID must not collapse a rich analysis.
    ranked = candidates[:1] + tuple(allowed[i] for i in dict.fromkeys(identifiers)) + candidates
    chosen = distinct_claims(ranked, limit, facts)
    return chosen, False


def render_claims(claims: Sequence[AnswerClaim]) -> str:
    if not claims:
        return ""
    return claims[0].text + ("\n\n" + "\n".join(f"- {c.text}" for c in claims[1:]) if len(claims) > 1 else "")


def compose_answer(request: AnswerRequest, *, select: ClaimSelector | None = None,
                   narrator: Writer | None = None) -> GroundedAnswer:
    pack = build_answer_fact_pack(request.evidence)
    if request.presentation in {"chart_only", "table_only"}:
        return GroundedAnswer("", pack.facts)
    if not pack.facts:
        return GroundedAnswer("I found no usable numeric evidence for this scope. Please check the selected filters or period.")
    if pack.conflicts:
        return GroundedAnswer("The calculations returned conflicting values for the same metric and scope. I cannot give a reliable numerical answer until they are reconciled.",
                              pack.facts, limitation="Conflicting evidence")
    candidates = compile_answer_claims(pack, request.question)
    limit = 1 if request.shape in {"lookup", "direct"} else ANALYST_CLAIM_LIMIT
    claims, rejected = select_claims(candidates, limit, select, pack.facts)
    selected_ids = {i for claim in claims for i in claim.fact_ids}
    used = tuple(f for f in pack.facts if f.id in selected_ids)
    claims = compact_claims(claims, used, request.scope)
    ledger = render_claims(claims)
    narration = write_narration(request, claims, pack.facts, ledger, narrator)
    return GroundedAnswer(narration.text or ledger, used, claims, rejected, scope=request.scope,
                          ledger=ledger, narrated=narration.accepted,
                          dropped_figures=narration.dropped,
                          narration_rejected=narration.rejected)


def write_narration(request: AnswerRequest, claims: Sequence[AnswerClaim],
                    facts: Sequence[AnswerFact], ledger: str,
                    narrator: Writer | None) -> Narration:
    """The prose answer, or an empty narration meaning "keep the ledger".

    The whole pack is offered as quotable evidence, not only the facts the
    selected claims cite: the per-slice detail a table is made of is exactly what
    a claim list cannot carry, and it is the missing "context and information"
    that made ledger-only answers read thin.
    """
    if narrator is None or not ledger:
        return Narration()
    brief = build_brief(request.question, request.shape, ledger, claims, facts,
                        request.scope, request.defaulted_period)
    return narrate(brief, narrator)


def content_supported(text: str, ledger: str, claims: Sequence[AnswerClaim],
                      facts: Sequence[AnswerFact], narrated: bool) -> bool:
    """Whether the words on screen are still backed by the reconstructed ledger.

    A ledger answer must match it character for character. A NARRATED answer is
    free prose, so the check is the one the narrator was held to: every figure it
    states is supported by the same claims and facts, and none was invented. That
    keeps the badge honest — edit a number in a stored answer and it stops
    verifying, exactly as it did before prose was allowed.
    """
    if not narrated:
        return text == ledger
    return not unsupported_in(text, supported_numbers(claims, facts))


def validate_record(record: Mapping, text: str, evidence: Sequence[Mapping] | None = None) -> bool:
    """Reconstruct the factual sentences instead of trusting a stored badge.

    Editing a value or sentence invalidates the record, including changes to a
    carrier, sign or unit that a bag-of-numbers check cannot detect.
    """
    if not isinstance(record, Mapping):
        return False
    try:
        facts = tuple(AnswerFact(**dict(f, dimensions=tuple(tuple(d) for d in f["dimensions"])))
                      for f in record.get("facts", []))
        version = record.get("version", 1)
        if version not in LEDGER_VERSIONS | {4}:
            return False
        quotable = facts
        if evidence is not None:
            from core.answers.facts import stable_id
            source = (build_answer_fact_pack if version >= 2 else build_fact_pack)(evidence)
            allowed = {stable_id("", f.as_dict()) for f in source.facts}
            if source.conflicts or any(stable_id("", f.as_dict()) not in allowed for f in facts):
                return False
            # A narrator may quote any figure the turn read back, not only the
            # ones a selected claim happens to cite — a per-slice table is the
            # obvious case. Recompute that set from the evidence rather than
            # storing it, so it is derived at check time exactly as it was at
            # write time and cannot be widened by editing the record.
            quotable = source.facts
        pack = FactPack(facts, 0)
        candidates = (compile_claims(pack, "") if version == 1 else
                      compile_answer_claims(pack, "", legacy=version == 2))
        expected = {c.id: c for c in candidates}
        selected = [expected[c["id"]] for c in record.get("claims", [])]
        if version >= 2:
            scope = tuple(tuple(pair) for pair in record.get("scope", ())) if version >= 3 else ()
            selected = compact_claims(tuple(selected), facts, scope, legacy=version == 2)
            expected = {c.id: c for c in selected}
        claims_match = all(
            c["text"] == expected[c["id"]].text
            and tuple(c["fact_ids"]) == expected[c["id"]].fact_ids
            and c["formula"] == expected[c["id"]].formula
            and c["kind"] == expected[c["id"]].kind
            for c in record.get("claims", [])
        )
        if not (bool(selected) and claims_match):
            return False
        ledger = render_claims(selected)
        if version in LEDGER_VERSIONS:
            return ledger == text == record.get("content")
        return (ledger == record.get("ledger") and text == record.get("content")
                and content_supported(text, ledger, selected, quotable,
                                      bool(record.get("narrated"))))
    except (KeyError, TypeError, ValueError):
        return False
