"""Survey chart node — recommends chart_type, x/y/series for the SQL output."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.agents.common.chart_spec import (
    ChartTypeSelectSignature,
    generate_chart_spec,
    stamp_intent,
)
from core.llm import Predictor
from core.schemas.survey import SurveyChartSignature
from core.skills.loader import get_skill_loader
from logger import get_logger

logger = get_logger(__name__)


class SurveyChartNode:
    # def __init__(self, carrier_schema: str, peer_schema: str, definitions: str, rules: str):

    def __init__(
        self,
        chart_creation_rules: str,
        detail_provider: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.chart_creation_rules = chart_creation_rules
        # Both phases reason: picking the type walks a selection tree, and the
        # spec has to map real columns onto x/y/series.
        self.type_predictor = Predictor(
            ChartTypeSelectSignature, tier="balanced", reasoning=True,
            label="survey_chart_type", node="survey_chart",
        )
        self.predictor = Predictor(
            SurveyChartSignature, tier="balanced", reasoning=True,
            label="survey_chart_spec", node="survey_chart",
        )
        self.detail_provider = detail_provider or get_skill_loader().chart_detail

    def __call__(self, user_query: str, sql_output: List[Dict[str, Any]]):
        # Chartwright designs the chart from per-type tool schemas; the older
        # two-phase predictors stay wired as its fallback (see chart_spec).
        spec = generate_chart_spec(
            base_rules=self.chart_creation_rules,
            user_query=user_query,
            sql_output=sql_output,
            type_predictor=self.type_predictor,
            spec_predictor=self.predictor,
            detail_provider=self.detail_provider,
            node="survey_chart",
        )
        logger.debug("Survey chart spec: %s", spec)
        return stamp_intent(spec, user_query)
