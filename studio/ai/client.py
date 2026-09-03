"""LangChain client wrapper for the Studio AI agents — optional, fail-soft.

Every Studio AI call goes through here so they share one availability gate, one
graceful-fallback contract, and uniform logging. The call shape is the repo's LangChain
pattern (`core/agents/analyst/insight_writer.py`): an AzureChatOpenAI client +
`SystemMessage`/`HumanMessage` + `.invoke()` / `.with_structured_output(Model)`, wrapped
in try/except.

The client comes from the shared tier factory (`core.llm.clients`) rather than
`core.initialization`, so importing the Studio app never builds the chatbot's database
engine and session factory just to write a sentence. That factory reads `.env` itself, so
a Studio-only entry point — `studio/serve.py`, the authoring app, a script — is configured
exactly like the chatbot without importing it.

Availability is the same factory's answer (`core.llm.clients.available`), not a second
opinion about which environment variables a client needs. **There is no Studio-specific
opt-in: a configured LLM is the switch.** `STUDIO_AI=off` remains as a kill switch, for a
test or an operator that wants the deck pinned to its deterministic composers whatever the
environment carries.

The client is still built **lazily**, so importing this module — and the whole Studio app
and its tests — never depends on an LLM being configured.
"""
from __future__ import annotations

import os
from typing import Callable, Optional, Type, TypeVar

from logger import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


# The values that turn Studio AI OFF. There is deliberately no value that turns it ON:
# a configured LLM is the switch, and a second one to remember is a way to ship a
# deterministic deck by accident.
_OFF = {"off", "0", "false", "no"}

_DEFAULT_TIER = "balanced"


def disabled() -> bool:
    """True when this run has explicitly asked for deterministic output.

    ``STUDIO_AI=off`` is a kill switch, not a feature flag: it is how a test, a CI run or
    an operator pins the deck to its rule composers regardless of what credentials the
    environment happens to carry.
    """
    return os.getenv("STUDIO_AI", "auto").strip().lower() in _OFF


def llm_available() -> bool:
    """True when this run may call a model — no Studio-specific opt-in required.

    Studio used to answer this itself, by checking ``API_KEY`` and ``ENDPOINT``. That was a
    guess at another module's requirements kept in a second place: ``core.llm.clients``
    also needs a version and a deployment, so an environment carrying only those two was
    told AI was available and then failed on every call, and one configured through
    ``OPENAI_API_VERSION`` was told the opposite. Asking core whether it can build a client
    is the same question the call itself will ask, so the answer cannot drift from it.
    """
    if disabled():
        return False
    from core.llm.clients import available

    return available(_DEFAULT_TIER)


def _tier_client(tier: str):
    """The AzureChatOpenAI client for a tier (built lazily — see module docstring)."""
    from core.llm.clients import make_client

    return make_client(tier)


def _log_usage(node: str, resp: object) -> None:
    """Best-effort token log (Studio runs outside the chatbot turn accumulator)."""
    usage = getattr(resp, "usage_metadata", None) or getattr(resp, "response_metadata", None)
    if usage:
        logger.info("studio.ai %s usage=%s", node, usage)


def generate(system: str, user: str, *, tier: str = "balanced", node: str = "ai") -> Optional[str]:
    """One free-text LLM call. Returns None (caller falls back) if unavailable/fails."""
    if not llm_available():
        return None
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        resp = _tier_client(tier).invoke([SystemMessage(content=system), HumanMessage(content=user)])
        _log_usage(node, resp)
        return getattr(resp, "content", None) or None
    except Exception as exc:  # noqa: BLE001 — AI is best-effort
        logger.warning("studio.ai generate(%s) failed: %s", node, exc)
        return None


def structured(model: Type[T], system: str, user: str, *, tier: str = "balanced", node: str = "ai") -> Optional[T]:
    """One structured (Pydantic) LLM call. Returns None on unavailable/failure."""
    if not llm_available():
        return None
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        client = _tier_client(tier).with_structured_output(model)
        result = client.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("studio.ai structured(%s, %s) failed: %s", node, getattr(model, "__name__", model), exc)
        return None


def run_or_fallback(fn: Callable[[], Optional[T]], fallback: Callable[[], T]) -> T:
    """Run an AI step, returning ``fallback()`` if AI is off, errors, or returns None."""
    if not llm_available():
        return fallback()
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("studio.ai step failed, using deterministic fallback: %s", exc)
        result = None
    return result if result is not None else fallback()
