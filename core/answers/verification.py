"""Checking an answer's MEANING, not just its arithmetic.

`core.answers.narration` already checks that every figure on the page appears in
the ledger. That catches an invented number and nothing else. The failures this
module exists for all pass that check comfortably:

  * a correct figure attached to the wrong product, carrier, year or unit — the
    number is real, it is quoted exactly, and the sentence is false;
  * a query that silently ran on a wider scope than the one requested;
  * a decomposition presented as complete when its parts do not sum to the whole;
  * a required investigation that produced neither a finding nor a limitation,
    so the answer reads complete while being silently thin;
  * a causal claim resting on two numbers that happened to move together.

Each check returns a structured failure naming the claim, the kind of failure,
the pipeline stage responsible and the repair to attempt — the same stage
vocabulary the evaluation harness attributes with, so a failure found in
production and one found in evaluation are described identically.

Pure functions over dataclasses. No model, no database, so every check is
testable with a planted violation — which is the only way to trust a checker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.answers.claims import AnswerClaim
from core.answers.facts import AnswerFact

# ── Stages, mirroring tests/evaluation/stages.py ──────────────────────────── #

INTERPRETATION = "interpretation"
PLANNING = "planning"
RETRIEVAL = "retrieval"
COMPUTATION = "computation"
SELECTION = "selection"
PRESENTATION = "presentation"

STAGE_ORDER: Tuple[str, ...] = (
    INTERPRETATION, PLANNING, RETRIEVAL, COMPUTATION, SELECTION, PRESENTATION,
)

# ── Failure kinds ─────────────────────────────────────────────────────────── #

WRONG_SCOPE = "wrong_scope"
WRONG_SUBJECT = "wrong_subject"
WRONG_UNIT = "wrong_unit"
INCOMPLETE_DECOMPOSITION = "incomplete_decomposition"
MISSING_INVESTIGATION = "missing_investigation"
UNSUPPORTED_CAUSATION = "unsupported_causation"

#: Failure kind -> (stage that owns the repair, what the repair should do).
#: One table, so adding a check means adding a row rather than editing a
#: dispatcher (open/closed).
REPAIRS: Mapping[str, Tuple[str, str]] = {
    WRONG_SCOPE: (RETRIEVAL, "re-run the step under the requested scope"),
    WRONG_SUBJECT: (SELECTION, "rebind the claim to its own subject or drop it"),
    WRONG_UNIT: (COMPUTATION, "recompute the value in the metric's declared unit"),
    INCOMPLETE_DECOMPOSITION: (
        COMPUTATION, "report the residual, or state the coverage limitation"
    ),
    MISSING_INVESTIGATION: (
        PLANNING, "gather the missing evidence, or publish its limitation"
    ),
    UNSUPPORTED_CAUSATION: (PRESENTATION, "restate as an observation, not a cause"),
}


@dataclass(frozen=True)
class Failure:
    """One thing wrong with an answer, and who has to fix it."""

    kind: str
    detail: str
    claim_id: str = ""
    step_id: str = ""
    evidence_id: str = ""

    @property
    def stage(self) -> str:
        return REPAIRS.get(self.kind, (PRESENTATION, ""))[0]

    @property
    def repair(self) -> str:
        return REPAIRS.get(self.kind, ("", "no repair is defined"))[1]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "detail": self.detail, "claim_id": self.claim_id,
            "step_id": self.step_id, "evidence_id": self.evidence_id,
            "stage": self.stage, "repair": self.repair,
        }


@dataclass(frozen=True)
class Verdict:
    """Everything wrong with one answer, worst stage first."""

    failures: Tuple[Failure, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def stage(self) -> str:
        """The earliest failing stage — the one whose repair can fix the rest.

        A wrong scope makes every downstream number wrong too, so repairing the
        writer would only make a wrong answer read better.
        """
        if not self.failures:
            return ""
        return min((f.stage for f in self.failures), key=_stage_rank)

    def of_kind(self, kind: str) -> Tuple[Failure, ...]:
        return tuple(f for f in self.failures if f.kind == kind)

    def as_dicts(self) -> List[dict]:
        return [f.as_dict() for f in self.failures]


def _stage_rank(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return len(STAGE_ORDER)


def verdict(failures: Iterable[Failure]) -> Verdict:
    """Collect failures, ordered by the stage that owns them."""
    ordered = sorted(failures, key=lambda f: (_stage_rank(f.stage), f.kind))
    return Verdict(tuple(ordered))


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def check_scope(evidence: Sequence[Mapping[str, Any]]) -> List[Failure]:
    """Every evidence record whose executed scope lost a requested filter.

    The most dangerous failure in the set, because nothing about the resulting
    number looks wrong: it is a real total, correctly calculated, for a
    population nobody asked about.
    """
    from core.analysis.evidence_ledger import scope_divergence

    failures = []
    for record in evidence or []:
        missing = scope_divergence(record)
        if missing:
            wanted = ", ".join(f"{k}={v!r}" for k, v in sorted(missing.items()))
            failures.append(
                Failure(
                    kind=WRONG_SCOPE,
                    detail=f"the query did not apply {wanted}",
                    step_id=str(record.get("step_id", "")),
                    evidence_id=str(record.get("evidence_id", "")),
                )
            )
    return failures


def check_subject_binding(
    claims: Sequence[AnswerClaim], facts: Sequence[AnswerFact]
) -> List[Failure]:
    """Claims whose cited facts disagree about what they describe.

    A claim compares things; the things must differ in exactly one way. Two facts
    for different products AND different years cannot be a single comparison —
    one of them has been bound to the wrong subject, and the sentence built from
    them is false however real its numbers are.
    """
    by_id = {fact.id: fact for fact in facts}
    failures = []
    for claim in claims:
        cited = [by_id[i] for i in claim.fact_ids if i in by_id]
        if len(cited) < 2:
            continue
        varying = _varying_dimensions(cited)
        if len(varying) > 1:
            failures.append(
                Failure(
                    kind=WRONG_SUBJECT,
                    detail=(
                        f"compares facts differing in {', '.join(sorted(varying))} "
                        "at once, so it describes no single subject"
                    ),
                    claim_id=claim.id,
                )
            )
    return failures


def _varying_dimensions(facts: Sequence[AnswerFact]) -> set:
    seen: Dict[str, set] = {}
    for fact in facts:
        for key, value in fact.dimensions:
            seen.setdefault(key, set()).add(value)
    return {key for key, values in seen.items() if len(values) > 1}


def check_units(
    claims: Sequence[AnswerClaim], facts: Sequence[AnswerFact]
) -> List[Failure]:
    """Claims that combine facts measured in different units.

    A score and a premium can both be 6.5, and a sentence that adds or compares
    them is arithmetic nonsense the figure check cannot see: both numbers are
    real and both appear in the evidence.
    """
    by_id = {fact.id: fact for fact in facts}
    failures = []
    for claim in claims:
        units = {by_id[i].unit for i in claim.fact_ids if i in by_id}
        units.discard("")
        if len(units) > 1:
            failures.append(
                Failure(
                    kind=WRONG_UNIT,
                    detail=f"mixes values measured in {', '.join(sorted(units))}",
                    claim_id=claim.id,
                )
            )
    return failures


def check_decomposition(
    parts: Sequence[float], headline: float, *, cut: str = "", tolerance: float = 1e-6
) -> List[Failure]:
    """Whether a decomposition presented as complete actually reconciles."""
    if not parts:
        return []
    from core.analytics.movement import reconcile

    result = reconcile(parts, headline)
    if result.is_complete:
        return []
    return [
        Failure(
            kind=INCOMPLETE_DECOMPOSITION,
            detail=result.limitation(cut) or "the parts do not sum to the whole",
        )
    ]


def check_completeness(
    requirements: Sequence[str],
    satisfied: Sequence[str],
    limitations: Sequence[str],
) -> List[Failure]:
    """Required evidence that produced neither a finding nor a stated limitation.

    The check that makes a thin answer visible. A turn that gathered no quarterly
    comparison and said nothing about quarters reads exactly like one that had
    nothing to say — unless something asks the question.
    """
    if limitations:
        return []
    missing = [key for key in requirements if key not in set(satisfied)]
    return [
        Failure(
            kind=MISSING_INVESTIGATION,
            detail=f"{key} was required but neither established nor limited",
        )
        for key in missing
    ]


#: Wording that asserts one thing MADE another happen. Deliberately narrow: an
#: analyst must still be able to say "consistent with" or "this suggests", which
#: are interpretations offered as interpretations. Only unhedged causal verbs
#: are flagged.
_CAUSAL = re.compile(
    r"\b(?:because of|caused by|due to|drove|driven by|led to|resulted in|"
    r"as a result of|owing to|thanks to)\b",
    re.IGNORECASE,
)

#: Hedges that turn an assertion into an offered reading. A sentence carrying one
#: is the analyst doing their job, not overclaiming.
_HEDGED = re.compile(
    r"\b(?:may|might|could|appears?|suggests?|consistent with|likely|possibly|"
    r"seems?|potentially|indicates?)\b",
    re.IGNORECASE,
)


def check_causation(text: str, *, evidence_supports_cause: bool = False) -> List[Failure]:
    """Unhedged causal assertions the evidence cannot support.

    Premium data shows that two things moved. It cannot show that one moved the
    other. Unless the caller says causal evidence exists, an unhedged causal verb
    is an overclaim — and the repair is a rewording, not a requery.
    """
    if evidence_supports_cause:
        return []
    failures = []
    for sentence in _sentences(text or ""):
        if _CAUSAL.search(sentence) and not _HEDGED.search(sentence):
            failures.append(
                Failure(
                    kind=UNSUPPORTED_CAUSATION,
                    detail=f"asserts a cause the evidence cannot establish: {sentence!r}",
                )
            )
    return failures


def _sentences(text: str) -> List[str]:
    from core.answers.narration import split_sentences

    return [s for line in text.splitlines() for s in split_sentences(line.strip()) if s]


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class VerificationInput:
    """Everything the checks read. Assembled once, by the caller."""

    text: str = ""
    claims: Tuple[AnswerClaim, ...] = ()
    facts: Tuple[AnswerFact, ...] = ()
    evidence: Tuple[Mapping[str, Any], ...] = ()
    requirements: Tuple[str, ...] = ()
    satisfied: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    evidence_supports_cause: bool = False


def verify_answer(data: VerificationInput) -> Verdict:
    """Run every check over one answer.

    Reads as the list of things that can be wrong. Each check is a plain function
    of its inputs and callable on its own in a test; this only decides the set and
    collects the result, so adding a check is one line here and one function above.
    """
    return verdict(
        [
            *check_scope(data.evidence),
            *check_subject_binding(data.claims, data.facts),
            *check_units(data.claims, data.facts),
            *check_completeness(data.requirements, data.satisfied, data.limitations),
            *check_causation(data.text, evidence_supports_cause=data.evidence_supports_cause),
        ]
    )


# --------------------------------------------------------------------------- #
# Repair
# --------------------------------------------------------------------------- #


def strip_unsupported_causation(text: str, failures: Sequence[Failure]) -> Tuple[str, int]:
    """Remove the sentences that asserted a cause. Returns the text and the count.

    The one repair that needs no model and no requery: the finding underneath is
    sound, only the claim ABOUT it overreached, so deleting the overreaching
    sentence leaves a correct answer rather than a shorter wrong one. It mirrors
    what the figure check already does to an unsupported number.
    """
    targets = {f.detail.split(": ", 1)[-1].strip("'\"") for f in failures
               if f.kind == UNSUPPORTED_CAUSATION}
    if not targets:
        return text, 0

    removed = 0
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        kept = []
        for sentence in _sentences(stripped):
            if sentence in targets:
                removed += 1
            else:
                kept.append(sentence)
        if kept:
            lines.append(" ".join(kept))
    return "\n".join(lines).strip(), removed


def limitations_for(verdict_: Verdict) -> Tuple[str, ...]:
    """Failures that survive repair, as sentences a reader can act on.

    An answer whose scope diverged or whose decomposition does not reconcile is
    still worth publishing — it is the SILENT version of those that is dangerous.
    Stating them is what "publish the validated subset with limitations" means.
    """
    wording = {
        WRONG_SCOPE: "Part of this answer ran on a wider scope than requested",
        WRONG_SUBJECT: "A comparison could not be bound to a single subject",
        WRONG_UNIT: "A comparison mixed different units and was not reported",
        INCOMPLETE_DECOMPOSITION: "The breakdown does not fully reconcile",
        MISSING_INVESTIGATION: "Part of the expected analysis could not be completed",
    }
    out = []
    for failure in verdict_.failures:
        prefix = wording.get(failure.kind)
        if prefix:
            out.append(f"{prefix}: {failure.detail}.")
    return tuple(dict.fromkeys(out))
