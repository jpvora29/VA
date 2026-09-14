"""Tracking what a plan has actually established, and what to do next.

A plan written before any data is retrieved is a guess about which questions are
worth asking. This module is what turns it into a loop: it records each step's
OUTCOME, works out which of the turn's evidence requirements are now satisfied,
and decides — from the results, not from the original wording — whether another
step is justified and affordable.

Three decisions live here and nowhere else:

  * **what a step achieved.** Satisfied, no data, failed, or skipped-with-reason.
    Four outcomes, never collapsed into "didn't work", because the repair for
    each is different and the limitation each produces is different.
  * **whether to go deeper.** An industry drill-down is admitted by an observed
    material product movement, not by the question containing the word
    "industry". That is the difference between following the data and following
    the prompt.
  * **when to stop.** Requirements satisfied, nothing left worth asking, or the
    budget is spent — and the reason is recorded either way, so a partial answer
    can say WHY it is partial.

Pure functions over dataclasses. No model, no database, no graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from core.analysis.requirements import EvidenceContract, UnmetRequirement

# ── Step outcomes ─────────────────────────────────────────────────────────── #

PENDING = "pending"
SATISFIED = "satisfied"
NO_DATA = "no_data"
FAILED = "failed"
SKIPPED = "skipped"

TERMINAL = frozenset({SATISFIED, NO_DATA, FAILED, SKIPPED})

# ── Stop reasons ──────────────────────────────────────────────────────────── #

COMPLETE = "requirements satisfied"
BOUNDED = "no further step was justified"
EXHAUSTED = "execution budget reached"


@dataclass(frozen=True)
class Budget:
    """What one turn is allowed to spend chasing an explanation.

    Deliberately three separate limits rather than one score. They fail for
    different reasons and a partial answer should be able to say which: "I ran
    out of steps" and "a step kept failing" are different messages to a reader.
    """

    max_steps: int = 8
    max_rounds: int = 3
    max_repairs: int = 2

    def exhausted(self, *, steps: int, rounds: int, repairs: int) -> str:
        """The limit that has been reached, or "" while there is room left."""
        if steps >= self.max_steps:
            return f"step limit of {self.max_steps} reached"
        if rounds >= self.max_rounds:
            return f"planning round limit of {self.max_rounds} reached"
        if repairs >= self.max_repairs:
            return f"repair limit of {self.max_repairs} reached"
        return ""


@dataclass(frozen=True)
class StepOutcome:
    """What one plan step produced."""

    step_id: str
    status: str = PENDING
    requirement: str = ""
    evidence_ids: Tuple[str, ...] = ()
    detail: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def produced_evidence(self) -> bool:
        return self.status == SATISFIED and bool(self.evidence_ids)


@dataclass(frozen=True)
class Finding:
    """One observed result a follow-up decision can be made from.

    Deliberately not the full evidence row: a decision about whether to drill
    into a product needs the product, how much it moved and how much of the
    headline that is — and nothing else. Keeping it this small is what stops the
    follow-up rule from quietly depending on the shape of a query result.
    """

    dimension: str
    value: str
    change: float
    contribution_pp: Optional[float] = None
    source_step: str = ""

    @property
    def magnitude(self) -> float:
        return abs(self.change)


@dataclass
class PlanProgress:
    """The mutable record of what this turn has established so far."""

    contract: EvidenceContract
    budget: Budget = field(default_factory=Budget)
    outcomes: Dict[str, StepOutcome] = field(default_factory=dict)
    rounds: int = 0
    repairs: int = 0
    stop_reason: str = ""

    # ── recording ───────────────────────────────────────────────────────── #

    def record(self, outcome: StepOutcome) -> None:
        """Commit a step's outcome, keyed by step id so a repair replaces it."""
        self.outcomes[outcome.step_id] = outcome

    def begin_round(self) -> None:
        self.rounds += 1

    def begin_repair(self) -> None:
        self.repairs += 1

    # ── reading ─────────────────────────────────────────────────────────── #

    @property
    def steps_run(self) -> int:
        return sum(1 for outcome in self.outcomes.values() if outcome.is_terminal)

    def satisfied_requirements(self) -> Tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                outcome.requirement
                for outcome in self.outcomes.values()
                if outcome.status == SATISFIED and outcome.requirement
            )
        )

    def unmet(self) -> Tuple[UnmetRequirement, ...]:
        """Selected requirements with no satisfying step, each with its reason.

        The reason is the specific one when a step actually tried and failed,
        and the requirement's generic sentence when nothing ever ran — which is
        the difference between "2024 stops at Q2" and "no quarterly evidence was
        gathered", and a reader can act on only one of those.
        """
        satisfied = set(self.satisfied_requirements())
        attempts = self._attempts_by_requirement()
        return tuple(
            requirement.unmet(attempts.get(requirement.key, ""))
            for requirement in self.contract.selected
            if requirement.key not in satisfied
        )

    def _attempts_by_requirement(self) -> Dict[str, str]:
        detail: Dict[str, str] = {}
        for outcome in self.outcomes.values():
            if outcome.status in {NO_DATA, FAILED, SKIPPED} and outcome.requirement:
                detail.setdefault(outcome.requirement, outcome.detail)
        return {key: value for key, value in detail.items() if value}

    def is_complete(self) -> bool:
        return not self.unmet()

    def limitations(self) -> Tuple[str, ...]:
        return tuple(unmet.text for unmet in self.unmet())


# --------------------------------------------------------------------------- #
# Deciding what to do next
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NextStep:
    """A follow-up the observed results justify."""

    requirement: str
    dimension: str
    value: str
    reason: str
    scope: Mapping[str, Any] = field(default_factory=dict)


#: A slice must move at least this share of the headline before it is worth a
#: query of its own. Expressed against the HEADLINE rather than as an absolute
#: currency amount so it travels between books of very different sizes.
MATERIAL_SHARE = 0.20

#: ...and must not be a rounding artefact of a tiny base. A 400% move on three
#: dollars outranks everything on a percentage basis and explains nothing, which
#: is the "tiny base" failure the regression matrix calls out by name.
MATERIAL_MINIMUM = 1.0


def material_findings(
    findings: Sequence[Finding],
    *,
    headline: float,
    share: float = MATERIAL_SHARE,
    minimum: float = MATERIAL_MINIMUM,
) -> Tuple[Finding, ...]:
    """Findings large enough to be worth investigating, largest first.

    Ranked by ABSOLUTE contribution, not by percentage change, so a large slice
    that moved a little outranks a tiny one that moved a lot. Both directions
    qualify: a product that grew strongly against a falling book is exactly as
    worth explaining as one that fell.
    """
    threshold = max(abs(headline) * share, minimum)
    material = [f for f in findings if f.magnitude >= threshold]
    return tuple(sorted(material, key=lambda f: f.magnitude, reverse=True))


def decide_next_steps(
    progress: PlanProgress,
    findings: Sequence[Finding],
    *,
    headline: float,
    limit: int = 1,
) -> Tuple[NextStep, ...]:
    """Follow-up steps the RESULTS justify, within what the contract selected.

    Returns nothing — which is a complete answer, not a failure — when the
    contract asks for no drill-down, when nothing moved materially, or when the
    budget is spent. `limit` bounds how many drill-downs one round may add, so a
    book with six material products does not become six more queries.
    """
    if progress.budget.exhausted(
        steps=progress.steps_run, rounds=progress.rounds, repairs=progress.repairs
    ):
        return ()
    if not progress.contract.requires("industry_concentration"):
        return ()
    if "industry_concentration" in progress.satisfied_requirements():
        return ()

    material = material_findings(findings, headline=headline)
    return tuple(
        NextStep(
            requirement="industry_concentration",
            dimension=finding.dimension,
            value=finding.value,
            scope={finding.dimension: finding.value},
            reason=(
                f"{finding.value} moved {finding.change:+,.1f}, "
                f"{_share_text(finding, headline)} of the total movement"
            ),
        )
        for finding in material[:limit]
    )


def _share_text(finding: Finding, headline: float) -> str:
    if finding.contribution_pp is not None:
        return f"{finding.contribution_pp:+.1f} points"
    if headline:
        return f"{finding.change / headline * 100:.0f}%"
    return "an unquantified share"


def stop_reason(progress: PlanProgress) -> str:
    """Why the loop ended. Always a sentence, never an empty silence.

    Completion is checked before exhaustion on purpose: a turn that answered
    everything on its last affordable step finished, and reporting a budget
    limit there would attach a limitation to a complete answer.
    """
    if progress.is_complete():
        return COMPLETE
    exhausted = progress.budget.exhausted(
        steps=progress.steps_run, rounds=progress.rounds, repairs=progress.repairs
    )
    return f"{EXHAUSTED}: {exhausted}" if exhausted else BOUNDED


# --------------------------------------------------------------------------- #
# Attaching identity to a planned step
# --------------------------------------------------------------------------- #


def assign_identity(
    plan: Any,
    *,
    contract: EvidenceContract,
    scope: Optional[Mapping[str, Any]] = None,
    requirement_of: Optional[Any] = None,
) -> Any:
    """Give every step a stable id, a requirement, a source and a scope.

    Done deterministically after planning rather than asked of the model: ids a
    model invents collide, and a requirement a model assigns is a claim about
    what its own step will achieve. `requirement_of(step, index)` maps a step to
    a requirement key; without one, steps take the contract's requirements in
    order, which is the right default because the planner is already told to put
    the step that answers the literal question first.
    """
    keys = list(contract.keys())
    revised = []
    for index, step in enumerate(plan.derived):
        requirement = (
            requirement_of(step, index) if requirement_of is not None
            else (keys[index] if index < len(keys) else "")
        )
        spec = next(
            (r for r in contract.selected if r.key == requirement), None
        )
        revised.append(
            step.model_copy(
                update={
                    "step_id": f"s{index}_{step.lens or 'step'}",
                    "requirement": requirement,
                    "source": spec.source if spec else "",
                    "scope": dict(scope or {}),
                    "priority": index,
                }
            )
        )
    return plan.model_copy(update={"derived": revised})
