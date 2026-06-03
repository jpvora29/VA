"""GPR chart node — recommends chart_type, x/y/series for the SQL output."""
from __future__ import annotations

from typing import Any, Dict, List

import dspy
from pydantic import BaseModel

from core.schemas.gpr import GPRChartSignature
from logger import get_logger

logger = get_logger(__name__)


class GPRChartNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(self, chart_creation_rules: str) -> None:
        super().__init__()
        self.chart_creation_rules = chart_creation_rules
        self.predictor = dspy.ChainOfThought(GPRChartSignature)

    def forward(self, user_query: str, sql_output: List[Dict[str, Any]]):

        # Combine context into a single training/inference context

        result = self.predictor(
            chart_creation_rules=self.chart_creation_rules,
            user_query=user_query,
            sql_output=sql_output,
        )
        logger.debug("GPR chart reasoning: %s", result)

        if isinstance(result.chart_data, BaseModel):
            return dict(result.chart_data)

        return result.chart_data
