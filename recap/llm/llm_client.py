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

Reasoning effort has two sources, and they never collide:

    <TIER>_EFFORT             the application-wide setting (core.llm.clients) — what a
                              tier is when Recap says nothing
    RECAP_REASONING_EFFORT    Recap's own, optionally per stage (recap.config). When a
    (and ..._<STAGE>)         call carries one, it replaces the tier's effort for that
                              call only; the chatbot and Studio never see it.

Like ``<TIER>_EFFORT``, a Recap effort must only be set when the deployment behind the
tier is a reasoning model — a classic deployment returns 400 on ``reasoning_effort``.
``python -m recap.check_reasoning_effort`` shows whether a deployment honours it.

Responsibilities kept from the standalone client: bounded concurrency, retry with
exponential back-off, JSON-mode structured output, and token-usage logging — now
aggregated per stage, so a run logs one line per stage instead of one per call.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import replace
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel

from recap.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

#: Which tier each kind of call runs on. Names, not deployments — see the module
#: docstring and ``core.llm.clients``.
STRUCTURED_TIER = "balanced"
CHEAP_TIER = "fast"
PROSE_TIER = "reason"

#: The noise filter's output cap; its verdict is a few fields of JSON.
CHEAP_TOKEN_BUDGET = 2048

#: Friendly names for the stage tags passed to ``call(stage=...)``; the usage summary
#: falls back to the title-cased tag for a stage not listed here.
STAGE_DISPLAY_NAMES: Dict[str, str] = {
    "noise_filter_ambiguous": "Noise Filter (ambiguous cases)",
    "enrichment_context": "Enrichment - Context (LoB/Country/Region)",
    "enrichment_kpi": "Enrichment - KPI/Performance",
    "umbrella_classification": "Umbrella Classification",
    "subcategory_classification": "Sub-category Classification",
    "action_item_classification": "Action Item Classification",
    "recap_takeaway": "Key Takeaway Generation",
    "recap_dedup": "Takeaway Dedup",
    "recap_force_compress": "Takeaway Force-Compress (6-cap)",
    "recap_exec_summary": "Executive Summary Generation",
    "recap_overlap": "Overlap Detection",
    "recap_fact_check_slide1": "Fact-Check (Slide 1)",
    "recap_fact_check_slide2": "Fact-Check (Slide 2 / Country)",
    "recap_action_ranker": "Action Item Ranking",
    "recap_country_summary_per_sentence": "Country Summary Generation",
}

_USAGE_FIELDS = ("calls", "prompt_tokens", "completion_tokens", "total_tokens",
                 "reasoning_tokens")


class LLMClient:
    """
    Async chat client with:
      - Bounded concurrency via asyncio.Semaphore
      - Exponential back-off retry on rate-limit / transient errors
      - Structured JSON output via response_format=json_object
      - Token-usage logging, aggregated per stage (see log_usage_summary())

    One instance owns one semaphore, so passing the same client to every stage is
    what bounds the whole pipeline's fan-out. The usage totals are per instance for
    the same reason: every stage of a run shares this client, and two runs in one
    process (two users of the merged app) must not add into each other's totals.
    """

    def __init__(self, tier: str = STRUCTURED_TIER) -> None:
        # The semaphore is lazy-initialised on first use inside call(). Binding it in
        # __init__ ties it to whichever event loop is current then - and the pipeline
        # is constructed on a worker thread before asyncio.run() starts its loop.
        self._tier = tier
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._usage: Dict[str, Dict[str, int]] = defaultdict(
            lambda: dict.fromkeys(_USAGE_FIELDS, 0)
        )

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
        reasoning_effort: Optional[str] = None,
        stage: Optional[str] = None,
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
        max_completion_tokens : Output cap (see ``_bind`` for when it is sent).
        reasoning_effort : Recap's own effort for this call, from
                          ``settings.reasoning_effort_for(stage)``. None leaves the
                          tier exactly as ``core.llm.clients`` configures it.
        stage           : Pipeline-stage tag, used only for the aggregated usage
                          summary. Has no effect on the request; untagged calls
                          are summed under "untagged".

        Returns
        -------
        Parsed Pydantic instance if response_model supplied, else raw str.
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)

        client = _bind(tier or self._tier, max_completion_tokens, reasoning_effort)
        messages = [("system", system_prompt), ("human", user_message)]

        async with self._semaphore:
            raw_text = await self._invoke_with_retry(client, messages, stage)

        if response_model is None:
            return raw_text
        return response_model.model_validate(json.loads(raw_text))

    async def call_cheap(
        self,
        *,
        system_prompt: str,
        user_message: str,
        response_model: Optional[Type[T]] = None,
        reasoning_effort: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> Any:
        """The same call on the cheap tier — the per-slide noise filter's pass."""
        return await self.call(
            system_prompt=system_prompt,
            user_message=user_message,
            response_model=response_model,
            tier=CHEAP_TIER,
            max_completion_tokens=CHEAP_TOKEN_BUDGET,
            reasoning_effort=reasoning_effort,
            stage=stage,
        )

    # ----------------------------------------------------------------
    # Usage summary
    # ----------------------------------------------------------------

    def get_usage_totals(self) -> Dict[str, Dict[str, int]]:
        """A plain-dict snapshot of the per-stage usage since the last summary."""
        return {stage: dict(bucket) for stage, bucket in self._usage.items()}

    def reset_usage_totals(self) -> None:
        self._usage.clear()

    def log_usage_summary(self, log: Optional[logging.Logger] = None) -> None:
        """
        One INFO line per stage, then a grand total, e.g.:
            Total reasoning tokens used for Executive Summary Generation ..... 493

        Clears the totals afterwards, so each summary covers the calls since the
        previous one — a run over several decks logs each deck once, and the recap
        generated after them once, without counting anything twice.
        """
        log = log or logger
        if not self._usage:
            log.info("No LLM usage recorded.")
            return

        grand = dict.fromkeys(_USAGE_FIELDS, 0)
        for stage, bucket in sorted(self._usage.items()):
            display = STAGE_DISPLAY_NAMES.get(stage, stage.replace("_", " ").title())
            log.info(
                "Total reasoning tokens used for %s ..... %d "
                "(calls=%d, prompt=%d, completion=%d, total=%d)",
                display, bucket["reasoning_tokens"], bucket["calls"],
                bucket["prompt_tokens"], bucket["completion_tokens"], bucket["total_tokens"],
            )
            for field_name in _USAGE_FIELDS:
                grand[field_name] += bucket[field_name]

        log.info(
            "Total reasoning tokens used across ALL stages ..... %d "
            "(calls=%d, prompt=%d, completion=%d, total=%d)",
            grand["reasoning_tokens"], grand["calls"], grand["prompt_tokens"],
            grand["completion_tokens"], grand["total_tokens"],
        )
        self.reset_usage_totals()

    def _record_usage(self, stage: Optional[str], response) -> None:
        """Add one response's token usage to its stage's totals."""
        usage = getattr(response, "usage_metadata", None) or {}
        bucket = self._usage[stage or "untagged"]
        bucket["calls"] += 1
        bucket["prompt_tokens"] += usage.get("input_tokens") or 0
        bucket["completion_tokens"] += usage.get("output_tokens") or 0
        bucket["total_tokens"] += usage.get("total_tokens") or 0
        bucket["reasoning_tokens"] += reasoning_tokens(usage)

    # ----------------------------------------------------------------
    # Retry
    # ----------------------------------------------------------------

    async def _invoke_with_retry(self, client, messages, stage: Optional[str] = None) -> str:
        """Invoke, backing off on a transient failure, and record what it cost."""
        attempt = 0
        while True:
            try:
                response = await client.ainvoke(messages)
                _log_usage(response, stage)
                self._record_usage(stage, response)
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

def _bind(tier: str, max_completion_tokens: int, reasoning_effort: Optional[str] = None):
    """The shared client for ``tier``, pinned to JSON output and an output cap.

    ``reasoning_effort`` is Recap's own (RECAP_REASONING_EFFORT*). When given, it
    replaces the tier's effort for this call and drops the tier's temperature — a
    reasoning request takes one and rejects the other.

    The output cap follows the effort:
      classic tier               ``max_tokens`` (what the tier has always been sent)
      Recap effort               ``max_completion_tokens`` — the parameter a reasoning
                                 deployment accepts; the stage budget covers its
                                 reasoning tokens too, as recap.config sizes it
      tier's own <TIER>_EFFORT   no cap, as before: that budget is the app's, not ours
    """
    from core.llm.clients import client_for, resolve_tier

    config = resolve_tier(tier)
    if reasoning_effort:
        config = replace(config, effort=reasoning_effort, temperature=None)

    client = client_for(config).bind(response_format={"type": "json_object"})
    if not max_completion_tokens:
        return client
    if reasoning_effort:
        return client.bind(max_completion_tokens=max_completion_tokens)
    if not config.effort:
        return client.bind(max_tokens=max_completion_tokens)
    return client


# The two failures worth another attempt: the tenant is throttling us, or the call
# fell over in transit. Anything else (a bad prompt, an unknown deployment) fails the
# same way on every retry, so retrying only makes the user wait longer for it.
_TRANSIENT = ("ratelimit", "429", "timeout", "timed out", "connection",
              "temporarily", "service unavailable", "503", "500", "apierror")


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT)


def reasoning_tokens(usage: dict) -> int:
    """The reasoning tokens in a LangChain ``usage_metadata`` dict (0 when none).

    A non-zero count is the definitive sign a reasoning effort was honoured rather
    than silently ignored by the deployment.
    """
    details = (usage or {}).get("output_token_details") or {}
    return int(details.get("reasoning") or 0)


def _log_usage(response, stage: Optional[str] = None) -> None:
    """Per-call token usage at DEBUG — the per-stage summary is the INFO view."""
    usage = getattr(response, "usage_metadata", None) or {}
    if usage:
        logger.debug(
            "LLM usage | stage=%s in=%s out=%s total=%s reasoning=%s",
            stage or "untagged",
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            usage.get("total_tokens", 0),
            reasoning_tokens(usage),
        )
