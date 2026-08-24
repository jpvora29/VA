"""Azure chat clients by tier — one tier name in, one LangChain client out.

The single place a *tier* ("reason" / "balanced" / "fast") becomes an
``AzureChatOpenAI``. Both callers share it: :mod:`core.initialization` builds the
chatbot's per-tier singletons from :func:`resolve_tier`, and Studio calls
:func:`make_client` directly, so the Studio app never constructs the chatbot's
engine and session factory just to write a sentence.

Tier semantics:

* ``MODEL_TIERS`` off (the default) — ``reason`` is the expressive client
  (temperature 0.4), ``balanced`` and ``fast`` are the deterministic one
  (temperature 0).
* ``MODEL_TIERS=on`` — each tier reads its own ``<TIER>_DEPLOYMENT`` /
  ``<TIER>_EFFORT`` / ``<TIER>_VERBOSITY``. Reasoning params are attached only when
  a tier has its OWN explicit deployment: a tier falling back to the base
  ``DEPLOYMENT`` is assumed to point at a classic model, which would 400 on
  ``reasoning_effort``.

Environment is read on every call and clients are cached per resolved config, so a
test that changes the env gets a new client rather than a stale one. Importing this
module builds nothing and needs no credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

DEFAULT_EFFORT = {"reason": "high", "balanced": "medium", "fast": "minimal"}

# "creative" is not a deployment tier — it is the base deployment run warm, for the
# nodes whose output the user reads as prose. It never takes per-tier deployments or
# reasoning effort, so `MODEL_TIERS` does not change it.
CREATIVE = "creative"
_CREATIVE_TEMPERATURE = 0.4


@dataclass(frozen=True)
class TierConfig:
    """The resolved settings for one tier — hashable, so it doubles as the cache key."""

    deployment: Optional[str]
    temperature: Optional[float] = None   # None when a reasoning model rejects one
    effort: Optional[str] = None          # minimal | low | medium | high
    verbosity: Optional[str] = None       # low | medium | high


def tiers_enabled() -> bool:
    """True when ``MODEL_TIERS`` opts into per-tier deployments."""
    return os.getenv("MODEL_TIERS", "off").strip().lower() in {"on", "true", "1"}


def _legacy_config(tier: str) -> TierConfig:
    """The pre-tiers config: one deployment, expressive for ``reason`` only.

    ``reason`` runs warm here because with tiers off it aliases the expressive
    client — the behaviour a node on the reason tier has always had.
    """
    return TierConfig(
        deployment=os.getenv("DEPLOYMENT"),
        temperature=_CREATIVE_TEMPERATURE if tier == "reason" else 0.0,
    )


def _creative_config() -> TierConfig:
    """The expressive client: base deployment, warm, never a reasoning model."""
    return TierConfig(deployment=os.getenv("DEPLOYMENT"),
                      temperature=_CREATIVE_TEMPERATURE)


def _tiered_config(tier: str) -> TierConfig:
    """The per-tier config, with reasoning params only on an explicit deployment."""
    name = tier.upper()
    explicit = os.getenv(f"{name}_DEPLOYMENT")
    effort = (os.getenv(f"{name}_EFFORT", DEFAULT_EFFORT[tier]) or "").strip().lower()
    if not explicit or effort in {"", "none", "off"}:
        return TierConfig(deployment=explicit or os.getenv("DEPLOYMENT"), temperature=0.0)
    return TierConfig(
        deployment=explicit,
        effort=effort,
        verbosity=(os.getenv(f"{name}_VERBOSITY") or "").strip().lower() or None,
    )


def resolve_tier(tier: str) -> TierConfig:
    """Read one tier's settings from the environment. Unknown tiers read as balanced."""
    if tier == CREATIVE:
        return _creative_config()
    tier = tier if tier in DEFAULT_EFFORT else "balanced"
    return _tiered_config(tier) if tiers_enabled() else _legacy_config(tier)


def _client_kwargs(config: TierConfig) -> Dict[str, Any]:
    """The AzureChatOpenAI keyword arguments for a resolved tier."""
    kwargs: Dict[str, Any] = dict(
        azure_deployment=config.deployment,
        api_key=os.getenv("API_KEY"),
        azure_endpoint=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model=config.deployment or "azure-openai",
        timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
    )
    if config.effort:
        kwargs["reasoning_effort"] = config.effort
        if config.verbosity:
            kwargs["model_kwargs"] = {"verbosity": config.verbosity}
    else:
        kwargs["temperature"] = config.temperature
    return kwargs


_CLIENTS: Dict[TierConfig, Any] = {}


def make_client(tier: str):
    """The LangChain chat client for a tier, built once per distinct resolved config."""
    config = resolve_tier(tier)
    if config not in _CLIENTS:
        from langchain_openai import AzureChatOpenAI

        _CLIENTS[config] = AzureChatOpenAI(**_client_kwargs(config))
    return _CLIENTS[config]


def reset_clients() -> None:
    """Drop the client cache (tests that swap credentials mid-run)."""
    _CLIENTS.clear()
