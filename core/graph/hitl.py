"""HITL clarification node — Phase 3 stub.

Will become a LangGraph interrupt node: when the agent needs to disambiguate
(unknown peer, missing market, conflicting filters), it pauses with a
structured question payload that the Dash UI renders as an inline
clarifying-question card. The graph resumes on user selection.

See `project-decision-hitl-inline-cards` memory note.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.state.agent_state import AgentState


def hitl_clarify(state: "AgentState") -> "AgentState":  # pragma: no cover - Phase 3
    """Placeholder. Phase 3 will raise a LangGraph interrupt here."""
    raise NotImplementedError("HITL clarification node lands in Phase 3.")
