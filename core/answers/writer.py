"""Model adapter for selecting supported statements; numerical prose stays in Python."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.answers.claims import AnswerClaim
from core.answers.grounded import ANALYST_CLAIM_LIMIT, ANSWER_VERSION, AnswerRequest, GroundedAnswer, compose_answer


@dataclass(frozen=True)
class ClaimSelectionClient:
    question: str
    client: Any

    def __call__(self, candidates: tuple[AnswerClaim, ...]) -> list[str]:
        from langchain_core.messages import HumanMessage, SystemMessage

        options = candidates[:32]
        schema = {
            "name": "select_answer_statements",
            "description": "Choose supported statements that directly answer the question.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {"claim_ids": {"type": "array", "minItems": 1, "maxItems": ANALYST_CLAIM_LIMIT,
                                              "items": {"type": "string", "enum": [c.id for c in options]}}},
                "required": ["claim_ids"],
            },
        }
        model = self.client.bind_tools([schema], tool_choice="select_answer_statements", strict=True)
        response = model.invoke([
            SystemMessage(content=(
                "Select the statements that answer the exact question. Put the direct answer first, "
                "then the largest contributors, offsets, breadth and mix changes when available. "
                "For a breakdown, cover the different product lines rather than stopping at the total. "
                f"Select up to {ANALYST_CLAIM_LIMIT} distinct insights when the evidence supports them. "
                "Avoid repeating observations already explained by a comparison. "
                "All statements were calculated by the application. You may select their IDs only. "
                "Do not write, calculate, or infer additional claims."
            )),
            HumanMessage(content=json.dumps({"question": self.question,
                                             "statements": [{"id": c.id, "text": c.text} for c in options]})),
        ])
        calls = getattr(response, "tool_calls", None) or []
        if len(calls) != 1 or calls[0].get("name") != "select_answer_statements":
            return []
        return calls[0].get("args", {}).get("claim_ids", [])


def write_answer(request: AnswerRequest, *, client: Any = None) -> GroundedAnswer:
    if request.shape in {"lookup", "direct"} or request.presentation in {"table_only", "chart_only"}:
        return compose_answer(request)
    if client is None:
        from core.llm import tier_client
        client = tier_client("balanced")
    answer = compose_answer(request, select=ClaimSelectionClient(request.question, client))
    from logger import get_logger
    from core.observability import log_event
    log_event(get_logger(__name__), "answer_grounded", node="answer_writer",
              facts=len(answer.facts), claims=len(answer.claims),
              answer_version=ANSWER_VERSION, shape=request.shape,
              evidence_sets=len(request.evidence), claim_kinds=[c.kind for c in answer.claims],
              selection_rejected=answer.selection_rejected, limitation=answer.limitation)
    return answer
