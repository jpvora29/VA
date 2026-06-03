"""Deterministic (no-LLM) analytical-plan validation.

`validate_plan` cross-checks the planner's output against the schema and the valid-value
lists the normalizer already uses, and returns advisory messages. The planner node appends
these to the plan's `notes` — they are advisory, never blocking, so grounding tightens
without over-rejecting.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


def _column_names(schema_tables: Dict[str, Any]) -> set[str]:
    """Collect the set of valid column names across all tables in the flow schema."""
    cols: set[str] = set()
    for columns in (schema_tables or {}).values():
        for col in columns or []:
            name = col.get("Column Name") if isinstance(col, dict) else None
            if name:
                cols.add(str(name))
    return cols


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def validate_plan(
    plan: Dict[str, Any],
    schema_tables: Dict[str, Any],
    valid_values: Dict[str, Any],
) -> List[str]:
    """Return advisory messages for plan elements not grounded in schema/valid_values.

    Args:
        plan: The planner output as a dict (parsed from the plan JSON string).
        schema_tables: Flow schema as {table_name: [column metadata]}.
        valid_values: {column_name: [valid values]} for this flow.

    Returns:
        A list of human-readable advisory strings (empty when the plan is clean).
    """
    if not isinstance(plan, dict):
        return []

    notes: List[str] = []
    valid_tables = {str(t).lower() for t in (schema_tables or {})}
    valid_columns = _column_names(schema_tables)
    valid_columns_lower = {c.lower() for c in valid_columns}

    # Tables referenced in the plan should exist in the flow schema.
    for table in plan.get("tables", []) or []:
        if str(table).lower() not in valid_tables:
            notes.append(
                f"Plan table '{table}' is not in the schema (valid: {sorted(valid_tables)})."
            )

    # group_by / filter keys should be real columns.
    for col in plan.get("group_by", []) or []:
        if str(col).lower() not in valid_columns_lower:
            notes.append(f"group_by column '{col}' is not a schema column.")

    filters = plan.get("filters", {}) or {}
    if isinstance(filters, dict):
        valid_values_lower = {
            str(k).lower(): {_norm(v) for v in (vals or [])}
            for k, vals in (valid_values or {}).items()
        }
        for key, val in filters.items():
            if str(key).lower() not in valid_columns_lower:
                notes.append(f"filter column '{key}' is not a schema column.")
                continue
            # Only check scalar string values against the valid list (skip ranges,
            # numbers, lists, and columns we have no valid list for).
            allowed = valid_values_lower.get(str(key).lower())
            if allowed and isinstance(val, str) and _norm(val) not in allowed:
                notes.append(
                    f"filter value '{val}' for '{key}' is not in the valid value list."
                )

    return notes


def annotate_plan_notes(
    plan_json: str,
    schema_tables: Dict[str, Any],
    valid_values: Dict[str, Any],
    flow: str = "",
) -> str:
    """Run `validate_plan` on a plan JSON string and fold advisory notes into `notes`.

    Returns the (possibly updated) plan JSON string. On any parse/serialise failure the
    original string is returned unchanged — validation is advisory and must never break
    the flow.
    """
    try:
        plan = json.loads(plan_json)
    except (TypeError, ValueError):
        return plan_json

    notes = validate_plan(plan, schema_tables, valid_values)
    if not notes:
        return plan_json

    advisory = "Validation advisory: " + " ".join(notes)
    existing = plan.get("notes") or ""
    plan["notes"] = (f"{existing}\n{advisory}".strip()) if existing else advisory

    try:
        return json.dumps(plan, indent=2)
    except (TypeError, ValueError):
        return plan_json
