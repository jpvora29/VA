"""The chart node — one per flow, from one class.

There were two of these: `core.agents.gpr.chart.GPRChartNode` and
`core.agents.survey.chart.SurveyChartNode`. They were the same forty lines twice,
down to a copy-paste in the GPR prompt that told it to "analyze the structure and
semantics of the survey data", and their two `Signature` classes were identical
apart from one word. Three call sites — the GPR subgraph, the survey subgraph and
the analyst's chart picker — then each re-implemented the same four steps around
them: look up the flow's chart skill, fall back to its rules class, log the
lookup, construct the node.

All of that is here now, once:

    chart_node_for(flow, question)  ->  ChartNode  ->  a chart spec dict

What actually differs between the flows is the RULES, which are data
(`core.rules.*_chart`, overridden per question by the skill catalog) rather than
code — so the flow is a lookup in `_FLOWS`, and adding a third flow is a row in
that table rather than a third copy of this file (OCP).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.agents.common.chart_spec import (
    ChartTypeSelectSignature,
    generate_chart_spec,
    stamp_intent,
)
from core.llm import InputField, OutputField, Predictor, Signature
from core.observability import log_event
from core.rules.gpr_chart import GPRChartRules
from core.rules.survey_chart import SurveyChartRules
from core.schemas.survey import ChartOutput
from core.skills.loader import get_skill_loader
from logger import get_logger

logger = get_logger(__name__)


class ChartSpecSignature(Signature):
    """
    [ROLE]
    You are an Expert Data Visualization Analyst working with insurance data —
    premium (GPR) and broker-perception (survey) results. Recommend the most
    suitable chart type and configuration to represent the user's intent, given
    the user query, the SQL output, and the chart creation rules.

    [OBJECTIVE]
    Analyze the structure and semantics of the result set (using the exact field
    names from the data) and determine the visual representation that most
    clearly communicates the trend, comparison or distribution asked about.

    [RULE]
    STRICTLY assign "x", "y", "series" in the Chart Data using ONLY column names
    present in "sql_output".
    """

    chart_creation_rules: str = InputField(
        desc="# Predefined guidelines or heuristics for choosing chart types, axis mapping, aggregation, and sorting."
    )
    user_query: str = InputField(desc="User's natural language question or query")
    sql_output: List[Dict[str, Any]] = InputField(
        desc="Structured SQL query result as a list of dictionaries, where each dict represents a row of data."
    )
    chart_data: ChartOutput = OutputField(
        desc="Structured chart data based on the chart creation rules"
    )


@dataclass(frozen=True)
class FlowCharting:
    """Everything that differs between one flow's charting and another's."""

    flow: str
    #: The telemetry node name. Kept per flow because the dashboards read it.
    node: str
    #: The rules used when no chart skill matches the question.
    default_rules: str


_FLOWS: Dict[str, FlowCharting] = {
    "gpr": FlowCharting("gpr", "gpr_chart", GPRChartRules.chart_creation_rules),
    "survey": FlowCharting("survey", "survey_chart", SurveyChartRules.chart_creation_rules),
}

#: An unrecognised flow charts as premium — the analyst's evidence carries a flow
#: label that is occasionally blank, and a missing label is not a reason to
#: withhold the chart.
_DEFAULT_FLOW = "gpr"


def flow_charting(flow: str) -> FlowCharting:
    return _FLOWS.get((flow or "").strip().lower(), _FLOWS[_DEFAULT_FLOW])


def chart_rules_for(flow: str, question: str) -> str:
    """This question's chart rules: the matching skill, else the flow's default.

    Logs the lookup, because whether a skill matched changes the prompt the model
    saw and is the first thing to check when a chart comes out wrong.
    """
    spec = flow_charting(flow)
    skill_rules = get_skill_loader().chart(spec.flow, question)
    log_event(
        logger, "skill_load", node=spec.node, flow=spec.flow, scope="chart",
        used_skills=bool(skill_rules),
    )
    return skill_rules or spec.default_rules


class ChartNode:
    """Designs one chart spec for one result set.

    Chartwright (`core.charts.agent`) does the designing; the two-phase
    predictors wired here are its fallback (see `chart_spec.generate_chart_spec`).
    Both predictors are constructed per node instance, which is why callers take
    one from `chart_node_for` and reuse it across a turn.
    """

    def __init__(
        self,
        flow: str,
        chart_creation_rules: str,
        detail_provider: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        spec = flow_charting(flow)
        self.flow = spec.flow
        self.node = spec.node
        self.chart_creation_rules = chart_creation_rules
        # Both phases reason: picking the type walks a selection tree, and the
        # spec has to map real columns onto x/y/series.
        self.type_predictor = Predictor(
            ChartTypeSelectSignature, tier="balanced", reasoning=True,
            label=f"{spec.flow}_chart_type", node=spec.node,
        )
        self.predictor = Predictor(
            ChartSpecSignature, tier="balanced", reasoning=True,
            label=f"{spec.flow}_chart_spec", node=spec.node,
        )
        # Phase-two per-type detail lookup (injected for tests; defaults to the
        # shared skill catalog).
        self.detail_provider = detail_provider or get_skill_loader().chart_detail

    def __call__(self, user_query: str, sql_output: List[Dict[str, Any]]) -> Dict[str, Any]:
        spec = generate_chart_spec(
            base_rules=self.chart_creation_rules,
            user_query=user_query,
            sql_output=sql_output,
            type_predictor=self.type_predictor,
            spec_predictor=self.predictor,
            detail_provider=self.detail_provider,
            node=self.node,
        )
        logger.debug("%s chart spec: %s", self.flow, spec)
        return stamp_intent(spec, user_query)


def chart_node_for(
    flow: str,
    question: str,
    detail_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> ChartNode:
    """A chart node for this flow, carrying the rules this question resolved to."""
    return ChartNode(flow, chart_rules_for(flow, question), detail_provider)
