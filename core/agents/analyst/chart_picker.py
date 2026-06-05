"""Chart-picker for the analyst subgraph.

The analyst gathers evidence as several executed queries across analytical lenses
(peer benchmark, trend, segment mix, …). Unlike the deterministic rails — which
have exactly one SQL result to chart — the analyst has MANY candidate datasets.

`pick_charts` scores those candidates for "chartability", takes the best 2–3, and
asks the SAME chart node the deterministic path uses (`GPRChartNode` /
`SurveyChartNode`, driven by the shared chart skill catalog) to produce a
`ChartOutput` spec for each. It returns a list of `{title, rows, chart_data}`
dicts the UI renders one chart per entry.

Best-effort by construction: any failure (bad rows, LLM error) is logged and
skipped, and the function returns `[]` rather than raising, so charting can never
crash an analyst turn.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from core.agents.common.chart_spec import normalize_chart_spec
from core.agents.gpr.chart import GPRChartNode
from core.agents.survey.chart import SurveyChartNode
from core.observability import log_event
from core.rules.gpr_chart import GPRChartRules
from core.rules.survey_chart import SurveyChartRules
from core.schemas.analyst_subgraph import Evidence
from core.skills.loader import get_skill_loader
from logger import get_logger

logger = get_logger(__name__)

# How many charts an analyst answer may carry, and how many rows we hand the LLM
# when asking for a spec (the full rows are still used to render).
MAX_CHARTS = 3
_LLM_ROW_CAP = 60

# Column-name hints that make a dataset more worth charting (time series, peer
# comparison, segment/product mix, growth/rate movement).
_DIMENSION_BOOSTS = re.compile(
    r"(?i)\b(year|quarter|month|date|period|peer|segment|product|cover|region|"
    r"country|carrier|section|practice|attribute|growth|share|appetite|rank)\b"
)


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    return list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []


def _is_number(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _chartability(rows: List[Dict[str, Any]]) -> float:
    """Heuristic score for how worth-charting a result set is (0 = skip)."""
    if not isinstance(rows, list) or len(rows) < 2:
        return 0.0
    cols = _columns(rows)
    if len(cols) < 2:
        return 0.0
    sample = rows[: min(len(rows), 10)]
    numeric = [c for c in cols if any(_is_number(r.get(c)) for r in sample)]
    # Need at least one numeric measure and a second column to act as the axis
    # dimension. A categorical is NOT required — a pure (Year, Premium) trend or a
    # two-measure scatter is perfectly chartable.
    if not numeric or len(cols) < 2:
        return 0.0
    score = min(len(rows), 24) / 24.0  # more rows → more to show (capped)
    score += 0.5 if len(numeric) >= 2 else 0.0  # combo/scatter potential
    score += 0.4 * len(_DIMENSION_BOOSTS.findall(" ".join(cols)))
    return score


def _dedup_key(ev: Evidence) -> str:
    return re.sub(r"\s+", " ", (ev.get("sql") or "")).strip().lower()


def _chart_node(flow: str, rules: str):
    return SurveyChartNode(rules) if flow == "survey" else GPRChartNode(rules)


def _chart_rules(flow: str, question: str) -> str:
    skill_rules = get_skill_loader().chart(flow, question)
    if skill_rules:
        return skill_rules
    return (
        SurveyChartRules.chart_creation_rules
        if flow == "survey"
        else GPRChartRules.chart_creation_rules
    )


def pick_charts(question: str, evidence: List[Evidence]) -> List[Dict[str, Any]]:
    """Select and build up to `MAX_CHARTS` charts from gathered analyst evidence."""
    if not evidence:
        return []

    # Rank distinct (by SQL) evidence sets by chartability, best first.
    best_by_sql: Dict[str, tuple[float, Evidence]] = {}
    for ev in evidence:
        rows = ev.get("rows") or []
        score = _chartability(rows)
        if score <= 0:
            continue
        key = _dedup_key(ev)
        if key not in best_by_sql or score > best_by_sql[key][0]:
            best_by_sql[key] = (score, ev)

    ranked = sorted(best_by_sql.values(), key=lambda t: t[0], reverse=True)
    if not ranked:
        return []

    # Cache one chart node per flow (rules are flow-wide for the turn).
    nodes: Dict[str, Any] = {}
    charts: List[Dict[str, Any]] = []

    for _score, ev in ranked:
        if len(charts) >= MAX_CHARTS:
            break
        flow = ev.get("flow") or "gpr"
        rows = ev.get("rows") or []
        try:
            if flow not in nodes:
                nodes[flow] = _chart_node(flow, _chart_rules(flow, question))
            # Always coerce to a plain dict: dspy can hand back a ChartOutput
            # MODEL (or a list of specs), which the old `isinstance(dict)` check
            # silently skipped — so the analyst produced charts that never
            # rendered. normalize_chart_spec flattens model/list/dict to one dict.
            chart_data = normalize_chart_spec(
                nodes[flow](user_query=question, sql_output=rows[:_LLM_ROW_CAP])
            )
            # Use the SAME falsy-aware normalization the renderer uses
            # (`chart_functions._sanitize_spec`): an empty string / None /
            # whitespace chart_type is "none". A bare `== "none"` check let those
            # through, so the chart was appended here but then rejected downstream
            # as "data is scalar" — surfacing a scalar flag for a real dataset.
            if str(chart_data.get("chart_type") or "none").strip().lower() == "none":
                continue
            charts.append(
                {
                    "title": chart_data.get("title") or ev.get("lens", "") or "Analysis",
                    "rows": rows,
                    "chart_data": chart_data,
                }
            )
        except Exception as exc:  # noqa: BLE001 - never crash the turn over a chart
            log_event(
                logger,
                "analyst_chart_picker_error",
                logging.WARNING,
                node="analyst_chart_picker",
                flow=flow,
                lens=ev.get("lens", ""),
                error=str(exc),
            )

    log_event(
        logger,
        "analyst_charts_picked",
        node="analyst_chart_picker",
        candidates=len(ranked),
        rendered=len(charts),
    )
    return charts
