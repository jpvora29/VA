"""Singleton initialization for the Virtual Analyst backend.

Owns the Azure OpenAI chat clients (LangChain), the SQLAlchemy engine and session
factory, and a small helper that records prompt-cache usage to the observability
log.

Every LLM call in the app is a LangChain call: nodes declare a signature
(:mod:`core.llm.signature`) and run it through :mod:`core.llm.predict`, which
resolves its tier's client from here.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.llm.clients import make_client, tiers_enabled
from core.observability import extract_token_usage, record_token_usage
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
# the inner loops stay fast and cheap. The resolution itself lives in
# `core.llm.clients`, shared with Studio.
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


class _Clients(type):
    """Metaclass exposing the model tiers as LATE-BOUND class properties.

    The tiers must be late-bound for two reasons:

    1. Test transparency. With tiers OFF, each tier resolves to its legacy client
       *at access time*, so `monkeypatch.setattr(Initialization, "llm_creative",
       fake)` flows through to `llm_reason` (the seam a node actually reads).
       Eagerly aliasing the object at class-creation time would miss the patch.
    2. Zero behaviour change. OFF -> the exact legacy client; ON -> the built
       per-tier client.
    """

    @property
    def llm_reason(cls) -> "AzureChatOpenAI":
        return cls._llm_reason if tiers_enabled() else cls.llm_creative

    @property
    def llm_balanced(cls) -> "AzureChatOpenAI":
        return cls._llm_balanced if tiers_enabled() else cls.llm

    @property
    def llm_fast(cls) -> "AzureChatOpenAI":
        return cls._llm_fast if tiers_enabled() else cls.llm


class Initialization(metaclass=_Clients):
    """Process-wide LLM clients and database engine.

    Class attributes are intentionally module-level singletons, so every node
    shares one client per tier.
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


    # ── Tiered clients (see module header + the `_Clients` metaclass) ─────────
    # Built ONLY when MODEL_TIERS=on; the metaclass properties (llm_reason, …,
    # llm_fast) read these private attrs when on and fall back to the legacy
    # clients above when off. `reason` carries the heavy reasoning (planner,
    # insight synthesis, pitch narrative), `balanced` the SQL generation, `fast`
    # the mechanical inner-loop nodes.
    if tiers_enabled():
        _llm_reason: AzureChatOpenAI = make_client("reason")
        _llm_balanced: AzureChatOpenAI = make_client("balanced")
        _llm_fast: AzureChatOpenAI = make_client("fast")

    engine = create_engine(f"sqlite:///{os.getenv('DB_PATH')}")
    Session = sessionmaker(bind=engine)

    @staticmethod
    def log_prompt_cache_usage(response: Any, label: str = "") -> None:
        """Log + accumulate token usage from a LangChain response object.

        Signature-driven calls record their own usage inside `core.llm.predict`;
        this is for the direct `.invoke()` call sites.
        """
        record_token_usage(extract_token_usage(response), label=label)

