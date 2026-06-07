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
from typing import Any, Iterator

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


class Initialization:
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
