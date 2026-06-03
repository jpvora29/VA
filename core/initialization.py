"""Singleton initialization for the Virtual Analyst backend.

Owns the Azure OpenAI clients (LangChain + dspy), the SQLAlchemy engine and
session factory, and a small helper that records prompt-cache usage to the
observability log.

Importing this module triggers `dspy.configure(...)`, matching the behavior of
the pre-refactor `core.backend` module.
"""
from __future__ import annotations

import os
from typing import Any

import dspy
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.observability import extract_token_usage, log_event
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)


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
    )

    dspy_llm: dspy.LM = dspy.LM(
        api_key=os.getenv("API_KEY"),
        api_base=os.getenv("ENDPOINT"),
        api_version=os.getenv("VERSION"),
        model=f"azure/{os.getenv('DEPLOYMENT')}",
        temperature=0,
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
    )

    dspy.configure(lm=dspy_llm)

    engine = create_engine(f"sqlite:///{os.getenv('DB_PATH')}")
    Session = sessionmaker(bind=engine)

    @staticmethod
    def log_prompt_cache_usage(response: Any, label: str = "") -> None:
        token_usage = extract_token_usage(response)
        if any(value is not None for value in token_usage.values()):
            log_event(logger, "llm_token_usage", label=label, token_usage=token_usage)
