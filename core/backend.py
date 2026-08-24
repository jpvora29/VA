"""Back-compat shim for the pre-refactor `core.backend` module.

The 5,342-line monolith was split in Phase 1 into focused modules under
`core/`. This shim re-exports the six symbols that external callers
(currently only `ui/callbacks.py`) actually import, so the rest of the
codebase keeps working without changes.

For new code, import directly from the new modules instead:

- `core.initialization`            → `Initialization`
- `core.data.general`              → `GeneralFunctions`
- `core.data.valid_values`         → `GetValidData`
- `core.state.agent_state`         → `AgentState`
- `core.state.pitch_state`         → `PitchAgentState`, `PitchQuestionResult`
- `core.schemas.{routing,survey,gpr,gimmi,combined,pitch,fallback}` → pydantic models + LLM signatures
- `core.rules.{survey,survey_chart,gpr,gpr_chart,gimmi}` → rule strings (Phase-2 migration target)
- `core.agents.{rephraser,router,fallback}` and `core.agents.{survey,gpr,gimmi,combined}.*` → node classes
- `core.graph.{main,pitch_question_graph,survey_subgraph,gpr_subgraph,combiner_subgraph}` → LangGraph workflows
- `core.pitch.workflow`            → `PitchBuilderWorkflow`

This shim will be removed in a later phase once all imports have moved.
"""
from __future__ import annotations

from core.data.general import GeneralFunctions
from core.graph.main import LangGraph
from core.initialization import Initialization
from core.pitch.workflow import PitchBuilderWorkflow
from core.state.agent_state import AgentState
from core.state.pitch_state import PitchAgentState

__all__ = [
    "AgentState",
    "GeneralFunctions",
    "Initialization",
    "LangGraph",
    "PitchAgentState",
    "PitchBuilderWorkflow",
]
