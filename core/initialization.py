"""Singleton initialization for the Virtual Analyst backend.

Owns the Azure OpenAI clients (LangChain + dspy), the SQLAlchemy engine and
session factory, and a small helper that records prompt-cache usage to the
observability log.

Importing this module triggers `dspy.configure(...)`, matching the behavior of
the pre-refactor `core.backend` module.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import dspy
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.observability import (
    extract_token_usage,
    normalize_dspy_usage,
    record_token_usage,
)
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

# Per-request latency guards. Without these, a stalled/rate-limited Azure call
# hangs a turn indefinitely — most visibly at the terminal follow-up node, which
# leaves the UI stuck on "Suggesting follow-ups" until the background thread
# eventually finishes. A bounded timeout + small retry cap makes the worst case a
# short, recoverable wait instead. Both are env-overridable.
_LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
_LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))


# ── Model tiers (GPT-5-ready) ────────────────────────────────────────────────
# A *tier* maps a class of work to an Azure deployment + optional GPT-5 reasoning
# controls. The heavy lifters (planner, SQL generation, insight synthesis, pitch
# narrative) want a reasoning model run at higher effort; the mechanical nodes
# (SQL fixer, classifiers, extraction, boardroom widgets) want minimal effort so
# the inner loops stay fast and cheap.
#
# The mechanism is OFF by default: with MODEL_TIERS unset, every tier accessor
# below aliases the legacy single-model clients, so behaviour is byte-identical
# until you opt in. Turn it on only once a reasoning deployment (e.g. gpt-5-mini)
# exists:
#
#   MODEL_TIERS=on
#   REASON_DEPLOYMENT=<gpt-5-mini deployment>     # each falls back to DEPLOYMENT
#   BALANCED_DEPLOYMENT=<...>
#   FAST_DEPLOYMENT=<...>
#   REASON_EFFORT=high  BALANCED_EFFORT=medium  FAST_EFFORT=minimal
#   REASON_VERBOSITY / BALANCED_VERBOSITY / FAST_VERBOSITY   (optional; off unless set)
#
# Reasoning params are attached ONLY when an effort is set for the tier, so a
# tier pointed at a classic (non-reasoning) deployment sends nothing new and
# keeps working. Set <TIER>_EFFORT=none to force a tier back to classic temp-0.
_MODEL_TIERS_ON = os.getenv("MODEL_TIERS", "off").strip().lower() in {"on", "true", "1"}
# dspy refuses reasoning models below this token budget (reasoning + output must
# both fit); also gives classic tiers headroom when reused for big prompts.
_REASON_MAX_TOKENS = int(os.getenv("REASON_MAX_TOKENS", "16000"))


@dataclass(frozen=True)
class _Tier:
    """Resolved settings for one model tier."""

    deployment: Optional[str]
    effort: Optional[str] = None      # GPT-5 reasoning_effort: minimal|low|medium|high
    verbosity: Optional[str] = None   # GPT-5 verbosity: low|medium|high


def _resolve_tier(name: str, default_effort: str) -> _Tier:
    """Read a tier's deployment + reasoning controls from the environment.

    Reasoning params are attached ONLY when the tier has its OWN explicit
    `<NAME>_DEPLOYMENT`. A tier that falls back to the base `DEPLOYMENT` is
    assumed to point at the existing (classic) model, so it stays at temp 0 and
    sends no reasoning_effort — sending it to a non-reasoning model would 400.
    This lets you upgrade just the reasoning path (set REASON_DEPLOYMENT) without
    accidentally breaking the cheaper tiers that still ride the base deployment.

    `<NAME>_EFFORT` of "none"/"off"/"" disables reasoning params even when the
    tier has its own deployment.
    """
    explicit = os.getenv(f"{name}_DEPLOYMENT")
    deployment = explicit or os.getenv("DEPLOYMENT")
    effort = (os.getenv(f"{name}_EFFORT", default_effort) or "").strip().lower()
    if not explicit or effort in {"", "none", "off"}:
        effort = None
    verbosity = (os.getenv(f"{name}_VERBOSITY") or "").strip().lower() or None
    return _Tier(deployment=deployment, effort=effort, verbosity=verbosity)


def _make_chat_client(tier: _Tier) -> AzureChatOpenAI:
    """LangChain Azure client for a tier.

    A reasoning tier gets `reasoning_effort` (and optional `verbosity`) and NO
    temperature — reasoning models reject a custom temperature. A classic tier
    keeps temperature 0 for deterministic, fact-bearing output.
    """
    kwargs: dict[str, Any] = dict(
        azure_deployment=tier.deployment,
        api_key=os.getenv("API_KEY"),
        azure_endpoint=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model=tier.deployment or "azure-openai",
        timeout=_LLM_TIMEOUT,
        max_retries=_LLM_MAX_RETRIES,
    )
    if tier.effort:
        kwargs["reasoning_effort"] = tier.effort
        if tier.verbosity:
            kwargs["model_kwargs"] = {"verbosity": tier.verbosity}
    else:
        kwargs["temperature"] = 0.0
    return AzureChatOpenAI(**kwargs)


def _make_dspy_client(tier: _Tier) -> "dspy.LM":
    """dspy LM for a tier.

    Reasoning models require temperature=1.0 and a generous max_tokens (dspy
    enforces both); classic tiers stay at temp 0.
    """
    common = dict(
        api_key=os.getenv("API_KEY"),
        api_base=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model=f"azure/{tier.deployment}",
        num_retries=_LLM_MAX_RETRIES,
        timeout=_LLM_TIMEOUT,
    )
    if tier.effort:
        return dspy.LM(
            **common,
            temperature=1.0,
            max_tokens=_REASON_MAX_TOKENS,
            reasoning_effort=tier.effort,
        )
    return dspy.LM(**common, temperature=0.0)


class _Clients(type):
    """Metaclass exposing the model tiers as LATE-BOUND class properties.

    The tiers must be late-bound for two reasons:

    1. Test transparency. With tiers OFF, each tier resolves to its legacy client
       *at access time*, so `monkeypatch.setattr(Initialization, "llm_creative",
       fake)` flows through to `llm_reason` (the seam a node actually reads).
       Eagerly aliasing the object at class-creation time would miss the patch.
    2. Zero behaviour change. OFF -> the exact legacy client; ON -> the built
       per-tier client.

    The dspy tiers are exposed the same way for symmetry, but dspy *wiring* goes
    through `Initialization.use_tier`, which is a no-op when OFF so predictors keep
    using the global dspy LM (and `dspy.context(...)` test overrides still apply).
    """

    @property
    def llm_reason(cls) -> "AzureChatOpenAI":
        return cls._llm_reason if _MODEL_TIERS_ON else cls.llm_creative

    @property
    def llm_balanced(cls) -> "AzureChatOpenAI":
        return cls._llm_balanced if _MODEL_TIERS_ON else cls.llm

    @property
    def llm_fast(cls) -> "AzureChatOpenAI":
        return cls._llm_fast if _MODEL_TIERS_ON else cls.llm

    @property
    def dspy_reason(cls) -> "dspy.LM":
        return cls._dspy_reason if _MODEL_TIERS_ON else cls.dspy_llm

    @property
    def dspy_balanced(cls) -> "dspy.LM":
        return cls._dspy_balanced if _MODEL_TIERS_ON else cls.dspy_llm

    @property
    def dspy_fast(cls) -> "dspy.LM":
        return cls._dspy_fast if _MODEL_TIERS_ON else cls.dspy_llm


class Initialization(metaclass=_Clients):
    """Process-wide LLM clients and database engine.

    Class attributes are intentionally module-level singletons; importing
    this module establishes the dspy default LM.
    """

    llm: AzureChatOpenAI = AzureChatOpenAI(
        azure_deployment=os.getenv("DEPLOYMENT"),
        api_key=os.getenv("API_KEY"),
        azure_endpoint=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model="gpt-41-mini",
        timeout=_LLM_TIMEOUT,
        max_retries=_LLM_MAX_RETRIES,
    )

    # Expressive variant (LangChain) for the pitch narrative + report writer, so
    # the consulting prose varies naturally. Structured extraction/KPI nodes keep
    # using `llm` for stable, deterministic JSON.
    llm_creative: AzureChatOpenAI = AzureChatOpenAI(
        azure_deployment=os.getenv("DEPLOYMENT"),
        api_key=os.getenv("API_KEY"),
        azure_endpoint=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model="gpt-41-mini",
        temperature=0.4,
        timeout=_LLM_TIMEOUT,
        max_retries=_LLM_MAX_RETRIES,
    )

    # Dedicated low-cost client for context compression (LangChain
    # SummarizationMiddleware). Summaries are throwaway scaffolding, so we point
    # them at a cheaper deployment (gpt-4o-mini) instead of paying the solver
    # model's rate. Falls back to the main DEPLOYMENT when SUMMARY_DEPLOYMENT is
    # unset so existing environments keep working.
    llm_summary: AzureChatOpenAI = AzureChatOpenAI(
        azure_deployment=os.getenv("SUMMARY_DEPLOYMENT") or os.getenv("DEPLOYMENT"),
        api_key=os.getenv("API_KEY"),
        azure_endpoint=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model="gpt-4o-mini",
        temperature=0,
        timeout=_LLM_TIMEOUT,
        max_retries=_LLM_MAX_RETRIES,
    )

    dspy_llm: dspy.LM = dspy.LM(
        api_key=os.getenv("API_KEY"),
        api_base=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model=f"azure/{os.getenv('DEPLOYMENT')}",
        temperature=0,
        num_retries=_LLM_MAX_RETRIES,
        timeout=_LLM_TIMEOUT,
    )

    # Expressive variant for narrative nodes (chat responses, combined insight,
    # follow-ups, pitch narrative). A modest temperature lets phrasing vary
    # naturally so answers don't read identically every time. Correctness-
    # critical nodes (SQL, planner, router, normalizer) keep `dspy_llm` at 0.
    dspy_creative: dspy.LM = dspy.LM(
        api_key=os.getenv("API_KEY"),
        api_base=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model=f"azure/{os.getenv('DEPLOYMENT')}",
        temperature=0.4,
        num_retries=_LLM_MAX_RETRIES,
        timeout=_LLM_TIMEOUT,
    )

    dspy.configure(lm=dspy_llm)

    # ── Tiered clients (see module header + the `_Clients` metaclass) ─────────
    # Built ONLY when MODEL_TIERS=on; the metaclass properties (llm_reason, …,
    # dspy_fast) read these private attrs when on and fall back to the legacy
    # clients above when off. `reason` carries the heavy reasoning (planner,
    # insight synthesis, pitch narrative), `balanced` the SQL generation, `fast`
    # the mechanical inner-loop nodes.
    if _MODEL_TIERS_ON:
        _llm_reason: AzureChatOpenAI = _make_chat_client(_resolve_tier("REASON", "high"))
        _llm_balanced: AzureChatOpenAI = _make_chat_client(
            _resolve_tier("BALANCED", "medium")
        )
        _llm_fast: AzureChatOpenAI = _make_chat_client(_resolve_tier("FAST", "minimal"))

        _dspy_reason: dspy.LM = _make_dspy_client(_resolve_tier("REASON", "high"))
        _dspy_balanced: dspy.LM = _make_dspy_client(_resolve_tier("BALANCED", "medium"))
        _dspy_fast: dspy.LM = _make_dspy_client(_resolve_tier("FAST", "minimal"))

    @classmethod
    def use_tier(cls, module: "dspy.Module", tier: str) -> None:
        """Point a dspy module's predictors at a tier's LM.

        No-op when MODEL_TIERS is off: the module then keeps using the global
        dspy LM, so behaviour is identical to before this change and
        `dspy.context(lm=...)` overrides in tests still take effect. When on, it
        binds the `reason` / `balanced` / `fast` LM to every predictor in the
        module via dspy's `set_lm`.
        """
        if not _MODEL_TIERS_ON:
            return
        module.set_lm(getattr(cls, f"dspy_{tier}"))

    engine = create_engine(f"sqlite:///{os.getenv('DB_PATH')}")
    Session = sessionmaker(bind=engine)

    @staticmethod
    def log_prompt_cache_usage(response: Any, label: str = "") -> None:
        """Log + accumulate token usage from a LangChain response object.

        For dspy predictors the usage is NOT on the returned (parsed) object —
        wrap those calls in `Initialization.dspy_usage(...)` instead.
        """
        record_token_usage(extract_token_usage(response), label=label)

    @staticmethod
    @contextmanager
    def dspy_usage(label: str, node: str | None = None) -> Iterator[None]:
        """Capture token usage for the dspy LM calls made inside the block.

        dspy attaches usage to the LM call, not to the parsed value a module's
        `forward` returns, so logging the returned object (the old pattern) always
        came up empty. This wraps the predictor/module call in dspy's usage
        tracker and records the real per-agent totals on exit.
        """
        with dspy.track_usage() as tracker:
            yield
        record_token_usage(
            normalize_dspy_usage(tracker.get_total_tokens()), label=label, node=node
        )
