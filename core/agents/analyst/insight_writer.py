"""Insight-writer agent.

The single, always-on synthesis step. Solvers gather evidence but never write
prose; this node turns ALL gathered evidence into the final Markdown answer,
following the output contract. It is a single non-tool LLM call — what used to be
the monolith's `_synthesize_from_evidence` salvage path, promoted to the normal
path so the answer is always written from clean, complete evidence.
"""
from __future__ import annotations

import logging
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage

from core.agents.analyst.common import digest_evidence
from core.agents.common.analysis_rules import analysis_directives
from core.agents.common.answer_shape import shape_contract, shape_label
from core.analysis import get_lens_library
from core.initialization import Initialization
from core.observability import log_event
from core.schemas.analyst_subgraph import Evidence
from logger import get_logger

logger = get_logger(__name__)


def write_insight(
    *,
    question: str,
    route: str,
    synthesis_focus: str,
    evidence: List[Evidence],
    presentation: str = "prose",
    shape: str = "analyst",
) -> str:
    """Synthesize the final Markdown answer from all gathered evidence.

    Returns "" if there is no evidence to write from or the call fails, so the
    caller can fall back to a graceful message.

    The per-turn response contract shapes the call: `presentation` of
    'chart_only'/'table_only' skips synthesis entirely (the UI renders the
    chart/table alone, and we never spend the LLM call), while `shape` selects
    HOW the answer is written — a lookup gets a sentence, a "why" gets ranked
    drivers, a "should we" gets a position (see
    :mod:`core.agents.common.answer_shape`). An unknown shape falls back to the
    full analysis, so a stale checkpoint can never leave a turn uncontracted.
    """
    if not evidence:
        return ""

    # Contract: a chart_only / table_only turn wants no prose at all — return
    # early so the writer's LLM call is never made.
    if presentation in ("chart_only", "table_only"):
        log_event(
            logger,
            "insight_skipped_by_directive",
            node="insight_writer",
            route=route,
            presentation=presentation,
        )
        return ""

    library = get_lens_library()
    focus = synthesis_focus or "Answer the question, then add the context a good analyst would."
    digest = digest_evidence(evidence)

    contract = shape_contract(shape)
    # The signed-off ICG decision tree (studio/rules/rules.yaml) plus the framing a
    # threshold cannot express: Marsh is a broker whose book is the carrier's
    # addressable opportunity, penetration happens by industry inside a product, a
    # performance question wants premium AND perception, and a growth percentage is
    # never reported without the money behind it. The deck has obeyed these since
    # they were written; the chat answer did not, which is how "premium up 1,140%"
    # off a book that wrote nothing last year became a headline.
    system_prompt = f"""You are a proactive insurance strategy analyst. Using ONLY
the evidence gathered below, write the final answer — answering the user's
question and proactively adding the context a good analyst would bring.

{analysis_directives()}

[ANALYST PRINCIPLES]
{library.principles()}

Synthesis focus: {focus}

{contract}"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=(
                "Write the final answer NOW, following the OUTPUT CONTRACT exactly. "
                "Do not ask for more data; use only the evidence below.\n\n"
                f"[EVIDENCE — executed queries and their rows, grouped by lens]\n{digest}\n\n"
                f"[USER QUESTION]\n{question}"
            )
        ),
    ]
    try:
        # Stream so the UI can render the answer token-by-token (the turn's
        # TokenStreamHandler, attached to the run config, forwards every chunk
        # tagged `final_answer`). Accumulate here for the committed state value.
        # A Stop raises out of `.stream()` mid-token; the broad except below turns
        # that into a graceful empty answer while the UI keeps the partial it saw.
        parts: List[str] = []
        # Reason tier: the final synthesis is the turn's highest-value reasoning.
        # The warm tier — this is prose a person reads, not structured output.
        for chunk in Initialization.llm_reason.with_config(
            tags=["final_answer"]
        ).stream(messages):
            parts.append(getattr(chunk, "content", "") or "")
        answer = "".join(parts).strip()
    except Exception as exc:  # noqa: BLE001 - synthesis is best-effort
        log_event(
            logger,
            "insight_writer_error",
            logging.ERROR,
            node="insight_writer",
            route=route,
            error=str(exc),
        )
        return ""

    log_event(
        logger,
        "insight_written",
        node="insight_writer",
        route=route,
        evidence_count=len(evidence),
        answered=bool(answer),
        shape=shape_label(shape),
    )
    return answer
