"""Survey chart node — recommends chart_type, x/y/series for the SQL output."""
from __future__ import annotations

from typing import Any, Dict, List

import dspy

from core.agents.common.chart_spec import normalize_chart_spec, stamp_intent
from core.schemas.survey import SurveyChartSignature
from logger import get_logger

logger = get_logger(__name__)


class SurveyChartNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(self, chart_creation_rules: str) -> None:
        super().__init__()
        self.chart_creation_rules = chart_creation_rules
        self.predictor = dspy.ChainOfThought(SurveyChartSignature)

    def forward(self, user_query: str, sql_output: List[Dict[str, Any]]):

        result = self.predictor(
            chart_creation_rules=self.chart_creation_rules,
            user_query=user_query,
            sql_output=sql_output,
        )
        logger.debug("Survey chart reasoning: %s", result)

        return stamp_intent(normalize_chart_spec(result.chart_data), user_query)
