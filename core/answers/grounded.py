"""A readable answer pipeline with a small optional model-selection adapter.

The model chooses claim IDs. It cannot supply values, entities, formulas or
factual prose. The default selection makes the same pipeline useful offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from core.answers.claims import AnswerClaim, compile_claims
from core.answers.facts import AnswerFact, FactPack, build_fact_pack
from core.answers.insights import compile_answer_claims
from core.answers.narrative import compact_claims
from core.answers.comparison_inputs import build_answer_fact_pack
from core.answers.scope import DisplayScope


ANALYST_CLAIM_LIMIT = 10
ANSWER_VERSION = 3


@dataclass(frozen=True)
class AnswerRequest:
    question: str
    evidence: tuple[Mapping, ...]
    shape: str = "analyst"
    presentation: str = "prose"
    scope: DisplayScope = ()


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    facts: tuple[AnswerFact, ...] = ()
    claims: tuple[AnswerClaim, ...] = ()
    selection_rejected: bool = False
    limitation: str = ""
    scope: DisplayScope = ()

    def as_dict(self) -> dict:
        return {"version": ANSWER_VERSION, "content": self.text, "facts": [f.as_dict() for f in self.facts],
                "claims": [c.as_dict() for c in self.claims], "limitation": self.limitation,
                "selection_rejected": self.selection_rejected, "scope": self.scope}


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


def compose_answer(request: AnswerRequest, *, select: ClaimSelector | None = None) -> GroundedAnswer:
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
    text = render_claims(claims)
    return GroundedAnswer(text, used, claims, rejected, scope=request.scope)


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
        if version not in {1, 2, 3}:
            return False
        if evidence is not None:
            from core.answers.facts import stable_id
            source = (build_answer_fact_pack if version >= 2 else build_fact_pack)(evidence)
            allowed = {stable_id("", f.as_dict()) for f in source.facts}
            if source.conflicts or any(stable_id("", f.as_dict()) not in allowed for f in facts):
                return False
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
        return bool(selected) and claims_match and render_claims(selected) == text == record.get("content")
    except (KeyError, TypeError, ValueError):
        return False
