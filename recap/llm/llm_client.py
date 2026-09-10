"""Every model call the recap pipeline makes, behind one small async interface.

The pipeline depends on :class:`LLMClient` — "system prompt + user message in, a
validated Pydantic object out" — and never on Azure, a deployment name or a key.

The credentials come from :mod:`core.llm.clients`, which is the one place in this
application a *tier* becomes a chat client. The standalone app built its own
``AsyncAzureOpenAI`` from its own ``AZURE_OPENAI_*`` variables, so a deployment change
had to be made twice and a working chatbot could sit beside a recap that 401s. It now
reads the same ``.env`` as Studio, the Chatbot and MoM.

A tier is a class of work, not a model name:

    balanced   classifiers, enrichment, the structured passes that must not vary
    fast       the cheap ambiguous-slide noise filter, called once per slide
    reason     the recap prose a person actually reads

Responsibilities kept from the standalone client: bounded concurrency, retry with
exponential back-off, JSON-mode structured output, and token-usage logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from recap.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

#: Which tier each kind of call runs on. Names, not deployments — see the module
#: docstring and ``core.llm.clients``.
STRUCTURED_TIER = "balanced"
CHEAP_TIER = "fast"
PROSE_TIER = "reason"


class LLMClient:
    """
    Async chat client with:
      - Bounded concurrency via asyncio.Semaphore
      - Exponential back-off retry on rate-limit / transient errors
      - Structured JSON output via response_format=json_object
      - Token-usage logging

    One instance owns one semaphore, so passing the same client to every stage is
    what bounds the whole pipeline's fan-out.
    """

    def __init__(self, tier: str = STRUCTURED_TIER) -> None:
        # The semaphore is lazy-initialised on first use inside call(). Binding it in
        # __init__ ties it to whichever event loop is current then - and the pipeline
        # is constructed on a worker thread before asyncio.run() starts its loop.
        self._tier = tier
        self._semaphore: Optional[asyncio.Semaphore] = None

    # ----------------------------------------------------------------
    # The one call
    # ----------------------------------------------------------------

    async def call(
        self,
        *,
        system_prompt: str,
        user_message: str,
        response_model: Optional[Type[T]] = None,
        tier: Optional[str] = None,
        max_completion_tokens: int = 2048,
    ) -> Any:
        """
        Make a single async call against the configured deployment.

        Parameters
        ----------
        system_prompt   : LLM system message.
        user_message    : Content to classify / enrich.
        response_model  : If provided, the raw JSON is parsed into this
                          Pydantic model and returned typed.
        tier            : Override the tier for this one call.
        max_completion_tokens : Output cap. Applied only to a classic deployment —
                          a reasoning deployment rejects it (see ``_bind``).

        Returns
        -------
        Parsed Pydantic instance if response_model supplied, else raw str.
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)

        client = _bind(tier or self._tier, max_completion_tokens)
        messages = [("system", system_prompt), ("human", user_message)]

        async with self._semaphore:
            raw_text = await self._invoke_with_retry(client, messages)

        if response_model is None:
            return raw_text
        return response_model.model_validate(json.loads(raw_text))

    async def call_cheap(
        self,
        *,
        system_prompt: str,
        user_message: str,
        response_model: Optional[Type[T]] = None,
    ) -> Any:
        """The same call on the cheap tier — the per-slide noise filter's pass."""
        return await self.call(
            system_prompt=system_prompt,
            user_message=user_message,
            response_model=response_model,
            tier=CHEAP_TIER,
            max_completion_tokens=512,
        )

    # ----------------------------------------------------------------
    # Retry
    # ----------------------------------------------------------------

    async def _invoke_with_retry(self, client, messages) -> str:
        """Invoke, backing off on a transient failure, and log what it cost."""
        attempt = 0
        while True:
            try:
                response = await client.ainvoke(messages)
                _log_usage(response)
                return (response.content or "").strip()
            except Exception as exc:  # noqa: BLE001 - retry, then re-raise
                attempt += 1
                if attempt > settings.max_llm_retries or not _is_transient(exc):
                    raise
                wait = settings.retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "LLM call failed - retrying in %.1fs (attempt %d/%d): %s",
                    wait, attempt, settings.max_llm_retries, exc,
                )
                await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------

def _bind(tier: str, max_completion_tokens: int):
    """The shared client for ``tier``, pinned to JSON output and an output cap.

    The cap is applied only when the tier resolves to a classic deployment: a
    reasoning deployment takes a reasoning effort instead and 400s on a token cap,
    and which of the two a tier is depends on the environment, not on this module.
    """
    from core.llm.clients import make_client, resolve_tier

    client = make_client(tier).bind(response_format={"type": "json_object"})
    if max_completion_tokens and not resolve_tier(tier).effort:
        client = client.bind(max_tokens=max_completion_tokens)
    return client


# The two failures worth another attempt: the tenant is throttling us, or the call
# fell over in transit. Anything else (a bad prompt, an unknown deployment) fails the
# same way on every retry, so retrying only makes the user wait longer for it.
_TRANSIENT = ("ratelimit", "429", "timeout", "timed out", "connection",
              "temporarily", "service unavailable", "503", "500", "apierror")


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT)


def _log_usage(response) -> None:
    """Token usage for cost monitoring — never a reason for a call to fail."""
    usage = getattr(response, "usage_metadata", None) or {}
    if usage:
        logger.debug(
            "LLM usage | in=%s out=%s total=%s",
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            usage.get("total_tokens", 0),
        )
