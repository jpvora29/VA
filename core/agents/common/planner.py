"""Unified analytical planner — one flow-parameterized dspy module for GPR + Survey.

Replaces the near-duplicate `GPRPlannerNode` and survey `PlannerNode`. Domain
differences come from the data passed in (schema slice, definitions, valid_values,
rules), not from separate classes. Inputs are typed `dspy.InputField`s via
`PlannerSignature` instead of one flattened `context` blob, and the upstream
`RoutingContext` is threaded in so the planner stops re-deriving timeframe and correctly
carries inherited follow-up filters.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import dspy
from pydantic import BaseModel

from core.schemas.analytical import PlannerSignature
from core.schemas.routing import RoutingContext


class BasePlannerNode(dspy.Module):
    """Flow-parameterized analytical planner.

    Args:
        flow: "gpr" or "survey" — informational; behaviour is driven by the data.
        schema_tables: Schema for this flow as {table_name: [column metadata]}.
        definitions: Business definitions for those columns.
        valid_values: Valid column values for grounding filters.
        rules: Flow-specific planning rules / worked examples (skills or `core.rules.*`).
        demos: Optional dspy few-shot examples, passed straight to the predictor.
    """

    def __init__(
        self,
        flow: str,
        schema_tables: Dict[str, Any],
        definitions: Dict[str, str],
        valid_values: Dict[str, Any],
        rules: str,
        demos: Optional[List[dspy.Example]] = None,
    ) -> None:
        super().__init__()
        self.flow = flow
        self.schema_tables = schema_tables
        self.definitions = definitions
        self.valid_values = valid_values
        self.rules = rules
        self.planner = dspy.ChainOfThought(PlannerSignature)
        if demos:
            self.planner.demos = demos

    def forward(
        self,
        user_query: str,
        routing_context: Optional[RoutingContext] = None,
        valid_year_quarter: Optional[List[str]] = None,
    ) -> str:
        # dspy's Optional handling is inconsistent across adapters; pass a concrete
        # RoutingContext / list rather than None.
        if routing_context is None:
            routing_context = RoutingContext(
                table_family="fallback", intent_type="new_question"
            )

        result = self.planner(
            schema=self.schema_tables,
            definitions=self.definitions,
            valid_values=self.valid_values,
            valid_year_quarter=valid_year_quarter or [],
            routing_context=routing_context,
            rules=self.rules,
            user_query=user_query,
        )

        if isinstance(result.plan, BaseModel):
            return result.plan.model_dump_json(indent=2)
        return result.plan
