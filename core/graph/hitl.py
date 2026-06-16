"""HITL clarification — workflow-path interrupt nodes.

Two small nodes sit between the context filler and the rephraser:

  context_filler -> clarify_decide -> clarify_gate -> rephraser_agent

`clarify_decide` assembles this turn's clarifying QUESTIONS (plural) and writes
them onto `clarify_questions` (persisted by the checkpointer). Questions come
from an ordered sequence of `ClarifyQuestionSource`s, deterministic first
(extend the list to add a source — OCP, no new branch):

  1. **Missing mandatory filter** (new, deterministic) — Carrier + Country are
     required; when one is still absent after history inheritance + fuzzy
     resolution, ask for it. Timeframe is excluded (it auto-defaults).
  2. **Unresolved contract terms** — entity mentions the query contract could
     not match to any stored value ("Did you mean…?" MCQs with fuzzy-suggested
     options). Zero LLM cost; these are the turns that would otherwise become
     wrong filters and false "no data" answers.
  3. **The conservative LLM ambiguity classifier** (existing) — skipped when
     its question merely repeats an entity already covered by (1)/(2).

`clarify_gate` interrupts ONCE with the whole list; the UI collects an answer
per question and resumes with `{question_id: answer}`. On resume the gate folds
every answer into the current query and, for entity questions, writes the
chosen value straight into `routing_context.resolved_filters` — so the
rephraser and SQL agents act on the disambiguated, canonically-filtered turn.

Splitting decide (LLM, runs once) from gate (interrupt, re-runs on resume) keeps
the classifier from re-firing on resume — the standard "deterministic code
before interrupt" pattern. The decision defaults to NOT asking; see
`core.schemas.hitl.ClarifyDecisionSignature`. Pitch builder does not wire these
nodes, so report generation never blocks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Protocol, Sequence

import dspy
from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.types import interrupt
from pydantic import BaseModel

from core.agents.common.mandatory_filters import MandatoryFilterGate
from core.data.valid_values import GetValidData
from core.observability import log_event
from core.schemas.hitl import ClarifyDecision, ClarifyDecisionSignature
from logger import get_logger

if TYPE_CHECKING:
    from core.state.agent_state import AgentState

logger = get_logger(__name__)


class ClarifyDecider(dspy.Module):
    """Conservative ambiguity classifier (ChainOfThought over the signature)."""

    def __init__(self) -> None:
        super().__init__()
        self.predictor = dspy.ChainOfThought(ClarifyDecisionSignature)

    def forward(self, current_user_query, routing_context, valid_values) -> ClarifyDecision:
        result = self.predictor(
            current_user_query=current_user_query,
            routing_context=routing_context,
            valid_values=valid_values,
        )
        decision = result.clarify_decision
        if isinstance(decision, ClarifyDecision):
            return decision
        if isinstance(decision, dict):
            return ClarifyDecision(**decision)
        # Any odd shape: fail safe to NOT asking.
        return ClarifyDecision(needs_clarification=False, reason="unparsable decision")


_CLARIFY_DECIDER = ClarifyDecider()


def _valid_values_snapshot() -> dict:
    """Compact valid-values bundle for grounding the ambiguity check + options."""
    survey = GetValidData.valid_values
    gpr = GetValidData.valid_values_gpr
    return {
        "carriers": survey.get("Carrier", []),
        "carrier_groups": gpr.get("Carrier_Group", []),
        "countries_gpr": gpr.get("Country", []),
        "products": gpr.get("Product_Line", []),
        "segments": gpr.get("Client_Segment", []),
        "survey_practices": survey.get("SurveyPractice", []),
    }


# Caps: a clarify card with too many questions is its own UX failure.
_MAX_ENTITY_QUESTIONS = 2
_MAX_QUESTIONS = 3

# Suggestion search for an unresolved term. The contract's resolver already
# missed at its strict cutoff, so the "did you mean" lookup casts wider.
_SUGGESTION_CUTOFF = 55
_SUGGESTION_TOP_N = 4


def _unresolved_entity_questions(routing_context: Any) -> List[Dict]:
    """Deterministic "Did you mean…?" MCQs from the contract's unresolved terms.

    One question per distinct (kind, term), capped, each carrying the column/
    flow/term meta the gate needs to write the answer back into
    `resolved_filters`. A term with no fuzzy suggestions at the wider cutoff is
    skipped — a card without grounded options is worse than letting the
    zero-row guard catch it downstream.
    """
    from core.mcp.tools import match_column_values  # lazy: avoid LLM-layer import

    unresolved = getattr(routing_context, "unresolved_terms", None) or []
    questions: List[Dict] = []
    seen: set = set()
    for item in unresolved:
        if len(questions) >= _MAX_ENTITY_QUESTIONS:
            break
        kind = getattr(item, "kind", "") or "entity"
        term = (getattr(item, "term", "") or "").strip()
        column = getattr(item, "column", "")
        flow = getattr(item, "flow", "")
        key = (kind, term.lower())
        if not term or not column or key in seen:
            continue
        seen.add(key)
        try:
            suggestions = match_column_values(
                flow, column, term,
                top_n=_SUGGESTION_TOP_N, score_cutoff=_SUGGESTION_CUTOFF,
            )
        except Exception as exc:  # noqa: BLE001 - suggestions are best-effort
            log_event(
                logger,
                "clarify_suggestion_error",
                logging.WARNING,
                node="clarify_decide",
                term=term,
                error=str(exc),
            )
            continue
        if not suggestions:
            continue
        questions.append(
            {
                "id": f"entity:{kind}:{term.lower()}",
                "kind": "unresolved_entity",
                "entity_kind": kind,
                "header": kind.title()[:12],
                "question": (
                    f"I couldn't find {kind} '{term}' in the data. "
                    f"Did you mean one of these?"
                ),
                "options": [{"label": s, "description": ""} for s in suggestions],
                "allow_free_text": True,
                "column": column,
                "flow": flow,
                "term": term,
            }
        )
    return questions


# ── clarify question sources (one protocol, deterministic-first ordering) ─────

# A mandatory filter the user simply omitted has no term to disambiguate, so we
# ask for it directly. Options come from the column's valid values when the list
# is short enough to be a genuine choice; otherwise the card is free-text only.
_MANDATORY_OPTION_CAP = 8
_MANDATORY_PROMPTS = {
    "carrier": "Which carrier would you like me to analyze?",
    "country": "Which market/country should I focus on?",
}


def _valid_values_for(flow: str, column: str) -> List[str]:
    """Valid stored values for a (flow, column), for seeding clarify options."""
    table = {
        "gpr": GetValidData.valid_values_gpr,
        "survey": GetValidData.valid_values,
        "gimmi": GetValidData.gimmi_valid_values,
    }.get(flow, {})
    return [str(v) for v in (table.get(column) or [])]


@dataclass
class ClarifyContext:
    """Inputs each source reads, plus the questions gathered by earlier sources
    (so a later source can dedup against, and respect the overall cap)."""

    query: str
    routing_context: Any
    valid_values: dict
    existing: List[Dict] = field(default_factory=list)


class ClarifyQuestionSource(Protocol):
    """Produces zero or more clarify-question dicts for the turn."""

    def gather(self, ctx: ClarifyContext) -> List[Dict]: ...


class MandatoryFilterSource:
    """Source 1: a required filter (Carrier/Country) the user never supplied.

    Delegates the missing-decision to `MandatoryFilterGate` (SRP) and turns each
    `FilterRequirement` into a grounded MCQ. The value loader is injected so tests
    can supply options without the real valid-values cache.
    """

    def __init__(self, *, gate: MandatoryFilterGate | None = None, value_loader=_valid_values_for) -> None:
        self._gate = gate or MandatoryFilterGate()
        self._load_values = value_loader

    def gather(self, ctx: ClarifyContext) -> List[Dict]:
        questions: List[Dict] = []
        for req in self._gate.missing_mandatory_filters(ctx.routing_context):
            column = req.columns[0] if req.columns else ""
            values = self._load_values(req.flow, column) if column else []
            options = (
                [{"label": v, "description": ""} for v in values]
                if 0 < len(values) <= _MANDATORY_OPTION_CAP
                else []
            )
            questions.append(
                {
                    "id": f"mandatory:{req.role}",
                    "kind": "mandatory_filter",
                    "entity_kind": req.role,
                    "header": req.label[:12],
                    "question": _MANDATORY_PROMPTS.get(
                        req.role, f"Which {req.role} should I use?"
                    ),
                    "options": options,
                    "allow_free_text": True,
                    "column": column,
                    "flow": req.flow,
                    "term": "",
                }
            )
        return questions


class UnresolvedEntitySource:
    """Source 2: entity mentions the contract could not match ("did you mean…?")."""

    def gather(self, ctx: ClarifyContext) -> List[Dict]:
        return _unresolved_entity_questions(ctx.routing_context)


class AmbiguityClassifierSource:
    """Source 3: the conservative LLM ambiguity classifier (fallback).

    Reads the module-level `_CLARIFY_DECIDER` at call time so tests can monkeypatch
    it. Skipped when its question merely repeats an entity an earlier source
    already covers, or when it cannot supply ≥2 grounded options.
    """

    def gather(self, ctx: ClarifyContext) -> List[Dict]:
        if len(ctx.existing) >= _MAX_QUESTIONS:
            return []
        try:
            decision = _CLARIFY_DECIDER(
                current_user_query=ctx.query,
                routing_context=ctx.routing_context,
                valid_values=ctx.valid_values,
            )
        except Exception as exc:  # noqa: BLE001 - clarification is best-effort; never break the turn
            log_event(logger, "clarify_decide_error", logging.ERROR, node="clarify_decide", error=str(exc))
            return []

        if not (decision.needs_clarification and decision.question is not None):
            return []
        llm_q = decision.question
        # A clarify card with fewer than 2 grounded options is a vague, unhelpful
        # ask (the model ignored the [WHEN YOU DO ASK] rule).
        if len(llm_q.options) < 2:
            log_event(logger, "clarify_skipped_no_options", node="clarify_decide", header=llm_q.header)
            return []
        # If it merely re-asks an entity an earlier source already covers, the
        # grounded card wins.
        covered_terms = {
            str(q.get("term", "")).lower() for q in ctx.existing if q.get("term")
        }
        if any(t and t in llm_q.question.lower() for t in covered_terms):
            return []
        payload = llm_q.model_dump()
        payload.setdefault("id", "llm:ambiguity")
        payload.setdefault("kind", "ambiguity")
        return [payload]


# Production ordering: deterministic mandatory + entity sources first, LLM last.
_DEFAULT_CLARIFY_SOURCES: Sequence[ClarifyQuestionSource] = (
    MandatoryFilterSource(),
    UnresolvedEntitySource(),
    AmbiguityClassifierSource(),
)


def clarify_decide(
    state: "AgentState",
    *,
    sources: Sequence[ClarifyQuestionSource] = _DEFAULT_CLARIFY_SOURCES,
) -> "AgentState":
    """Assemble this turn's clarify questions. Default: ask nothing.

    Iterates the injected `sources` in order (mandatory filter -> unresolved
    entity -> LLM ambiguity), accumulating questions up to `_MAX_QUESTIONS`. The
    interrupt must live in the checkpointed main graph to be resumable, so this
    single gate — not a nested-agent middleware — is the sole clarifier across
    both the lookup and analytical routes.
    """
    routing_context = state.get("routing_context")
    # Out-of-scope turns never clarify — they go straight to fallback.
    if routing_context is None or getattr(routing_context, "table_family", None) == "fallback":
        return {"clarify_questions": None}

    ctx = ClarifyContext(
        query=state["messages"][-1].content,
        routing_context=routing_context,
        valid_values=_valid_values_snapshot(),
    )

    questions: List[Dict] = []
    for source in sources:
        if len(questions) >= _MAX_QUESTIONS:
            break
        ctx.existing = questions
        for question in source.gather(ctx):
            questions.append(question)
            if len(questions) >= _MAX_QUESTIONS:
                break

    if not questions:
        return {"clarify_questions": None}

    log_event(
        logger,
        "clarify_needed",
        node="clarify_decide",
        count=len(questions),
        ids=[q.get("id") for q in questions],
    )
    return {"clarify_questions": questions[:_MAX_QUESTIONS]}


def _normalize_answers(answers: Any, questions: List[Dict]) -> Dict[str, str]:
    """Map a resume value to {question_id: answer}.

    A dict passes through (the multi-question UI); a bare string — legacy UI,
    tests, API callers — answers the FIRST question, preserving the old
    single-question contract.
    """
    if isinstance(answers, dict):
        return {str(k): str(v).strip() for k, v in answers.items() if str(v).strip()}
    text = str(answers).strip()
    if text and questions:
        return {str(questions[0].get("id") or "q0"): text}
    return {}


def clarify_gate(state: "AgentState") -> "AgentState":
    """Pause for the user's answers when clarify questions are pending.

    No questions -> pure pass-through. Otherwise ONE `interrupt()` carries the
    whole list; the UI resumes with `{question_id: answer}`. Every answer is
    folded into the current query; entity answers are also written into
    `routing_context.resolved_filters` so the contract — and everything that
    reads it — carries the user's choice as an exact filter value.
    """
    pending = state.get("clarify_questions")
    if not pending:
        return {}
    questions: List[Dict] = list(pending)

    # Pauses here until the UI resumes the thread with Command(resume=<answers>).
    raw = interrupt({"kind": "clarify", "questions": questions})
    answers = _normalize_answers(raw, questions)

    routing_context = state.get("routing_context")
    notes: List[str] = []
    for q in questions:
        answer = answers.get(str(q.get("id")))
        if not answer:
            continue
        column = q.get("column")
        # Both the "did you mean…?" disambiguation and the mandatory-filter ask
        # carry a target column — the answer is an exact contract filter value.
        if column:
            if q.get("kind") == "unresolved_entity":
                notes.append(
                    f"{q.get('entity_kind', 'entity')} '{q.get('term')}' means '{answer}'"
                )
            else:
                notes.append(f"{q.get('entity_kind', 'filter').title()}: {answer}")
            if routing_context is not None:
                filters = dict(getattr(routing_context, "resolved_filters", {}) or {})
                bucket = list(filters.get(column, []))
                if answer not in bucket:
                    bucket.append(answer)
                filters[column] = bucket
                routing_context.resolved_filters = filters
                # Keep the structured contract's filter mirror in step with the
                # live map a clarification just wrote into.
                intent = getattr(routing_context, "query_intent", None)
                if intent is not None:
                    intent.filters = filters
        else:
            notes.append(f"{q.get('question', 'clarification')} -> {answer}")

    last = state["messages"][-1]
    original = last.content
    clarification = "; ".join(notes) if notes else str(raw)
    augmented = f"{original} (User clarification: {clarification})"
    log_event(
        logger,
        "clarify_resumed",
        node="clarify_gate",
        answered=len(answers),
        asked=len(questions),
    )
    updates: "AgentState" = {
        "messages": [RemoveMessage(id=last.id), HumanMessage(content=augmented)],
        "clarification": clarification,
        "clarify_questions": None,
    }
    if routing_context is not None:
        updates["routing_context"] = routing_context
    return updates


def hitl_clarify(state: "AgentState") -> "AgentState":  # pragma: no cover - back-compat shim
    """Deprecated single-node entry point. Use clarify_decide + clarify_gate."""
    decided = clarify_decide(state)
    merged = dict(state)
    merged.update(decided or {})
    return clarify_gate(merged)
