"""Studio AI layer — optional LangChain agents over the deterministic deck.

Every agent is an *enhancement*: it runs only when an LLM is configured
(`client.llm_available()`), its output is faithfulness-checked (`verifier`), and on
any failure the caller falls back to the deterministic narrator/planner — so the
deck always generates, with or without a key. Agents: story, layout, selection,
critic. Nothing here is imported by the chatbot graph.
"""
from __future__ import annotations

from studio.ai.client import generate, llm_available, run_or_fallback, structured

__all__ = ["llm_available", "generate", "structured", "run_or_fallback"]
