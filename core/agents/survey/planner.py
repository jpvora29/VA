"""Survey planner — thin flow wrapper over the shared `BasePlannerNode`.

Wires the Survey-specific schema slices, definitions, and valid values; all planning
logic lives in `core.agents.common.planner` and
`core.schemas.analytical.PlannerSignature`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import dspy

from core.agents.common.planner import BasePlannerNode
from core.data.valid_values import GetValidData


class PlannerNode(BasePlannerNode):
    def __init__(
        self,
        carriers_schema: List[Dict[str, Any]],
        peers_schema: List[Dict[str, Any]],
        rules: str,
        demos: Optional[List[dspy.Example]] = None,
    ) -> None:
        super().__init__(
            flow="survey",
            schema_tables={"Carriers": carriers_schema, "Peers": peers_schema},
            definitions=GetValidData.definitions,
            valid_values=GetValidData.valid_values,
            rules=rules,
            demos=demos,
        )
