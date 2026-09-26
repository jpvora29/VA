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


ANALYST_CLAIM_LIMIT = 12
ANSWER_VERSION = 5

#: Versions whose `content` is the deterministic ledger verbatim. Version 4 may
#: also carry narrated prose, which verifies by figure support instead. Version
#: 5 adds two presentation changes, both replayed by verification: a claim no
#: longer repeats a scope value its own sentence names, and an un-narrated
#: answer is shown SECTIONED (`present_claims`) rather than as one flat list.
LEDGER_VERSIONS = {1, 2, 3}
PROSE_VERSIONS = {4, 5}


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
    #: What the analysis planner decided this answer should lead with.
    synthesis_focus: str = ""
    #: Requirement keys this kind of question owes its reader, and the sentences
    #: for the ones the turn could not satisfy. Both reach the claim selector and
    #: the writer, so "the evidence was not gathered" and "the answer chose not
    #: to mention it" stop looking identical on the page.
    requirements: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


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
    #: What the turn could not establish, as reader-facing sentences.
    #:
    #: Deliberately NOT part of `ledger` or `text`. The stored record verifies by
    #: rebuilding its text from claims that are themselves re-checked against the
    #: evidence, so everything inside the ledger is derived from something
    #: verifiable. A limitation is derived from the turn's plan, which the record
    #: does not carry — folding it in would mean a sentence that verification
    #: cannot actually check, which is worse than one it does not cover. It rides
    #: alongside instead, and the narrator is told to state it in the prose.
    limitations: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        # `limitations` is additive: `validate_record` reads named keys and
        # ignores the rest, so older records stay valid and this needs no
        # version bump.
        return {"version": ANSWER_VERSION, "content": self.text, "facts": [f.as_dict() for f in self.facts],
                "claims": [c.as_dict() for c in self.claims], "limitation": self.limitation,
                "selection_rejected": self.selection_rejected, "scope": self.scope,
                "ledger": self.ledger or self.text, "narrated": self.narrated,
                "limitations": list(self.limitations)}


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


#: How an un-narrated answer is organised: each verified finding goes under the
#: question it answers, in the order an analyst walks a carrier review — the
#: movement, where the book is concentrated, where the carrier stands, what
#: brokers say, then anything else. Kinds not listed fall into the last group.
CLAIM_SECTIONS: tuple[tuple[str, frozenset[str]], ...] = (
    ("What moved", frozenset({
        "change", "portfolio_change", "growth_driver", "growth_offset", "growth_breadth",
        "growth_resilience", "mix_shift", "premium_mix", "comparison_coverage"})),
    ("Where the book is concentrated", frozenset({
        "concentration", "growth_concentration", "share_of_portfolio"})),
    ("Market position", frozenset({
        "share_of_wallet", "rank", "rank_of", "standing", "position", "positioning",
        "peer_gap", "headroom"})),
    ("What brokers say", frozenset({
        "survey", "survey_movement", "survey_standing", "survey_trailing",
        "surveypractice", "surveysegment"})),
)
OTHER_SECTION = "Also worth knowing"


def section_of(kind: str) -> str:
    for title, kinds in CLAIM_SECTIONS:
        if kind in kinds:
            return title
    return OTHER_SECTION


def present_claims(claims: Sequence[AnswerClaim]) -> str:
    """The verified findings as a READ, not a list: lead, then labelled groups.

    Same sentences as :func:`render_claims`, only arranged — no figure is added,
    dropped or reworded, so it verifies against the same claims. Findings that
    all fall in one group keep the plain layout: a heading over one group is
    scaffolding, not structure.
    """
    if not claims:
        return ""
    lead, rest = claims[0], list(claims[1:])
    groups: dict[str, list[AnswerClaim]] = {}
    for claim in rest:
        groups.setdefault(section_of(claim.kind), []).append(claim)
    if len(groups) < 2:
        return render_claims(claims)
    order = [title for title, _ in CLAIM_SECTIONS] + [OTHER_SECTION]
    parts = [lead.text]
    for title in order:
        if groups.get(title):
            parts.append(f"### {title}\n" + "\n".join(f"- {c.text}" for c in groups[title]))
    return "\n\n".join(parts)


def _conflict_limitations(disputed: Sequence[str]) -> tuple[str, ...]:
    """What was left out because two results disagreed about it."""
    if not disputed:
        return ()
    return (
        f"Two results disagreed on {', '.join(disputed)}, so "
        f"{'that figure was' if len(disputed) == 1 else 'those figures were'} "
        "left out of this answer.",
    )


def compose_answer(request: AnswerRequest, *, select: ClaimSelector | None = None,
                   narrator: Writer | None = None) -> GroundedAnswer:
    pack = build_answer_fact_pack(request.evidence)
    if request.presentation in {"chart_only", "table_only"}:
        return GroundedAnswer("", pack.facts)
    if not pack.facts:
        # Distinguish "nothing came back" from "something came back that I could
        # not turn into verified figures". They look identical to the writer and
        # entirely different to a reader who is looking at a populated table and
        # a rendered chart underneath a sentence claiming there was no evidence.
        rows = sum(len(item.get("rows") or []) for item in request.evidence)
        if rows:
            return GroundedAnswer(
                f"I retrieved {rows} row{'s' if rows != 1 else ''} for this scope but "
                "could not derive verified figures from them, so the data is shown "
                "below without a written analysis.",
                limitation="No verifiable figures",
                limitations=(
                    "The retrieved rows carried no numeric measure this answer "
                    "could verify, so the analysis is the table itself.",
                ),
            )
        return GroundedAnswer("I found no usable numeric evidence for this scope. Please check the selected filters or period.")
    disputed = ()
    if pack.conflicts and not pack.conflicted:
        # A conflict with no identity attached is not two sources disagreeing
        # about one slice — it is a calculation contradicting its own operands
        # (a stated growth rate its own before/after values do not produce).
        # Nothing can be salvaged from that by dropping a slice, so it fails
        # closed exactly as it always has.
        return GroundedAnswer(
            "The calculations returned conflicting values for the same metric and "
            "scope. I cannot give a reliable numerical answer until they are "
            "reconciled.",
            pack.facts, limitation="Conflicting evidence",
        )
    if pack.conflicts:
        # A disagreement about ONE figure is not a reason to withhold every
        # other figure the turn established. The affected identities are dropped,
        # the rest of the answer is written, and what was excluded is stated —
        # which is what a reader who waited three minutes deserves instead of a
        # refusal beside a set of charts drawn from the very same evidence.
        disputed = pack.disputed_labels()
        pack = pack.usable()
        if not pack.facts:
            return GroundedAnswer(
                "The calculations returned conflicting values for the same metric "
                "and scope, and nothing else was established. I cannot give a "
                "reliable numerical answer until they are reconciled.",
                limitation="Conflicting evidence",
                limitations=_conflict_limitations(disputed),
            )
    candidates = compile_answer_claims(pack, request.question)
    limit = 1 if request.shape in {"lookup", "direct"} else ANALYST_CLAIM_LIMIT
    claims, rejected = select_claims(candidates, limit, select, pack.facts)
    selected_ids = {i for claim in claims for i in claim.fact_ids}
    used = tuple(f for f in pack.facts if f.id in selected_ids)
    claims = compact_claims(claims, used, request.scope)
    ledger = render_claims(claims)
    narration = write_narration(request, claims, pack.facts, ledger, narrator)
    return GroundedAnswer(narration.text or present_claims(claims), used, claims, rejected,
                          scope=request.scope,
                          ledger=ledger, narrated=narration.accepted,
                          dropped_figures=narration.dropped,
                          narration_rejected=narration.rejected,
                          limitations=tuple(request.limitations) + _conflict_limitations(disputed))


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
                        request.scope, request.defaulted_period,
                        synthesis_focus=request.synthesis_focus,
                        requirements=request.requirements,
                        limitations=request.limitations)
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
        return text in {ledger, present_claims(claims)}
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
        if version not in LEDGER_VERSIONS | PROSE_VERSIONS:
            return False
        quotable = facts
        if evidence is not None:
            from core.answers.facts import stable_id
            source = (build_answer_fact_pack if version >= 2 else build_fact_pack)(evidence)
            allowed = {stable_id("", f.as_dict()) for f in source.facts}
            # A conflict elsewhere in the turn does not invalidate an answer
            # written from figures that did NOT conflict. Reject only when a
            # fact this record actually uses is one of the disputed identities —
            # otherwise every partial answer would fail its own verification.
            disputed = set(source.conflicted)
            if any((f.metric, f.unit, f.dimensions) in disputed for f in facts):
                return False
            if any(stable_id("", f.as_dict()) not in allowed for f in facts):
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
            selected = compact_claims(tuple(selected), facts, scope, legacy=version == 2,
                                      plain_suffix=version >= 5)
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
