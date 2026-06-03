"""Unified SQL agent + SQL fixer — one flow-parameterized path for GPR + Survey.

Replaces the near-duplicate `GPRSQLAgentNode` / survey `SQLAgentNode` (and fixes the
survey `self.sql_query = dspy.ChainOfThought(...)` misnaming) and the two near-identical
inline SQL-fixer prompts in the subgraphs. Both flows now receive `valid_values` and
`valid_year_quarter` via typed fields instead of a flattened `context` blob.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import dspy

from core.schemas.analytical import SQLAgentSignature, SQLFixerOutput


class BaseSQLAgentNode(dspy.Module):
    """Flow-parameterized SQL generation agent.

    Args:
        flow: "gpr" or "survey" — informational.
        schema_tables: Schema for this flow as {table_name: [column metadata]}.
        rules: Flow-specific query-construction rules (skills or `core.rules.*`).
        valid_values: Valid column values for grounding filters.
        few_shot: Worked few-shot query examples for this flow (may be None/empty).
    """

    def __init__(
        self,
        flow: str,
        schema_tables: Dict[str, Any],
        rules: str,
        valid_values: Dict[str, Any],
        few_shot: Optional[List[Any]] = None,
    ) -> None:
        super().__init__()
        self.flow = flow
        self.schema_tables = schema_tables
        self.rules = rules
        self.valid_values = valid_values
        self.few_shot = few_shot or []
        self.predictor = dspy.ChainOfThought(SQLAgentSignature)

    def forward(
        self,
        user_query: str,
        query_plan: str,
        valid_year_quarter: Optional[List[str]] = None,
    ) -> str:
        result = self.predictor(
            schema=self.schema_tables,
            rules=self.rules,
            few_shot=self.few_shot,
            valid_values=self.valid_values,
            valid_year_quarter=valid_year_quarter or [],
            query_plan=query_plan,
            user_query=user_query,
        )
        return result.sql_query


_FIXER_SYSTEM_PROMPT = """
You are a SQL Error Fixer Agent for SQLite insurance queries.

[ROLE]
You diagnose errors in SQLite queries and return a corrected query. You understand
schemas, valid values, and typical SQLite syntax errors.

[INPUTS]
user query, table schema(s), column definitions, the SQL query, the error message
(this may be a pre-execution validation / EXPLAIN error or a runtime error), and the
valid list of column values.

[APPROACH]
1. Read the SQL query and the error message.
2. Compare the query against the schema and valid values.
3. Identify the cause (missing/typo column, wrong table, alias issue, syntax error,
   invalid filter value, ORDER BY after UNION, etc.).
4. Fix it step by step so it adheres to the schema and business rules.

[RULES]
- Never invent filters or columns outside the schema.
- Apply fuzzy matching for column/value names (e.g. "Chub" -> "Chubb"); normalise
  values to the valid list and keep comparisons case-insensitive.
- If a peer average is involved, use the Peers table to get the peer list for the
  Carrier/Country/Product combination, then filter in the main table. Avoid
  unnecessary joins.
- Output ONLY the corrected SQL query (no reasoning, no commentary, no code fences).
{extra_rules}
""".strip()


class BaseSQLFixerNode:
    """Flow-parameterized SQL fixer. One prompt, two flows.

    Used by the subgraph fixer nodes. Returns the corrected SQL string. `extra_rules`
    lets a flow inject one or two domain specifics (e.g. GPR's Carrier_Group rule).
    """

    def __init__(self, flow: str, extra_rules: str = "") -> None:
        self.flow = flow
        self.system_prompt = _FIXER_SYSTEM_PROMPT.format(
            extra_rules=("\n" + extra_rules if extra_rules else "")
        )

    def fix(
        self,
        *,
        user_query: str,
        schema_tables: Any,
        peer_schema: Any,
        sql_query: str,
        error_message: Any,
        valid_values: Dict[str, Any],
        definitions: Optional[Dict[str, str]] = None,
    ) -> str:
        # Imported lazily so importing this module does not pull in the LLM/init layer.
        from langchain_core.messages import HumanMessage, SystemMessage

        from core.initialization import Initialization

        human_message = (
            f"User Query: {user_query}\n"
            f"Schema: {schema_tables}\n"
            f"Peer Schema: {peer_schema}\n"
            f"Column Definitions: {definitions or {}}\n"
            f"SQL Query: {sql_query}\n"
            f"Error Message: {error_message}\n"
            f"Valid Values: {valid_values}\n"
        )

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=human_message),
        ]

        structured_llm = Initialization.llm.with_structured_output(SQLFixerOutput)
        corrected = structured_llm.invoke(messages)
        Initialization.log_prompt_cache_usage(
            response=corrected, label=f"{self.flow}_sql_fixer_agent"
        )
        return corrected.updated_query
