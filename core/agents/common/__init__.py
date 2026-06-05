"""Shared, flow-parameterized agent building blocks for the GPR and Survey flows.

Both flows previously carried near-duplicate planner / SQL-agent / SQL-fixer code. The
modules here unify them behind one base each, driven by typed dspy signatures in
`core.schemas.analytical`. Flow-specific behaviour comes from the data passed in
(schema slice, definitions, valid_values, rules) — not from separate classes.
"""
from core.agents.common.planner import BasePlannerNode
from core.agents.common.sql_agent import (
    BaseSQLAgentNode,
    BaseSQLFixerNode,
    log_sql_failure,
    recalled_sql_examples,
    recalled_sql_text,
    record_recovered_sql_fix,
)
from core.agents.common.validation import annotate_plan_notes, validate_plan
from core.agents.common.sql_validation import assert_read_only, dry_run_explain

__all__ = [
    "BasePlannerNode",
    "BaseSQLAgentNode",
    "BaseSQLFixerNode",
    "log_sql_failure",
    "recalled_sql_examples",
    "recalled_sql_text",
    "record_recovered_sql_fix",
    "validate_plan",
    "annotate_plan_notes",
    "assert_read_only",
    "dry_run_explain",
]
