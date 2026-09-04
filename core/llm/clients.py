"""Azure chat clients by tier — one tier name in, one LangChain client out.

The single place a *tier* becomes an ``AzureChatOpenAI``. Every part of the app reads
it: the chatbot through :mod:`core.initialization`'s singletons, and Studio and MoM
through :func:`make_client` directly, so neither builds the chatbot's database engine
and session factory just to write a sentence.

A tier is a class of work, and it answers two independent questions from the
environment:

    <TIER>_DEPLOYMENT   which model  (falls back to DEPLOYMENT)
    <TIER>_EFFORT       is it a reasoning model?  (unset -> a classic model at the
                        tier's own temperature)

Set nothing and every tier resolves to ``DEPLOYMENT`` at its default temperature.
Set one variable and one tier moves; nothing else does. That is the whole model —
per-tier configuration is purely additive, and there is no mode to be in.

There used to be a ``MODEL_TIERS`` flag gating whether the per-tier variables were
read at all, plus a separate config path for each side of it. It made ``reason`` mean
two different things — warm temperature with the flag off, reasoning effort with it on
— which is exactly the sort of thing you have to read the source to find out. The two
questions above are independent, so the flag was answering a question nobody asked.

``<TIER>_EFFORT`` must be set explicitly to get reasoning parameters. Defaulting it
would send ``reasoning_effort`` to whatever ``<TIER>_DEPLOYMENT`` pointed at, and a
classic deployment 400s on it. Suggested values if you do want them:
``REASON_EFFORT=high``, ``BALANCED_EFFORT=medium``, ``FAST_EFFORT=minimal``.

Environment is read on every call and clients are cached per resolved config, so a
test that changes the env gets a new client rather than a stale one. Importing this
module builds nothing and needs no credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from logger import get_logger

logger = get_logger(__name__)

# Read ``.env`` here rather than only in ``core.initialization``. Credentials are a
# property of the process, not of the chatbot: a Studio run, a script or a notebook that
# imports this module gets the same configuration the chatbot does, without constructing
# the engine and session factory it does not need. ``load_dotenv`` never overrides a real
# environment variable, so an explicitly exported value still wins, and calling it twice
# is a no-op.
load_dotenv()

# Every tier, and the temperature it runs at when no reasoning effort is configured.
# The values ARE the tier semantics, so the table is the documentation:
#
#   reason / creative  the nodes whose output a person reads as prose — a chat answer,
#                      a QBR commentary column, the pitch narrative. Warm, because
#                      prose written at temperature 0 reads like it.
#   balanced           structured work that must not vary: SQL generation, extraction,
#                      classifiers, the commentary verifiers.
#   fast               mechanical inner-loop nodes.
#   summary            throwaway context compression (LangChain SummarizationMiddleware),
#                      which is why it usually points at a cheaper SUMMARY_DEPLOYMENT.
TIERS: Dict[str, float] = {
    "reason": 0.4,
    "creative": 0.4,
    "balanced": 0.0,
    "fast": 0.0,
    "summary": 0.0,
}

DEFAULT_TIER = "balanced"

# What turns a tier's reasoning parameters back off without unsetting the variable.
_NO_EFFORT = {"", "none", "off"}


@dataclass(frozen=True)
class TierConfig:
    """The resolved settings for one tier — hashable, so it doubles as the cache key."""

    deployment: Optional[str]
    temperature: Optional[float] = None   # None when a reasoning model rejects one
    effort: Optional[str] = None          # minimal | low | medium | high
    verbosity: Optional[str] = None       # low | medium | high


def _env(tier: str, suffix: str) -> str:
    return (os.getenv(f"{tier.upper()}_{suffix}") or "").strip()


def resolve_tier(tier: str) -> TierConfig:
    """Read one tier's settings from the environment.

    An unknown tier name reads as ``balanced`` rather than inventing a tier of its own,
    so a typo is a boring default instead of a silent third configuration.
    """
    if tier not in TIERS:
        tier = DEFAULT_TIER
    deployment = _env(tier, "DEPLOYMENT") or os.getenv("DEPLOYMENT")
    effort = _env(tier, "EFFORT").lower()
    if effort in _NO_EFFORT:
        return TierConfig(deployment, temperature=TIERS[tier])
    return TierConfig(deployment, effort=effort,
                      verbosity=_env(tier, "VERBOSITY").lower() or None)


def _client_kwargs(config: TierConfig) -> Dict[str, Any]:
    """The AzureChatOpenAI keyword arguments for a resolved tier."""
    kwargs: Dict[str, Any] = dict(
        azure_deployment=config.deployment,
        api_key=os.getenv("API_KEY"),
        azure_endpoint=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        # The deployment IS the model here. It used to be a hard-coded string per client
        # ("gpt-41-mini"), which is a label that goes stale the day the deployment behind
        # it changes and tells every log a small lie in the meantime.
        model=config.deployment or "azure-openai",
        timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
    )
    # A reasoning model takes an effort and rejects a temperature; a classic one is the
    # other way round. Never both.
    if config.effort:
        kwargs["reasoning_effort"] = config.effort
        if config.verbosity:
            kwargs["model_kwargs"] = {"verbosity": config.verbosity}
    else:
        kwargs["temperature"] = config.temperature
    return kwargs


_CLIENTS: Dict[TierConfig, Any] = {}


def make_client(tier: str):
    """The LangChain chat client for a tier, built once per distinct resolved config.

    Cached on the resolved config rather than on the tier name, so two tiers that
    resolve to the same settings share one client — which is the common case when
    nothing is configured per-tier.
    """
    config = resolve_tier(tier)
    if config not in _CLIENTS:
        from langchain_openai import AzureChatOpenAI

        _CLIENTS[config] = AzureChatOpenAI(**_client_kwargs(config))
    return _CLIENTS[config]


def available(tier: str = DEFAULT_TIER) -> bool:
    """True when a client for ``tier`` can actually be built from this environment.

    The honest form of the question, and the reason it lives here: every caller that asked
    it for itself was really asking "does ``make_client`` have what it needs", and answered
    with its own guess at the answer — Studio checked ``API_KEY`` and ``ENDPOINT`` and
    nothing else, so a process with those two set but no ``VERSION`` was told AI was on and
    then failed on every call. Building the client is the only check that cannot drift from
    what the client requires, and it is cheap: ``AzureChatOpenAI(...)`` validates its
    configuration and opens no connection.

    Never raises — an unconfigured environment is the normal case for a deterministic run,
    not an error.
    """
    try:
        return make_client(tier) is not None
    except Exception as exc:  # noqa: BLE001 — "cannot build" IS the answer
        logger.debug("core.llm: no client for tier %r (%s)", tier, exc)
        return False


def reset_clients() -> None:
    """Drop the client cache (tests that swap credentials mid-run)."""
    _CLIENTS.clear()
