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

from core.llm.clients import make_client
from core.observability import extract_token_usage, record_token_usage
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

# Per-request latency guards (LLM_TIMEOUT / LLM_MAX_RETRIES) are applied by
# `core.llm.clients._client_kwargs`, which every client here is built through.
# Without them a stalled or rate-limited Azure call hangs a turn indefinitely —
# most visibly at the terminal follow-up node, which leaves the UI stuck on
# "Suggesting follow-ups" until the background thread eventually finishes.


# ── Model tiers ──────────────────────────────────────────────────────────────
# A *tier* maps a class of work to a deployment and, optionally, reasoning controls.
# The heavy lifters (planner, SQL generation, insight synthesis, pitch narrative) want
# a reasoning model at higher effort; the mechanical nodes (SQL fixer, classifiers,
# extraction, boardroom widgets) want minimal effort so the inner loops stay cheap.
#
# The resolution itself lives in `core.llm.clients`, shared with Studio and MoM, and
# every client below is built by it. There is no second factory here: the six lines
# of `os.getenv` this file used to repeat per client had already drifted from it —
# each carried a hard-coded `model="gpt-41-mini"` label that no longer had to be true
# of the deployment behind it.
#
# Configure a tier by naming its deployment; anything unset falls back to DEPLOYMENT:
#
#   REASON_DEPLOYMENT / BALANCED_DEPLOYMENT / FAST_DEPLOYMENT / SUMMARY_DEPLOYMENT
#   REASON_EFFORT=high  BALANCED_EFFORT=medium  FAST_EFFORT=minimal   (optional)
#   REASON_VERBOSITY / …                                              (optional)
#
# An EFFORT is what makes a tier a reasoning call, so set it only on a deployment that
# is one. Leave it unset and the tier runs classic at its own temperature.


class _LazyClient:
    """A named LLM client that is built on first real use.

    The attribute itself exists for monkeypatching and import-time introspection, but
    the Azure client behind it is only constructed when a caller invokes a method on it.
    """

    def __init__(self, tier: str) -> None:
        self._tier = tier

    def _client(self) -> AzureChatOpenAI:
        return make_client(self._tier)

    def __getattr__(self, name: str):
        return getattr(self._client(), name)

    def __call__(self, *args, **kwargs):
        return self._client()(*args, **kwargs)


class Initialization:
    """Process-wide LLM clients and database engine.

    LLM clients are lazy proxies so imports stay credential-free. The database
    engine/session remain process-wide singletons.
    """

    llm: AzureChatOpenAI = _LazyClient("balanced")
    llm_balanced: AzureChatOpenAI = llm
    llm_creative: AzureChatOpenAI = _LazyClient("creative")
    llm_reason: AzureChatOpenAI = _LazyClient("reason")
    llm_fast: AzureChatOpenAI = _LazyClient("fast")
    llm_summary: AzureChatOpenAI = _LazyClient("summary")

    engine = create_engine(f"sqlite:///{os.getenv('DB_PATH')}")
    Session = sessionmaker(bind=engine)
    @staticmethod
    def log_prompt_cache_usage(response: Any, label: str = "") -> None:
        """Log + accumulate token usage from a LangChain response object.

        Signature-driven calls record their own usage inside `core.llm.predict`;
        this is for the direct `.invoke()` call sites.
        """
        record_token_usage(extract_token_usage(response), label=label)

