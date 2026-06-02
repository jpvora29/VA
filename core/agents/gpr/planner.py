"""GPR planner — produces a structured analytical plan from the user query."""
from __future__ import annotations

from typing import Any, Dict, List

import dspy
from pydantic import BaseModel

from core.schemas.gpr import GPRPlannerNodeSignature


class GPRPlannerNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(
        self,
        gpr_schema: List[Dict[str, Any]],
        peers_schema: List[Dict[str, Any]],
        definitions: Dict[str, str],
        rules: str,
        demos: List[dspy.Example] = None,
    ) -> None:
        super().__init__()
        self.gpr_schema = gpr_schema
        self.peers_schema = peers_schema
        self.definitions = definitions
        self.rules = rules
        self.demos = demos
        self.planner = dspy.ChainOfThought(GPRPlannerNodeSignature)

    def forward(self, user_query: str, valid_year_quarter: List[str]):
        # Combine context into a single training/inference context
        context = (
            f"GPR Schema:\n{self.gpr_schema}\n\n"
            f"Peers Schema:\n{self.peers_schema}\n\n"
            f"Definitions:\n{self.definitions}\n\n"
            f"Rules:\n{self.rules}\n"
            f"Few Shot Examples:\b{self.demos}\n"
        )

        result = self.planner(
            context=context,
            valid_year_quarter=valid_year_quarter,
            user_query=user_query,
            # valid_values=valid_values,
            # carrier_schema=self.carrier_schema,
            # peer_schema=self.peer_schema,
            # definitions=self.definitions,
            # rules=self.rules,
            # demos=self.demos,
        )

        if isinstance(result.plan, BaseModel):
            # return dict(result.plan)
            return result.plan.model_dump_json(indent=2)

        return result.plan
