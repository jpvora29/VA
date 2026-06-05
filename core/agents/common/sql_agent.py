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
from logger import get_logger

logger = get_logger(__name__)


# ── Episodic SQL-fix learning helpers ───────────────────────────────────────
# These let any flow (a) recall a user's past error→fix pairs as extra few-shot
# examples at generation time, and (b) record a *verified* fix once the corrected
# query actually executes. Episodic memory is imported lazily so importing this
# module stays free of the DB/memory layer.


def recalled_sql_examples(
    user_id: Any, route: str, question: str, k: int = 3
) -> List[Any]:
    """Past verified fixes for similar questions, as ``dspy.Example`` few-shots."""
    if not user_id:
        return []
    try:
        from core.memory.episodic import episodic_store

        fixes = episodic_store.recall_sql_fixes(user_id, route, question, k=k)
        return [
            dspy.Example(user_query=f["question"], sql_query=f["sql"]).with_inputs(
                "user_query"
            )
            for f in fixes
        ]
    except Exception:  # pragma: no cover - recall must never break generation
        logger.exception("recalled_sql_examples failed")
        return []


def recalled_sql_text(user_id: Any, route: str, question: str, k: int = 3) -> str:
    """Same recall as :func:`recalled_sql_examples`, rendered as prompt text.

    For flows (e.g. GIMMI) whose SQL signature takes a single ``context`` string
    instead of a typed ``few_shot`` field.
    """
    if not user_id:
        return ""
    try:
        from core.memory.episodic import episodic_store

        fixes = episodic_store.recall_sql_fixes(user_id, route, question, k=k)
    except Exception:  # pragma: no cover
        logger.exception("recalled_sql_text failed")
        return ""
    if not fixes:
        return ""
    blocks = [
        f"-- Example (previously corrected):\n-- Q: {f['question']}\n{f['sql']}"
        for f in fixes
    ]
    return "Worked examples from this user's history:\n" + "\n\n".join(blocks)


def log_sql_failure(question: str, failed_sql: str, error: Any, route: str) -> dict:
    """Build the ``sql_error_log`` breadcrumb a fixer node appends to state."""
    return {
        "sql_error_log": [
            {
                "question": question,
                "failed_sql": failed_sql,
                "error": str(error)[:2000],
                "route": route,
            }
        ]
    }


def record_recovered_sql_fix(state: dict, route: str, working_sql: str) -> None:
    """If this turn recovered from a SQL error, persist the verified fix.

    Called from an execute node on success: reads the latest ``sql_error_log``
    breadcrumb (set by the fixer) and stores ``failed_sql → working_sql`` against
    the user. Best-effort; never raises into the graph.
    """
    log = state.get("sql_error_log") or []
    if not log:
        return
    last = log[-1]
    try:
        from core.memory.episodic import episodic_store

        episodic_store.record_sql_fix(
            user_id=state.get("user_id"),
            route=route,
            question=last.get("question", "") or "",
            failed_sql=last.get("failed_sql", "") or "",
            error=last.get("error", "") or "",
            working_sql=working_sql or "",
        )
    except Exception:  # pragma: no cover - recording must never break a turn
        logger.exception("record_recovered_sql_fix failed")


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
