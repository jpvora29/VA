"""Shared graph adapter: scope → evidence → grounded answer → persisted record."""
from __future__ import annotations

from core.agents.common.contract import resolved_filters_of
from core.agents.common.directives import answer_shape, presentation_mode, prose_suppressed
from core.answers.grounded import AnswerRequest
from core.answers.writer import write_answer
from core.answers.scope import answer_scope, defaulted_period


FLOW_FIELDS = {
    "gpr": ("gpr_query_result", "gpr_sql_query", "gpr_analytics"),
    "survey": ("survey_query_result", "survey_sql_query", "survey_analytics"),
    "gimmi": ("gimmi_query_result", "gimmi_sql_query", "gimmi_analytics"),
}


def response_evidence(state: dict, flows: tuple[str, ...]) -> tuple[dict, ...]:
    scope = resolved_filters_of(state.get("routing_context"))
    gathered = state.get("analyst_evidence") or []
    evidence = [dict(item, scope=item.get("scope") or scope) for item in gathered
                if item.get("flow") in flows and item.get("rows")]
    covered = {item.get("flow") for item in evidence}
    for flow in flows:
        if flow in covered:
            continue
        rows_key, sql_key, analytics_key = FLOW_FIELDS[flow]
        rows = state.get(rows_key)
        if not isinstance(rows, list):
            continue
        analytics = state.get(analytics_key) or {}
        evidence.append({"flow": flow, "lens": flow, "sql": state.get(sql_key) or "",
                         "rows": rows, "scope": analytics.get("scope") or scope,
                         "metrics": analytics.get("metrics") or {},
                         "facts": analytics.get("facts") or []})
    return tuple(evidence)


def write_response(state: dict, key: str, flows: tuple[str, ...], *, client=None) -> dict:
    if prose_suppressed(state.get("routing_context")):
        return {key: ""}
    question = state["messages"][-1].content
    evidence = response_evidence(state, flows)
    request = AnswerRequest(question, evidence,
                            answer_shape(state.get("routing_context")),
                            presentation_mode(state.get("routing_context")), answer_scope(state),
                            defaulted_period(evidence))
    answer = write_answer(request, client=client)
    return {key: answer.text, key + "_record": answer.as_dict()}
