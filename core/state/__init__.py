"""LangGraph state TypedDicts for the Virtual Analyst agents.

`agent_state.AgentState` is the state for the main chatbot workflow.
`pitch_state.PitchAgentState` is the state for the pitch/docx workflow.
"""
from core.state.agent_state import AgentState
from core.state.pitch_state import PitchAgentState, PitchQuestionResult

__all__ = ["AgentState", "PitchAgentState", "PitchQuestionResult"]
