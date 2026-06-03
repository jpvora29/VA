"""Survey SQL agent — thin flow wrapper over the shared `BaseSQLAgentNode`.

Wires the Survey-specific schema slices and valid values; all generation logic lives in
`core.agents.common.sql_agent` and `core.schemas.analytical.SQLAgentSignature`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.agents.common.sql_agent import BaseSQLAgentNode
from core.data.valid_values import GetValidData


class SQLAgentNode(BaseSQLAgentNode):
    def __init__(
        self,
        carrier_schema: List[Dict[str, Any]],
        peer_schema: List[Dict[str, Any]],
        rules: str,
        few_shot: Optional[List[Any]] = None,
    ) -> None:
        super().__init__(
            flow="survey",
            schema_tables={"Carriers": carrier_schema, "Peers": peer_schema},
            rules=rules,
            valid_values=GetValidData.valid_values,
            few_shot=few_shot,
        )
