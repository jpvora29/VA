"""Unified analytical planner — one flow-parameterized node for GPR + Survey.

Replaces the near-duplicate `GPRPlannerNode` and survey `PlannerNode`. Domain
differences come from the data passed in (schema slice, definitions, valid_values,
rules), not from separate classes. Inputs are typed `InputField`s via
`PlannerSignature` instead of one flattened `context` blob, and the upstream
`RoutingContext` is threaded in so the planner stops re-deriving timeframe and correctly
carries inherited follow-up filters.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from core.analytics.timeframe import (
    resolve_default_timeframe,
    timeframe_resolution_enabled,
)
from core.context.gate import gate_enabled, gated_valid_values
from core.llm import Example, Predictor
from core.schemas.analytical import PlannerSignature
from core.schemas.routing import RoutingContext


class BasePlannerNode:
    """Flow-parameterized analytical planner.

    Args:
        flow: "gpr" or "survey" — informational; behaviour is driven by the data.
        schema_tables: Schema for this flow as {table_name: [column metadata]}.
        definitions: Business definitions for those columns.
        valid_values: Valid column values for grounding filters.
        rules: Flow-specific planning rules / worked examples (skills or `core.rules.*`).
        demos: Optional few-shot examples, passed straight to the predictor.
    """

    def __init__(
        self,
        flow: str,
        schema_tables: Dict[str, Any],
        definitions: Dict[str, str],
        valid_values: Dict[str, Any],
        rules: str,
        demos: Optional[List[Example]] = None,
    ) -> None:
        self.flow = flow
        self.schema_tables = schema_tables
        self.definitions = definitions
        self.valid_values = valid_values
        self.rules = rules
        # Reason tier: planning is the hardest reasoning on the analytical path.
        self.planner = Predictor(
            PlannerSignature, tier="reason", reasoning=True,
            label=f"{flow}_planner_node", node=flow,
        )
        if demos:
            self.planner = self.planner.with_examples(demos)

    def __call__(
        self,
        user_query: str,
        routing_context: Optional[RoutingContext] = None,
        valid_year_quarter: Optional[List[str]] = None,
    ) -> str:
        # Pass a concrete RoutingContext / list rather than None, so the prompt
        # shows real defaults instead of the renderer's "(not provided)".
        if routing_context is None:
            routing_context = RoutingContext(
                table_family="fallback", intent_type="new_question"
            )

        # Cardinality gate (decisions #2): the planner's worst prompt-bloat source
        # is the full valid_values dict (e.g. GPR Carrier_Group ~550 values). When
        # enabled, replace high-card columns with only the query-resolved subset.
        # Default off -> identical to the legacy full-dict behavior.
        valid_values = self.valid_values
        if gate_enabled():
            try:
                valid_values = gated_valid_values(
                    self.flow, user_query, full_values=self.valid_values
                )
            except Exception:  # noqa: BLE001 - never let gating break planning
                valid_values = self.valid_values

        result = self.planner(
            table_schema=self.schema_tables,
            definitions=self.definitions,
            valid_values=valid_values,
            valid_year_quarter=valid_year_quarter or [],
            routing_context=routing_context,
            rules=self.rules,
            user_query=user_query,
        )

        plan = result.plan
        # Deterministic timeframe backstop (Phase 1): when the plan leaves the
        # timeframe empty and the query carries no time reference, fill the latest
        # available year instead of letting an unfiltered all-years aggregate
        # slip through. Only fills a BLANK timeframe — explicit/relative choices
        # are never overridden. Flag-gated; default off = identical to today.
        if timeframe_resolution_enabled() and isinstance(plan, BaseModel):
            if not (getattr(plan, "timeframe", "") or "").strip():
                resolved = resolve_default_timeframe(
                    valid_year_quarter or [],
                    user_query,
                    timeframe_hint=getattr(routing_context, "timeframe_hint", "") or "",
                )
                if resolved:
                    try:
                        plan.timeframe = resolved
                    except Exception:  # noqa: BLE001 - presentation backstop, never fatal
                        pass

        if isinstance(plan, BaseModel):
            return plan.model_dump_json(indent=2)
        return plan
