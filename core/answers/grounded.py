"""A readable answer pipeline with a small optional model-selection adapter.

The model chooses claim IDs. It cannot supply values, entities, formulas or
factual prose. The default selection makes the same pipeline useful offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from core.answers.claims import AnswerClaim, compile_claims
from core.answers.facts import AnswerFact, FactPack, build_fact_pack


@dataclass(frozen=True)
class AnswerRequest:
    question: str
    evidence: tuple[Mapping, ...]
    shape: str = "analyst"
    presentation: str = "prose"


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    facts: tuple[AnswerFact, ...] = ()
    claims: tuple[AnswerClaim, ...] = ()
    selection_rejected: bool = False
    limitation: str = ""

    def as_dict(self) -> dict:
        return {"version": 1, "content": self.text, "facts": [f.as_dict() for f in self.facts],
                "claims": [c.as_dict() for c in self.claims], "limitation": self.limitation,
                "selection_rejected": self.selection_rejected}


ClaimSelector = Callable[[tuple[AnswerClaim, ...]], Sequence[str]]


def distinct_claims(candidates: Sequence[AnswerClaim], limit: int) -> tuple[AnswerClaim, ...]:
    chosen, covered = [], set()
    for claim in candidates:
        if set(claim.fact_ids) <= covered:
            continue
        chosen.append(claim)
        covered.update(claim.fact_ids)
        if len(chosen) == limit:
            break
    return tuple(chosen)


def select_claims(candidates: tuple[AnswerClaim, ...], limit: int,
                  select: ClaimSelector | None) -> tuple[tuple[AnswerClaim, ...], bool]:
    if select is None:
        return distinct_claims(candidates, limit), False
    try:
        identifiers = list(select(candidates))
    except Exception:
        return distinct_claims(candidates, limit), True
    allowed = {c.id: c for c in candidates}
    if not identifiers or any(not isinstance(i, str) or i not in allowed for i in identifiers):
        return distinct_claims(candidates, limit), True
    chosen = distinct_claims(tuple(allowed[i] for i in dict.fromkeys(identifiers)), limit)
    return chosen, False


def render_claims(claims: Sequence[AnswerClaim]) -> str:
    if not claims:
        return ""
    return claims[0].text + ("\n\n" + "\n".join(f"- {c.text}" for c in claims[1:]) if len(claims) > 1 else "")


def compose_answer(request: AnswerRequest, *, select: ClaimSelector | None = None) -> GroundedAnswer:
    pack = build_fact_pack(request.evidence)
    if request.presentation in {"chart_only", "table_only"}:
        return GroundedAnswer("", pack.facts)
    if not pack.facts:
        return GroundedAnswer("I found no usable numeric evidence for this scope. Please check the selected filters or period.")
    if pack.conflicts:
        return GroundedAnswer("The calculations returned conflicting values for the same metric and scope. I cannot give a reliable numerical answer until they are reconciled.",
                              pack.facts, limitation="Conflicting evidence")
    candidates = compile_claims(pack, request.question)
    limit = 1 if request.shape in {"lookup", "direct"} else 4
    claims, rejected = select_claims(candidates, limit, select)
    text = render_claims(claims)
    selected_ids = {i for claim in claims for i in claim.fact_ids}
    used = tuple(f for f in pack.facts if f.id in selected_ids)
    return GroundedAnswer(text, used, claims, rejected)


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
        if evidence is not None:
            from core.answers.facts import stable_id
            source = build_fact_pack(evidence)
            allowed = {stable_id("", f.as_dict()) for f in source.facts}
            if source.conflicts or any(stable_id("", f.as_dict()) not in allowed for f in facts):
                return False
        expected = {c.id: c for c in compile_claims(FactPack(facts, 0), "")}
        selected = [expected[c["id"]] for c in record.get("claims", [])]
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
