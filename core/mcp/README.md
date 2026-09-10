# Data tools and MCP transport

`tools.py` is the shared Python boundary for read-only SQL execution, schema,
definitions and entity matching. Internal graph nodes call these functions
directly. `server.py` exposes the same implementation through FastMCP; internal
calls do not need an MCP round trip.

The server registers four tools: `execute_sql`, `match_entities`,
`match_column_values` and `get_distinct_values`. It also registers schema,
valid-values and definitions resources. Start its stdio transport with
`python -m core.mcp.server` when an external client needs it.

Deterministic business calculations live in `core/analytics`, and the adapters in
`core/agents/common/analytics_tools.py` and `core/agents/analyst/analytics_tool.py`
preserve their facts and supporting inputs. The answer pipeline in `core/answers`
uses those facts to build and validate statements. MCP is a transport boundary,
not a separate definition of metrics or proof that an answer is correct.

Keep calculation rules in the analytics library, analytical task selection in
the planner, model selection behind adapters, and answer validation in the
shared fact/claim pipeline. Do not duplicate these rules inside MCP wrappers.
