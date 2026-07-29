"""LangChain middleware for Studio deep agents — retry + observability.

The Studio counterpart of `core/agents/analyst/middleware.py`: the same
before/after-model concerns, but scoped to Studio's gated agents. This module
imports LangChain at the top, so it must only be imported *after*
`studio.ai.client.llm_available()` (or `studio.ai.deep_agent.deep_agent_available()`)
has confirmed the LLM gate is open — `studio.ai.deep_agent` does exactly that.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from langchain.agents.middleware import AgentMiddleware, ModelRetryMiddleware

from logger import get_logger

logger = get_logger(__name__)

# Retry only genuinely transient Azure/OpenAI failures (same rationale as the
# analyst solver): auth and request-validation errors will never succeed, so
# they fall through immediately and the caller's deterministic fallback stands.
try:
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


class StudioObservabilityMiddleware(AgentMiddleware):
    """Log token usage and tool activity after each deep-agent model step.

    Studio runs outside the chatbot turn accumulator, so this logs directly
    (mirroring `studio.ai.client._log_usage`) instead of folding into a turn total.
    """

    def __init__(self, *, node: str = "deep-agent") -> None:
        super().__init__()
        self._node = node

    def after_model(self, state: Any, runtime: Any) -> Optional[dict]:  # noqa: ARG002
        messages = (state or {}).get("messages") if isinstance(state, dict) else None
        if not messages:
            return None
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        usage = getattr(last, "usage_metadata", None)
        logger.log(
            logging.INFO if usage else logging.DEBUG,
            "studio.ai deep(%s) step tools=%s usage=%s",
            self._node,
            [tc.get("name") for tc in tool_calls if isinstance(tc, dict)],
            usage,
        )
        return None


def build_studio_middleware(*, node: str = "deep-agent") -> list[AgentMiddleware]:
    """The Studio deep-agent stack: transient-error retry, then step logging.

    (Planning todos, skills, filesystem, subagents and summarization come from
    the deepagents harness itself — this list is only what Studio adds on top.)
    """
    return [
        ModelRetryMiddleware(
            max_retries=_MODEL_MAX_RETRIES,
            retry_on=_TRANSIENT_MODEL_ERRORS,
            on_failure="raise",
        ),
        StudioObservabilityMiddleware(node=node),
    ]
