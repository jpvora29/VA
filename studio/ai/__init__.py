"""Studio AI layer — optional LangChain agents over the deterministic deck.

Every agent is an *enhancement*: it runs only when an LLM is configured
(`client.llm_available()`), its output is faithfulness-checked (`verifier`), and on
any failure the caller falls back to the deterministic narrator/planner — so the
deck always generates, with or without a key. Agents: story, layout, selection,
critic. Nothing here is imported by the chatbot graph.

Two call shapes share the gate: one-shot calls (`client.generate` /
`client.structured`) and the deepagents harness (`deep_agent.run_deep_agent`) for
the multi-step semantic-judgment tasks — planning todos, skills from
``studio/skills``, retry and summarization included.

Both run on the shared LangChain tier clients (`core.llm.clients.make_client`).
"""
from __future__ import annotations

from studio.ai.client import generate, llm_available, run_or_fallback, structured
from studio.ai.deep_agent import deep_agent_available, run_deep_agent

__all__ = [
    "llm_available", "generate", "structured", "run_or_fallback",
    "deep_agent_available", "run_deep_agent",
]
