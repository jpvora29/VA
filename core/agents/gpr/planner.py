"""GPR planner — thin flow wrapper over the shared `BasePlannerNode`.

Wires the GPR-specific schema slices, definitions, and valid values; all planning logic
lives in `core.agents.common.planner` and `core.schemas.analytical.PlannerSignature`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.agents.common.planner import BasePlannerNode
from core.data.valid_values import GetValidData
from core.llm import Example


class GPRPlannerNode(BasePlannerNode):
    def __init__(
        self,
        gpr_schema: List[Dict[str, Any]],
        peers_schema: List[Dict[str, Any]],
        rules: str,
        demos: Optional[List[Example]] = None,
    ) -> None:
        super().__init__(
            flow="gpr",
            schema_tables={"GPR": gpr_schema, "Peers": peers_schema},
            definitions=GetValidData.definitions_gpr,
            valid_values=GetValidData.valid_values_gpr,
            rules=rules,
            demos=demos,
        )
