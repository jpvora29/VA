"""Out-of-scope fallback node."""
from __future__ import annotations

from core.observability import log_event
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class Fallback:

    @staticmethod
    def fallback(state: AgentState) -> AgentState:

        log_event(logger, "out_of_scope", node="fallback")

        return {"out_of_scope_answer": "Out of Scope"}
