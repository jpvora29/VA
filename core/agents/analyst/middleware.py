"""LangChain agent middleware for the analyst solver.

The solver is the only `create_agent` path in the app, so this is the one place
LangChain middleware attaches (the deterministic GPR/Survey/GIMMI rails are DSPy +
LangGraph and are unaffected). Two concerns live here:

* **Observability** — `SolverObservabilityMiddleware` logs token usage and tool
  activity after every model step, so a turn's cost and loop depth are visible in
  the structured logs without enabling DSPy/LangChain debug tracing.
* **Context control** — `build_solver_middleware` also wires LangChain's
  `SummarizationMiddleware` so a long evidence-gathering loop compresses its older
  messages instead of growing unbounded. This is safe here because the rows that
  matter are captured out-of-band in the solver's `evidence` list, not re-read
  from message history.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRetryMiddleware,
    SummarizationMiddleware,
)

from core.observability import (
    accumulate_token_usage,
    extract_token_usage,
    log_event,
)
from logger import get_logger

logger = get_logger(__name__)

# Retry the MODEL call only on genuinely transient Azure/OpenAI failures. The
# default `retry_on=(Exception,)` is too broad — it would also retry auth and
# request-validation errors that will never succeed. Auth/4xx (other than 429)
# fall through immediately. After retries are exhausted we re-raise so the
# solver's existing top-level handler logs it and preserves partial evidence.
try:  # openai is a hard dependency of langchain_openai, but stay defensive.
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    _TRANSIENT_MODEL_ERRORS: tuple[type[Exception], ...] = (
        RateLimitError,
        APITimeoutError,
        APIConnectionError,
        InternalServerError,
    )
except Exception:  # pragma: no cover - openai import shape changed
    _TRANSIENT_MODEL_ERRORS = (TimeoutError, ConnectionError)

_MODEL_MAX_RETRIES = 2

# Summarization thresholds. The solver is short-lived and bounded by a recursion
# limit; summarize only once history is genuinely large, and keep enough recent
# turns that the latest SQL + error context survives.
_SUMMARY_TRIGGER_MESSAGES = 14
_SUMMARY_KEEP_MESSAGES = 6


class SolverObservabilityMiddleware(AgentMiddleware):
    """Emit a structured log line after each model call in the solver loop."""

    def __init__(self, *, flow: str = "", lens: str = "") -> None:
        super().__init__()
        self._flow = flow
        self._lens = lens

    def after_model(self, state: Any, runtime: Any) -> Optional[dict]:  # noqa: ARG002
        messages = (state or {}).get("messages") if isinstance(state, dict) else None
        if not messages:
            return None
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        usage = extract_token_usage(last)
        # Fold each solver model step into the turn-level token total so the
        # analyst path shows up alongside the deterministic rails.
        accumulate_token_usage(usage, label=f"analyst_solver:{self._lens or self._flow}")
        log_event(
            logger,
            "analyst_model_step",
            logging.DEBUG,
            node="analyst_solver",
            flow=self._flow,
            lens=self._lens,
            tool_calls=len(tool_calls),
            tool_names=[tc.get("name") for tc in tool_calls if isinstance(tc, dict)],
            **usage,
        )
        return None


def build_solver_middleware(
    model: Any,
    *,
    flow: str = "",
    lens: str = "",
    summary_model: Any = None,
) -> list[AgentMiddleware]:
    """Middleware stack for one solver agent.

    Order matters: retry is outermost so a transient model failure re-runs the
    whole model call; observability logs each step; summarization edits history
    before the model is called when the message count crosses the trigger.

    `summary_model` runs the history-compression call. It defaults to the solver
    `model`, but callers should pass a cheaper client (e.g.
    `Initialization.llm_summary`, gpt-4o-mini) so throwaway summaries don't cost
    the solver's rate.
    """
    return [
        ModelRetryMiddleware(
            max_retries=_MODEL_MAX_RETRIES,
            retry_on=_TRANSIENT_MODEL_ERRORS,
            on_failure="raise",
        ),
        SolverObservabilityMiddleware(flow=flow, lens=lens),
        SummarizationMiddleware(
            model=summary_model or model,
            trigger=("messages", _SUMMARY_TRIGGER_MESSAGES),
            keep=("messages", _SUMMARY_KEEP_MESSAGES),
        ),
    ]
