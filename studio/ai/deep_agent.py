"""Deep-agent adapter — the LangChain `deepagents` harness behind Studio's AI gate.

Where `studio.ai.client` makes one-shot LLM calls, this module runs the full
deepagents harness for the semantic-judgment steps the template-intelligence
plan assigns to a deep agent (layout interpretation, QA explanation): planning
todos, progressive-disclosure **skills** loaded from ``studio/skills``,
summarization for long loops, plus Studio's own retry + observability
middleware (`studio.ai.middleware`).

Same fail-soft contract as the rest of `studio.ai`: everything is gated on
`deep_agent_available()`, heavy imports happen only after the gate passes, and
every entrypoint returns ``None`` on any failure so callers fall back to the
one-shot call or the deterministic path. The agent's filesystem access is a
read-only view of the skills directory — it can read SKILL.md guidance but can
never write files or touch data, and its output still goes through the same
deterministic validators as every other AI output.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Sequence, Type, TypeVar

from logger import get_logger
from studio.ai.client import llm_available

logger = get_logger(__name__)
T = TypeVar("T")

_RECURSION_LIMIT = 25


def skills_root() -> Path:
    """The progressive-disclosure skills library (``studio/skills/*/SKILL.md``)."""
    return Path(__file__).resolve().parents[1] / "skills"


def deep_agent_available() -> bool:
    """True when the Studio LLM gate is open and the deep agent isn't disabled.

    `STUDIO_DEEP_AGENT=off` opts out of the harness while leaving the one-shot
    `studio.ai.client` calls available; otherwise availability follows the same
    `STUDIO_AI` / credentials gate as every other Studio AI feature.
    """
    if os.getenv("STUDIO_DEEP_AGENT", "auto").strip().lower() in {"off", "0", "false", "no"}:
        return False
    return llm_available() and skills_root().is_dir()


def _make_agent(
    *,
    system_prompt: str,
    response_format: Optional[Type[T]],
    tools: Sequence[Any],
    tier: str,
    node: str,
):
    """Build one harnessed agent (imports deferred — see module docstring)."""
    from deepagents import FilesystemPermission, create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend

    from studio.ai.client import _tier_client
    from studio.ai.middleware import build_studio_middleware

    return create_deep_agent(
        _tier_client(tier),
        tools=list(tools),
        system_prompt=system_prompt,
        middleware=build_studio_middleware(node=node),
        backend=FilesystemBackend(root_dir=str(skills_root()), virtual_mode=True),
        skills=["/"],
        # Read-only harness: the agent may read skills, never write anywhere.
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        response_format=response_format,
        name=f"studio-{node}",
    )


def _final_text(result: dict) -> Optional[str]:
    messages = result.get("messages") or []
    for msg in reversed(messages):
        # `.text` is a str subclass (callable only as a deprecated compat shim).
        text = str(getattr(msg, "text", "") or "")
        if getattr(msg, "type", "") == "ai" and text.strip():
            return text.strip()
    return None


def run_deep_agent(
    user: str,
    *,
    system_prompt: str,
    response_format: Optional[Type[T]] = None,
    tools: Sequence[Any] = (),
    tier: str = "balanced",
    node: str = "deep-agent",
) -> Optional[Any]:
    """One harnessed agent run. Returns the structured response when a
    ``response_format`` model is given, the final message text otherwise, and
    ``None`` (caller falls back) if the gate is closed or anything fails.
    """
    if not deep_agent_available():
        return None
    from langchain_core.messages import HumanMessage

    try:
        agent = _make_agent(
            system_prompt=system_prompt, response_format=response_format,
            tools=tools, tier=tier, node=node,
        )
        result = agent.invoke(
            {"messages": [HumanMessage(content=user)]},
            config={"recursion_limit": _RECURSION_LIMIT},
        )
    except Exception as exc:  # noqa: BLE001 — the harness is best-effort
        logger.warning("studio.ai deep(%s) failed: %s", node, exc)
        return None
    if response_format is not None:
        return result.get("structured_response")
    return _final_text(result)
