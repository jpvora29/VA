"""Survey chart node — recommends chart_type, x/y/series for the SQL output."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import dspy

from core.agents.common.chart_spec import (
    ChartTypeSelectSignature,
    generate_chart_two_phase,
    stamp_intent,
)
from core.schemas.survey import SurveyChartSignature
from core.skills.loader import get_skill_loader
from logger import get_logger

logger = get_logger(__name__)


class SurveyChartNode(dspy.Module):
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(
        self,
        chart_creation_rules: str,
        detail_provider: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        super().__init__()
        self.chart_creation_rules = chart_creation_rules
        self.type_predictor = dspy.ChainOfThought(ChartTypeSelectSignature)
        self.predictor = dspy.ChainOfThought(SurveyChartSignature)
        self.detail_provider = detail_provider or get_skill_loader().chart_detail

    def forward(self, user_query: str, sql_output: List[Dict[str, Any]]):
        # Two phases: pick the chart_type from the selection tree, then build the
        # spec with only that type's detail appended (see chart_spec).
        spec = generate_chart_two_phase(
            base_rules=self.chart_creation_rules,
            user_query=user_query,
            sql_output=sql_output,
            type_predictor=self.type_predictor,
            spec_predictor=self.predictor,
            detail_provider=self.detail_provider,
        )
        logger.debug("Survey chart spec: %s", spec)
        return stamp_intent(spec, user_query)
