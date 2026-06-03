"""Typed I/O contracts for the MCP tool layer.

The execute-SQL tool returns one well-typed result instead of the historical
"list-of-rows OR error-string" overloading that each `*_execute_sql` node used
to invent for itself. Flow-specific state mapping (e.g. survey's `:-` error
wrapping, GIMMI's generic retry message) stays in the nodes; the tool stays
neutral and predictable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExecuteSQLResult(BaseModel):
    """Outcome of running a single read-only SELECT through `execute_sql`.

    On success: `rows` is a list of row dicts, `error` is None.
    On any failure (validation, EXPLAIN, or runtime): `rows` is None, `error`
    holds a human-readable message suitable for feeding the SQL fixer loop.
    """

    rows: Optional[List[Dict[str, Any]]] = None
    columns: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    overflow: bool = False
    row_count: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None
