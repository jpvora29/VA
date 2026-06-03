"""In-process FastMCP server exposing the Virtual Analyst data/SQL contract.

Registers the `core.mcp.tools` callables as MCP tools and the schema /
valid-values / definitions as cacheable MCP resources. The bodies just call the
plain functions in `tools.py`, so there is a single source of truth shared by:

  * the deterministic subgraph `*_execute_sql` nodes (call tools directly),
  * the analytical agent (binds tools directly),
  * and any external MCP client (talks to this server).

Consumed **in-process** today. Because it is also runnable as a standalone stdio
server (`python -m core.mcp.server`), exposing it to external clients later is a
transport flip, not a rewrite.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from core.mcp import tools

mcp = FastMCP("virtual-analyst-data")

_FLOWS = ("survey", "gpr", "gimmi")


# --------------------------------------------------------------------------- #
# Tools                                                                       #
# --------------------------------------------------------------------------- #
@mcp.tool()
def execute_sql(flow: str, sql: str) -> Dict[str, Any]:
    """Validate (read-only + EXPLAIN) and run a single SELECT against `flow`'s tables.

    `flow` is one of "survey", "gpr", "gimmi". Returns a dict with `rows`,
    `columns`, `error`, `overflow`, `row_count`. Never raises; failures come back
    as a non-null `error`. Write/DDL statements are rejected.
    """
    return tools.execute_sql(flow, sql).model_dump()


@mcp.tool()
def match_entities(flow: str, user_query: str) -> Dict[str, Any]:
    """Fuzzy-match country / carrier mentions in `user_query` to valid values."""
    return tools.match_entities(flow, user_query)


@mcp.tool()
def match_column_values(
    flow: str, column: str, term: str, top_n: int = 10, score_cutoff: int = 60
) -> List[str]:
    """Fuzzy-match `term` to the valid values of any `column`.

    Use to resolve a loose user phrase to an exact value before filtering —
    industry (SIC_Major_Class), SIC_Minor_Class, Business_Line, Cover_Line,
    Product_Line, Client_Segment, Region, survey Sections / Attributes, etc.
    """
    return tools.match_column_values(
        flow, column, term, top_n=top_n, score_cutoff=score_cutoff
    )


@mcp.tool()
def get_distinct_values(flow: str, column: str) -> List[str]:
    """List the distinct valid values of `column` for a flow (e.g. all industries)."""
    return tools.get_distinct_values(flow, column)


# --------------------------------------------------------------------------- #
# Resources (cacheable, read-only)                                            #
# --------------------------------------------------------------------------- #
@mcp.resource("schema://{flow}")
def schema_resource(flow: str) -> str:
    """Table/column schema for a flow (or all tables when flow == 'all')."""
    return json.dumps(tools.get_schema(None if flow == "all" else flow), default=str)


@mcp.resource("valid-values://{flow}")
def valid_values_resource(flow: str) -> str:
    """Valid column values for grounding filters."""
    return json.dumps(tools.get_valid_values(flow), default=str)


@mcp.resource("definitions://{flow}")
def definitions_resource(flow: str) -> str:
    """Business definitions for columns."""
    return json.dumps(tools.get_definitions(flow), default=str)


def list_registered() -> Dict[str, List[str]]:
    """Lightweight introspection helper for the in-process smoke test."""
    return {
        "tools": [
            "execute_sql",
            "match_entities",
            "match_column_values",
            "get_distinct_values",
        ],
        "resources": ["schema://{flow}", "valid-values://{flow}", "definitions://{flow}"],
        "flows": list(_FLOWS),
    }


if __name__ == "__main__":
    # Standalone stdio transport — for external MCP clients / future Phase F.
    mcp.run()
