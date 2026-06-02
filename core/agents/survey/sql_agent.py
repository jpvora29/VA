"""Survey SQL agent — turns the planner output into a SQLite query."""
from __future__ import annotations

from typing import Any, Dict, List

import dspy

from core.schemas.survey import SQLAgentNodeSignature


class SQLAgentNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(
        self,
        carrier_schema: List[Dict[str, Any]],
        peer_schema: List[Dict[str, Any]],
        rules: str,
        few_shot: List[dspy.Example] = None,
    ) -> None:
        super().__init__()
        self.carrier_schema = carrier_schema
        self.peer_schema = peer_schema
        self.rules = rules
        self.few_shot = few_shot
        self.sql_query: str = dspy.ChainOfThought(SQLAgentNodeSignature)

    def forward(self, user_query: str, query_plan: str):
        # Combine context into a single training/inference context
        context = (
            f"Carriers Schema:\n{self.carrier_schema}\n\n"
            f"Peers Schema:\n{self.peer_schema}\n\n"
            f"Rules:\n{self.rules}\n\n"
            f"Few Shot Examples:\n{self.few_shot}\n"
        )

        result = self.sql_query(
            context=context,
            user_query=user_query,
            query_plan=query_plan,
        )

        return result.sql_query
