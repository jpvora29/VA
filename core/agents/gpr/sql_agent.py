"""GPR SQL agent — turns the planner output into a SQLite query."""
from __future__ import annotations

from typing import Any, Dict, List

import dspy

from core.schemas.gpr import GPRSQLAgentNodeSignature


class GPRSQLAgentNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(
        self,
        gpr_schema: List[Dict[str, Any]],
        peer_schema: List[Dict[str, Any]],
        rules: str,
        few_shot: List[dspy.Example] = None,
    ) -> None:
        super().__init__()
        self.gpr_schema = gpr_schema
        self.peer_schema = peer_schema
        self.rules = rules
        self.few_shot = few_shot
        self.predictor = dspy.ChainOfThought(GPRSQLAgentNodeSignature)

    def forward(self, user_query: str, query_plan: str, valid_year_quarter: List[str]):
        # Combine context into a single training/inference context
        context = (
            f"GPR Schema:\n{self.gpr_schema}\n\n"
            f"Peers Schema:\n{self.peer_schema}\n\n"
            f"Rules:\n{self.rules}\n\n"
            f"Few Shot Examples:\n{self.few_shot}\n"
        )

        result = self.predictor(
            context=context,
            valid_year_quarter=valid_year_quarter,
            user_query=user_query,
            query_plan=query_plan,
        )

        # if isinstance(result.query, BaseModel):
        #     return dict(result.plan)

        return result.sql_query
