"""Multi-agent analyst subgraph.

Replaces the single ReAct loop with specialized agents that hand structured
context to each other, for context isolation and reliability:

    START
      -> planner_node            (select + order analytical lenses)
      -> schema_identifier_node  (resolve the minimal grounded schema slice once)
      -> dispatch (Send fan-out) ──▶ peer_solver_node    ─┐
                                 ──▶ generic_solver_node ─┴─▶ join_node
      -> join_node               (run dependency-bound steps serially)
      -> writer_node             (facts -> calculated claims -> select IDs -> text)
      -> chart_picker_node       (one relevant chart from the evidence)
      -> END

Independent lenses (no `depends_on`) run in parallel via the LangGraph `Send`
API; each solver appends to the shared `evidence` channel through an add-reducer,
so concurrent writes merge safely. Dependency-bound steps run serially in
`join_node`, fed the evidence the parallel wave produced.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import Annotated, TypedDict

from core.agents.analyst.chart_picker import ChartFocus, pick_charts
from core.analytics.dimensions import choose_dimension
from core.analytics.positioning import build_positioning_comparison
from core.answers.positioning_claims import LENS as POSITIONING_LENS
from core.agents.common.contract import resolved_filters_of, unresolved_terms_of
from core.agents.common.peer_privacy import (
    build_policy,
    redact_text,
    redacted_names,
    subjects_from_resolved,
)
from core.agents.common.directives import (
    answer_shape,
    charts_suppressed,
    presentation_mode,
)
from core.agents.analyst.generic_solver import solve_generic
from core.agents.analyst.insight_writer import grounded_insight
from core.answers.claims import AnswerClaim
from core.answers.facts import AnswerFact
from core.answers.scope import answer_scope
from core.answers.verification import (
    UNSUPPORTED_CAUSATION,
    VerificationInput,
    limitations_for,
    strip_unsupported_causation,
    verdict,
    verify_answer,
)
from core.agents.analyst.peer_solver import solve_peer
from core.agents.analyst.schema_identifier import identify_schema
from core.agents.analyst.common import digest_evidence
from core.analysis import build_contract, plan_analysis
from core.analysis.evidence_ledger import build_evidence, merge_evidence
from core.analysis.operation import detect_operation, detect_source_restriction
from core.analysis.progress import (
    Budget,
    PlanProgress,
    StepOutcome,
    assign_identity,
    NO_DATA,
    SATISFIED,
    decide_next_steps,
    stop_reason,
)
from core.analysis.alignment import QUARTER, available_grains
from core.analysis.requirements import (
    GPR,
    SURVEY,
    EvidenceContract,
    performance_sources,
)
from core.analysis.validation import plan_limit, validate_plan
from core.initialization import Initialization
from core.observability import log_event
from core.schemas.analysis import AnalysisPlan, DerivedAnalysis
from core.schemas.analyst_subgraph import Evidence, SchemaSlice
from core.schemas.routing import RoutingContext
from logger import get_logger

logger = get_logger(__name__)

# The one lens whose work routes to the peer-comparison specialist; everything
# else goes to the generic solver.
_PEER_LENS = "peer_benchmark"

# The cut a product drill-down goes down into. Named once here rather than
# spelled into the sub-question, so the industry column this system reasons in
# is changed in one place.
_DRILL_DIMENSION = "industry"


class AnalystState(TypedDict):
    """Internal state for the analyst subgraph (isolated from the global AgentState)."""

    question: str
    route: str
    flow: str
    routing_context: Optional[RoutingContext]
    # Session-pinned custom peer override + per-turn switch (see AgentState).
    custom_peers: Optional[dict]
    custom_peers_active: bool
    plan: AnalysisPlan
    # The lens of the planner's step 0 — the one that answers the user's literal
    # question. Carried out of the subgraph so the caller can tell the answer's
    # own result set apart from the supporting lenses' (see `answer_table`).
    primary_lens: str
    schema_slice: SchemaSlice
    # Identity-keyed merge, not `operator.add`. Parallel solvers still merge
    # without racing, and the same query recorded twice — by two solvers that
    # happened to need it, or by a step re-run after a failure — collapses to
    # one record instead of reading downstream as two confirmations of the same
    # number. See `core.analysis.evidence_ledger`.
    evidence: Annotated[List[Evidence], merge_evidence]
    # What this turn's question is entitled to be answered with, and what it has
    # established so far. The contract decides how many steps the plan may have
    # and which drill-downs are admissible; the progress record decides when the
    # loop stops and what the answer has to admit it could not establish.
    contract: EvidenceContract
    progress: Optional[PlanProgress]
    answer: str
    answer_record: dict
    # Up to 3 chart specs picked from the gathered evidence (title/rows/chart_data).
    charts: List[dict]
    # Charts decided from the data rather than picked by a model. When this
    # is non-empty the picker uses it: a performance answer's charts are not
    # a judgement call, and a deterministic plan cannot describe a different
    # slice from the prose beside it.
    chart_plan: List[dict]


def _model():
    return Initialization.llm


def build_turn_contract(state: AnalystState) -> EvidenceContract:
    """What this turn's question is entitled to be answered with.

    Reads the operation off the question, resolves which datasets may serve it
    (an explicit "premium only" beating the configured default), and asks the
    requirement library for the contract. The conditions supplied here are the
    ones knowable BEFORE any retrieval — a drill-down is not among them, because
    admitting it depends on a result that does not exist yet.
    """
    rc = state.get("routing_context")
    question = state["question"]
    depth = getattr(rc, "analysis_depth", "") or ""
    operation = detect_operation(question, depth="analytical" if depth == "analytical" else depth)
    restricted = detect_source_restriction(question)
    allowed = performance_sources(requested=restricted)
    # The router already decided which families this turn may touch; a survey
    # requirement on a premium-only route is unsatisfiable by construction.
    if state["route"] == "premium":
        allowed = tuple(source for source in allowed if source == "gpr") or ("gpr",)
    elif state["route"] == "survey":
        allowed = ("survey",)
    return build_contract(
        operation,
        conditions=turn_conditions(state, allowed),
        allowed_sources=allowed,
    )


def turn_conditions(state: AnalystState, allowed: tuple) -> tuple:
    """Conditions knowable BEFORE any retrieval.

    Only two kinds of thing belong here: what the router already decided, and
    what the registry already knows about a flow's shape. Whether the warehouse
    actually holds comparable survey years for THIS carrier and country is not
    knowable yet, and guessing it either way is wrong — admitting the requirement
    optimistically and letting the step report `no_data` produces a stated
    limitation, which is the outcome the plan asks for. Deferring it instead
    would produce silence, which is the outcome it warns against.
    """
    conditions = []
    if SURVEY in allowed and state["route"] in {"both", "survey"}:
        conditions.append("comparable_survey_data")
    if QUARTER in available_grains(state.get("flow") or GPR):
        conditions.append("quarterly_data_available")
    return tuple(conditions)


def planner_node(state: AnalystState) -> dict:
    """Select and order the analytical lenses, bounded by the turn's contract."""
    contract = build_turn_contract(state)
    plan = plan_analysis(state["question"], state.get("routing_context"), mode="chat")
    # Re-bound the plan against the contract: a performance question needs more
    # steps than the flat default, and the planner's own cap is deliberately
    # generous rather than requirement-aware.
    plan = validate_plan(
        plan, {d.lens for d in plan.derived}, limit=plan_limit(contract)
    )
    plan = assign_identity(
        plan, contract=contract, scope=resolved_filters_of(state.get("routing_context"))
    )
    log_event(
        logger,
        "analysis_planned",
        node="analyst_planner",
        route=state["route"],
        flow=state["flow"],
        lenses=[d.lens for d in plan.derived],
        derived_count=len(plan.derived),
        intent=contract.intent,
        requirements=list(contract.keys()),
        deferred=[r.key for r in contract.deferred],
        step_limit=plan_limit(contract),
    )
    return {
        "plan": plan,
        "contract": contract,
        "progress": PlanProgress(contract=contract, budget=Budget(max_steps=plan_limit(contract))),
        "primary_lens": plan.derived[0].lens if plan.derived else "",
    }


def schema_identifier_node(state: AnalystState) -> dict:
    """Resolve the minimal grounded schema slice the solvers will share."""
    plan: AnalysisPlan = state["plan"]
    sub_questions = [d.sub_question for d in plan.derived if d.sub_question]
    schema_slice = identify_schema(
        question=state["question"],
        sub_questions=sub_questions or [state["question"]],
        flow=state["flow"],
        # Contract seed: the context filler already resolved this turn's entity
        # mentions to exact stored values — the slice must carry the same ones.
        pre_resolved=resolved_filters_of(state.get("routing_context")),
    )
    # Gate the solver's zero-row guard: only arm it when the user named an entity
    # the contract could NOT resolve. With everything cleanly resolved, a 0-row
    # result is real "no data" — not a filter typo to chase with a re-run.
    schema_slice.guard_zero_rows = bool(
        unresolved_terms_of(state.get("routing_context"))
    )
    return {"schema_slice": schema_slice}


def _independent_indices(plan: AnalysisPlan) -> List[int]:
    """Indices of derived steps with no unmet dependency (the parallel wave 1)."""
    independent = [i for i, d in enumerate(plan.derived) if not d.depends_on]
    # The planner's step 0 always answers the literal question and should lead the
    # wave even in the rare case it was (incorrectly) marked dependent.
    if plan.derived and 0 not in independent:
        independent.insert(0, 0)
    return independent


def _target_for(lens: str) -> str:
    return "peer_solver_node" if lens == _PEER_LENS else "generic_solver_node"


def _payload(state: AnalystState, step) -> dict:
    """Self-contained input for a solver node (Send replaces channel state).

    Carries the STEP, not just its sub-question, so the evidence a parallel
    solver returns can be attributed to the requirement that asked for it. A
    `Send` payload replaces channel state entirely, so anything the solver's
    evidence needs to be stamped with has to travel in here.
    """
    return {
        "question": state["question"],
        "sub_question": step.sub_question,
        "lens": step.lens,
        "flow": step.source or state["flow"],
        "route": state["route"],
        "schema_slice": state["schema_slice"],
        "custom_peers": state.get("custom_peers"),
        "custom_peers_active": state.get("custom_peers_active", False),
        "step": step,
        "scope": dict(step.scope or {}),
    }


def dispatch(state: AnalystState) -> List[Send]:
    """Fan out the independent lenses to their solvers in parallel via Send."""
    plan: AnalysisPlan = state["plan"]
    if not plan.derived:
        # No plan — answer the literal question with one generic solver.
        literal = DerivedAnalysis(
            lens="", sub_question=state["question"], step_id="s0_literal"
        )
        return [Send("generic_solver_node", _payload(state, literal))]
    return [
        Send(_target_for(plan.derived[i].lens), _payload(state, plan.derived[i]))
        for i in _independent_indices(plan)
    ]


def _solve(solver, payload: dict) -> dict:
    """Run one solver on a Send payload and stamp its step onto the evidence."""
    rows = solver(
        model=_model(),
        question=payload["question"],
        sub_question=payload["sub_question"],
        lens=payload["lens"],
        flow=payload["flow"],
        route=payload["route"],
        schema_slice=payload["schema_slice"],
        custom_peers=payload.get("custom_peers"),
        custom_peers_active=payload.get("custom_peers_active", False),
    )
    step = payload.get("step")
    if step is None:
        return {"evidence": rows}
    return {"evidence": [stamp_step(row, step, payload.get("scope")) for row in rows]}


def peer_solver_node(payload: dict) -> dict:
    """Run the peer-comparison specialist on one sub-question (parallel-safe)."""
    return _solve(solve_peer, payload)


def generic_solver_node(payload: dict) -> dict:
    """Run the generic per-lens solver on one sub-question (parallel-safe)."""
    return _solve(solve_generic, payload)


def run_step(state: AnalystState, step, *, prior: List[Evidence], scope=None) -> List[Evidence]:
    """Execute one plan step and stamp its identity onto the evidence it returns.

    A step is a plain function of the state and the step, so it is callable on
    its own in a test. It never calls another step — ordering lives in
    `join_node` and nowhere else.
    """
    solver = solve_peer if step.lens == _PEER_LENS else solve_generic
    rows = solver(
        model=_model(),
        question=state["question"],
        sub_question=step.sub_question,
        lens=step.lens,
        flow=step.source or state["flow"],
        route=state["route"],
        schema_slice=state["schema_slice"],
        prior_digest=digest_evidence(prior),
        custom_peers=state.get("custom_peers"),
        custom_peers_active=state.get("custom_peers_active", False),
    )
    return [stamp_step(row, step, scope) for row in rows]


def stamp_step(row: Evidence, step, scope=None) -> Evidence:
    """Attach the asking step's identity and scope to a solver's raw evidence.

    The solver knows what it ran; only the caller knows WHY, and the link from a
    number back to the requirement that asked for it is what lets an unmet
    requirement name a specific failure instead of a generic one.
    """
    from core.analysis.evidence_ledger import identity_of, now_iso

    stamped: Evidence = dict(row)  # type: ignore[assignment]
    stamped.setdefault("scope", dict(scope or step.scope or {}))
    stamped.setdefault("actual_scope", dict(stamped.get("scope") or {}))
    stamped.setdefault("tool", "run_sql" if row.get("sql") else "")
    stamped.setdefault("status", "validated" if row.get("rows") else "no_data")
    stamped.setdefault("retrieved_at", now_iso())
    stamped.setdefault("version", 1)
    stamped["step_id"] = step.step_id
    stamped["evidence_id"] = identity_of(stamped)
    return stamped


def outcome_for(step, rows: List[Evidence]) -> StepOutcome:
    """What a step achieved, keeping "found nothing" apart from "did not run".

    A step that returned rows is satisfied. One that ran and returned none is
    `no_data` — a real finding about the scope, and the thing an honest
    limitation is written from. Neither is an error.
    """
    from core.analysis.evidence_ledger import VALIDATED

    produced = [row for row in rows if row.get("status") == VALIDATED and row.get("rows")]
    if produced:
        return StepOutcome(
            step_id=step.step_id,
            status=SATISFIED,
            requirement=step.requirement,
            evidence_ids=tuple(str(row.get("evidence_id", "")) for row in produced),
        )
    return StepOutcome(
        step_id=step.step_id,
        status=NO_DATA,
        requirement=step.requirement,
        detail=(
            f"No rows were returned for {step.sub_question!r} on the requested scope."
        ),
    )


def join_node(state: AnalystState) -> dict:
    """Run dependent steps, then whatever the results themselves justify.

    Three phases, in one place so the order is readable and reorderable:

      1. the plan's dependency-bound steps, fed the parallel wave's evidence;
      2. drill-downs admitted by what those results actually showed — the
         industry cut follows the product that moved, not the question's wording;
      3. a recorded stop reason, so a partial answer can say why it stopped.

    The loop is bounded by the turn's `Budget`, and every exit writes a reason.
    """
    plan: AnalysisPlan = state["plan"]
    progress: PlanProgress = state.get("progress") or PlanProgress(
        contract=state.get("contract") or EvidenceContract(intent="")
    )
    scope = resolved_filters_of(state.get("routing_context"))

    accumulated: List[Evidence] = list(state.get("evidence", []))
    new_rows: List[Evidence] = []

    # Wave 1 already ran in the solver nodes; record what it achieved so the
    # follow-up decision sees a complete picture.
    record_parallel_outcomes(progress, plan, accumulated)

    independent = set(_independent_indices(plan))
    progress.begin_round()
    for index in range(len(plan.derived)):
        if index in independent:
            continue
        step = plan.derived[index]
        rows = run_step(state, step, prior=accumulated, scope=scope)
        progress.record(outcome_for(step, rows))
        accumulated = merge_evidence(accumulated, rows)
        new_rows.extend(rows)

    followups = run_followups(state, progress, accumulated, scope)
    accumulated = merge_evidence(accumulated, followups)
    new_rows.extend(followups)

    progress.stop_reason = stop_reason(progress)
    log_event(
        logger,
        "analysis_progress",
        node="analyst_join",
        route=state["route"],
        steps_run=progress.steps_run,
        rounds=progress.rounds,
        satisfied=list(progress.satisfied_requirements()),
        limitations=list(progress.limitations()),
        stop_reason=progress.stop_reason,
    )
    return {"evidence": new_rows, "progress": progress}


def record_parallel_outcomes(
    progress: PlanProgress, plan: AnalysisPlan, evidence: List[Evidence]
) -> None:
    """Attribute the parallel wave's evidence back to the steps that asked for it."""
    by_step: dict = {}
    for row in evidence:
        by_step.setdefault(str(row.get("step_id", "")), []).append(row)
    for index in _independent_indices(plan):
        step = plan.derived[index]
        progress.record(outcome_for(step, by_step.get(step.step_id, [])))


def run_followups(
    state: AnalystState, progress: PlanProgress, evidence: List[Evidence], scope
) -> List[Evidence]:
    """Drill-downs the observed results justify, within the remaining budget.

    Returns nothing when the contract asks for no drill-down, when nothing moved
    materially, or when the budget is spent — all three are complete answers, and
    the reason is recorded by the caller.
    """
    from core.analysis.observations import observe

    findings, headline = observe(evidence)
    steps = decide_next_steps(progress, findings, headline=headline)
    if not steps:
        return []

    plan: AnalysisPlan = state["plan"]
    produced: List[Evidence] = []
    for offset, follow in enumerate(steps):
        progress.begin_round()
        step = DerivedAnalysis(
            lens="dimensional_breakdown",
            sub_question=(
                f"Within {follow.value}, how did premium move by "
                f"{_DRILL_DIMENSION} between the two years?"
            ),
            rationale=follow.reason,
            step_id=f"f{len(plan.derived) + offset}_{follow.requirement}",
            requirement=follow.requirement,
            source=state["flow"],
            scope={**(scope or {}), **follow.scope},
            priority=len(plan.derived) + offset,
        )
        log_event(
            logger,
            "drilldown_admitted",
            node="analyst_join",
            route=state["route"],
            requirement=follow.requirement,
            target=follow.value,
            reason=follow.reason,
        )
        rows = run_step(state, step, prior=evidence, scope=step.scope)
        progress.record(outcome_for(step, rows))
        produced.extend(rows)
    return produced


#: Requirements whose answer is about standing across a dimension, so the
#: positioning pack is worth the handful of extra queries it costs.
_POSITIONING_REQUIREMENTS = frozenset({
    # The requirement that IS the positioning table.
    "positioning",
    # A movement answer carries it too: share of wallet and rank are what turn
    # "premium fell $300k" into something a reader can act on.
    "product_contributors",
    "annual_movement",
    "direct_value",
    "whitespace",
})


def positioning_node(state: AnalystState) -> dict:
    """Gather where the carrier STANDS, deterministically, before the answer is written.

    Everything here is computed by signed-off primitives rather than asked of a
    solver. The numbers a reader needs to turn "premium was $900k" into something
    actionable — share of the carrier's own book, share of Marsh's wallet, rank,
    unheld market — are always the same numbers, so asking a model to remember to
    fetch them is a reliability problem with no upside.

    Best-effort: a warehouse that cannot answer one of the six leaves that column
    out (see `core.analytics.positioning`), and a failure here never costs the
    turn its answer.
    """
    contract = state.get("contract")
    required = set(contract.keys()) if contract else set()
    if state.get("flow") != "gpr" or not (required & _POSITIONING_REQUIREMENTS):
        log_event(logger, "positioning_skipped", logging.WARNING,
                  node="analyst_positioning", route=state["route"],
                  flow=state.get("flow"), requirements=sorted(required),
                  reason="this turn asks for no requirement the position table serves")
        return {}

    scope = dict(resolved_filters_of(state.get("routing_context")) or {})
    # A question that names no carrier still deserves a table — it is a question
    # about the market, and the pack drops the carrier-specific columns for it
    # (see `PositioningPack.is_market_view`). Only the columns change, not
    # whether the reader gets one.
    subject = _subject_carrier(state, scope)

    # Cut by the finest level the question has NOT already fixed. Asking about
    # one product and cutting by product gives a single row whose share of the
    # book is 100% by construction — the table has nothing to compare, which is
    # exactly what a penetration question needs it to do.
    dimension = choose_dimension(scope, flow="gpr")
    if not dimension:
        log_event(logger, "positioning_skipped", logging.WARNING,
                  node="analyst_positioning", route=state["route"],
                  reason="the question fixes every dimension, so there is nothing to break out",
                  scope=sorted(scope))
        return {}

    try:
        pack = build_positioning_comparison(
            dimension=dimension, filters=scope, subject=subject
        )
    except Exception as exc:  # noqa: BLE001 - positioning is additive, never fatal
        log_event(logger, "positioning_failed", logging.WARNING,
                  node="analyst_positioning", route=state["route"], error=str(exc))
        return {}
    if not pack:
        # The queries ran and returned nothing usable. Silent until now, which is
        # why a missing table was impossible to diagnose from the outside: the
        # reader saw no table and no reason, and neither did the log.
        log_event(logger, "positioning_empty", logging.WARNING,
                  node="analyst_positioning", route=state["route"],
                  dimension=dimension, subject=subject or "(market)",
                  scope=sorted(scope),
                  reason="no slice returned a figure for this scope")
        return {}

    record = build_evidence(
        flow="gpr",
        rows=pack.numeric_rows(),
        lens=POSITIONING_LENS,
        tool="build_positioning",
        parameters={"dimension": pack.dimension, "subject": subject},
        requested_scope=scope,
        actual_scope=scope,
        metric="premium",
    )
    plan = _chart_plan_for(state, pack, scope)
    if pack.missing:
        log_event(logger, "positioning_partial", logging.WARNING,
                  node="analyst_positioning", route=state["route"],
                  missing=list(pack.missing),
                  reason="these columns could not be computed for this warehouse")
    log_event(logger, "positioning_gathered", node="analyst_positioning",
              route=state["route"], slices=len(pack.positions),
              dimension=pack.dimension, subject=subject or "(market)",
              missing=list(pack.missing), charts=[spec.get("tab") for spec in plan])
    return {"evidence": [record], "chart_plan": plan}


def _chart_plan_for(state: AnalystState, pack, scope: dict) -> List[dict]:
    """The charts this answer should carry, as renderable views.

    The quarterly pair is fetched here rather than reused from the solvers'
    evidence because the chart needs the two years side by side as columns, and
    a solver's rows are whatever shape its query returned.
    """
    from core.analytics.movement import compute_aligned_periods, resolve_year_pair
    from core.analytics.types import PrimitiveArgs
    from core.answers.chart_plan import build_chart_plan, quarterly_rows_from

    quarterly: List[dict] = []
    try:
        facts = compute_aligned_periods(
            PrimitiveArgs(flow="gpr", metric="premium", filters=scope)
        )
        if facts:
            dims = facts[0].dims
            quarterly = quarterly_rows_from(
                facts,
                current_year=int(dims.get("year")),
                prior_year=int(dims.get("prior_year")),
            )
    except Exception as exc:  # noqa: BLE001 - a missing chart never costs the answer
        log_event(logger, "quarterly_chart_unavailable", logging.WARNING,
                  node="analyst_positioning", route=state["route"], error=str(exc))

    views = [
        spec.as_view()
        for spec in build_chart_plan(pack, quarterly_rows=quarterly, scope=scope)
    ]
    # The positioning table is a VIEW, not only an input to the commentary. It
    # was being computed, feeding the claims, and then never rendered: the panel
    # is built from this list alone, so a result set that is not in it does not
    # reach the reader however carefully it was assembled.
    # The table leads. It is the evidence every sentence above it was written
    # from, so it is what a reader checks first; a chart is the illustration.
    return [_positioning_view(pack, scope), *views]


def _positioning_view(pack, scope: dict) -> dict:
    """The positioning table as a table-only view (no chart spec, so rows render)."""
    from core.analytics.dimensions import describe_scope, label_for

    level = label_for(pack.dimension)
    unit = pack.money_suffix()
    return {
        "tab": "Position",
        "title": f"Position by {level}{describe_scope(scope, pack.dimension)}",
        "rows": pack.rows(),
        "chart_data": {},
        "lens": "positioning",
        "note": (
            f"Premium in {unit or 'currency units'}"
            if unit else "Premium in currency units"
        ),
    }


def _subject_carrier(state: AnalystState, scope: dict) -> str:
    """The carrier the answer is about, from the turn's resolved filters."""
    from core.registry import get_flow_registry

    spec = get_flow_registry().get("gpr")
    column = (getattr(spec, "entity_columns", {}) or {}).get("carrier") if spec else None
    value = scope.get(column) if column else None
    if isinstance(value, (list, tuple)):
        value = value[0] if len(value) == 1 else None
    return str(value) if value else ""


def writer_node(state: AnalystState) -> dict:
    """Build a grounded answer and record from all gathered evidence."""
    plan: AnalysisPlan = state.get("plan") or AnalysisPlan()
    rc = state.get("routing_context")
    evidence = [dict(item, scope=item.get("scope") or resolved_filters_of(rc))
                for item in state.get("evidence", [])]
    progress = state.get("progress")
    contract = state.get("contract")
    result = grounded_insight(
        question=state["question"],
        route=state["route"],
        synthesis_focus=plan.synthesis_focus,
        evidence=evidence,
        presentation=presentation_mode(rc),
        shape=answer_shape(rc),
        scope=answer_scope(state),
        # What this question owed its reader, and what the turn could not
        # establish. Without the second of these a missing quarterly comparison
        # is invisible on the page: the answer simply does not mention quarters,
        # and reads exactly like one that had nothing to say about them.
        requirements=contract.keys() if contract else (),
        limitations=progress.limitations() if progress else (),
    )
    return {"answer": scrub_peer_names(result.text, evidence, state), "answer_record": result.as_dict()}


def scrub_peer_names(answer: str, evidence: List[Evidence], state: AnalystState) -> str:
    """Last line of defence over the written answer.

    The evidence the writer saw is already redacted, so this should find nothing.
    It covers the ways a peer name can reach the prose without passing through a
    tool result -- quoted from the user's own question, or carried in a schema
    note -- and it is cheap enough to run unconditionally. Unlike the row
    redaction it has no per-peer labels to restore, so a leak becomes "a peer".
    """
    hidden = redacted_names(evidence)
    if not hidden:
        return answer
    slice_ = state.get("schema_slice")
    policy = build_policy(
        state["flow"],
        [
            *subjects_from_resolved(getattr(slice_, "resolved_values", None), state["flow"]),
            (state.get("custom_peers") or {}).get("carrier") or "",
        ],
    )
    scrubbed = redact_text(answer, hidden, policy)
    if scrubbed != answer:
        log_event(
            logger,
            "peer_name_scrubbed_from_answer",
            logging.WARNING,
            node="insight_writer",
            route=state["route"],
            names=len(hidden),
        )
    return scrubbed


def verify_node(state: AnalystState) -> dict:
    """Check the written answer's MEANING, repair what can be repaired, publish.

    The figure check inside the writer already proved every number came from the
    evidence. This asks the questions that check cannot: is each number attached
    to the right subject, did a query quietly widen its scope, was a required
    investigation silently skipped, does a sentence assert a cause the data
    cannot show.

    One bounded pass, and never a re-run: the only repair applied here is the
    deterministic one — deleting an overclaiming sentence, which leaves the
    findings underneath intact. Everything else becomes a stated limitation,
    because publishing a validated subset with its gaps named is a better answer
    than either a silent gap or no answer at all.
    """
    record = dict(state.get("answer_record") or {})
    answer = state.get("answer") or ""
    if not answer or not record:
        return {}

    progress = state.get("progress")
    contract = state.get("contract")
    data = VerificationInput(
        text=answer,
        claims=tuple(_claims_of(record)),
        facts=tuple(_facts_of(record)),
        evidence=tuple(state.get("evidence") or []),
        requirements=tuple(contract.keys()) if contract else (),
        satisfied=tuple(progress.satisfied_requirements()) if progress else (),
        limitations=tuple(progress.limitations()) if progress else (),
    )
    result = verify_answer(data)
    if result.passed:
        return {}

    repaired, removed = strip_unsupported_causation(answer, result.failures)
    remaining = verdict(f for f in result.failures if f.kind != UNSUPPORTED_CAUSATION)
    limitations = tuple(dict.fromkeys(
        (*(record.get("limitations") or ()), *limitations_for(remaining))
    ))
    record["content"] = repaired or answer
    record["limitations"] = list(limitations)
    record["verification"] = result.as_dicts()

    log_event(
        logger,
        "answer_verified",
        logging.WARNING,
        node="analyst_verifier",
        route=state["route"],
        stage=result.stage,
        failures=[f.kind for f in result.failures],
        causal_sentences_removed=removed,
        limitations=len(limitations),
    )
    return {"answer": repaired or answer, "answer_record": record}


def _claims_of(record: dict) -> List[AnswerClaim]:
    """Rebuild the typed claims from a stored record, tolerating a partial one."""
    out = []
    for raw in record.get("claims") or []:
        try:
            out.append(AnswerClaim(**{**raw, "fact_ids": tuple(raw.get("fact_ids", ())),
                                      "focus_ids": tuple(raw.get("focus_ids", ()))}))
        except (TypeError, ValueError):
            continue
    return out


def _facts_of(record: dict) -> List[AnswerFact]:
    """Rebuild the typed facts from a stored record, tolerating a partial one."""
    out = []
    for raw in record.get("facts") or []:
        try:
            out.append(AnswerFact(**{
                **raw,
                "dimensions": tuple(tuple(pair) for pair in raw.get("dimensions", ())),
                "support": tuple(raw.get("support", ())),
            }))
        except (TypeError, ValueError):
            continue
    return out


def chart_picker_node(state: AnalystState) -> dict:
    """Pick and build one primary chart from gathered evidence (best-effort)."""
    # Query-contract gate: "don't generate a chart" means exactly that.
    if charts_suppressed(state.get("routing_context")):
        log_event(
            logger,
            "charts_suppressed_by_directive",
            node="analyst_chart_picker",
            route=state["route"],
        )
        return {"charts": []}
    planned = list(state.get("chart_plan") or [])
    if planned:
        # The plan was decided from the data that produced the prose, so there is
        # nothing for a model to choose between. Falling back to the picker only
        # when there is no plan keeps every non-performance question working
        # exactly as it did.
        log_event(logger, "charts_from_plan", node="analyst_chart_picker",
                  route=state["route"], chart_count=len(planned))
        return {"charts": planned}
    charts = pick_charts(
        state["question"],
        list(state.get("evidence", [])),
        chart_focus(state),
    )
    log_event(
        logger,
        "analyst_charts_done",
        node="analyst_chart_picker",
        route=state["route"],
        chart_count=len(charts),
    )
    return {"charts": charts}


def chart_focus(state: AnalystState) -> ChartFocus:
    """What the written answer led with, so the chart agrees with the prose.

    Built from the answer RECORD rather than the plan: the plan is what the turn
    intended to say and the record is what it actually said, and only the second
    of those is what the reader is looking at next to the chart.
    """
    record = state.get("answer_record") or {}
    contract = state.get("contract")
    claims = record.get("claims") or []
    lead_ids = set(claims[0].get("fact_ids", ())) if claims else set()
    subject = tuple(
        pair
        for fact in record.get("facts") or []
        if fact.get("id") in lead_ids
        for pair in (tuple(p) for p in fact.get("dimensions", ()))
    )
    cited = {
        str(fact.get("source_id", ""))
        for fact in record.get("facts") or []
        if fact.get("id") in lead_ids
    }
    return ChartFocus(
        evidence_ids=tuple(sorted(i for i in cited if i)),
        subject=subject,
        requirements=tuple(contract.keys()) if contract else (),
    )


def build_analyst_subgraph():
    """Compile the analyst subgraph (no checkpointer — runs inside the main graph)."""
    graph = StateGraph(AnalystState)

    graph.add_node("planner_node", planner_node)
    graph.add_node("schema_identifier_node", schema_identifier_node)
    graph.add_node("peer_solver_node", peer_solver_node)
    graph.add_node("generic_solver_node", generic_solver_node)
    graph.add_node("join_node", join_node)
    graph.add_node("positioning_node", positioning_node)
    graph.add_node("writer_node", writer_node)
    graph.add_node("verify_node", verify_node)
    graph.add_node("chart_picker_node", chart_picker_node)

    graph.add_edge(START, "planner_node")
    graph.add_edge("planner_node", "schema_identifier_node")
    graph.add_conditional_edges(
        "schema_identifier_node",
        dispatch,
        ["peer_solver_node", "generic_solver_node"],
    )
    graph.add_edge("peer_solver_node", "join_node")
    graph.add_edge("generic_solver_node", "join_node")
    graph.add_edge("join_node", "positioning_node")
    graph.add_edge("positioning_node", "writer_node")
    graph.add_edge("writer_node", "verify_node")
    graph.add_edge("verify_node", "chart_picker_node")
    graph.add_edge("chart_picker_node", END)

    return graph.compile()


class AnalystSubGraph:
    """Lazily-compiled singleton wrapper, mirroring the other subgraph classes."""

    _compiled = None

    @property
    def AnalystAgent(self):
        if AnalystSubGraph._compiled is None:
            AnalystSubGraph._compiled = build_analyst_subgraph()
        return AnalystSubGraph._compiled
