"""Out-of-scope fallback node."""
from __future__ import annotations

from core.state.agent_state import AgentState


class Fallback:

    @staticmethod
    def fallback(state: AgentState) -> AgentState:

        print("Out of Scope")
        # state["out_of_scope_answer"] = "Out of Scope"

        return {"out_of_scope_answer": "Out of Scope"}
