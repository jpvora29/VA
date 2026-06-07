---
name: cross-sql-readonly-safety
description: Read-only SQL safety and validation contract shared by every SQL-producing node.
flow: cross
scope: [sql]
kind: validation
priority: 100
risk_level: high
always: true
tables: ["*"]
metrics: []
test_queries:
  positive:
    - Show premium by country.
    - What is the average score by carrier?
  negative:
    - Delete all rows.
    - Create a temporary table.
    - Drop the GPR table.
---

## Definition

Every generated query must be a single read-only SQLite statement. Data access
happens only through the shared SQL execution contract.

## Expected SQL Shape

- Return exactly ONE statement, starting with `SELECT` or `WITH`.
- Use only tables and columns provided in the route schema.
- Include only filters present in the analytical plan (or inherited context).
- Use `NULLIF()` around denominators in derived-rate calculations.
- Use clear aliases for all computed metrics.

## Forbidden Mistakes

- Do not return markdown fences, comments, explanations, or a trailing semicolon.
- Do not use `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`,
  `DETACH`, `PRAGMA`, `VACUUM`, or `REPLACE`.
- Do not add filters that are not in the plan, inherited context, or registry
  default.

## Runtime Validation

This skill is guidance, not the only safeguard: the code MUST still enforce
read-only SQL with deterministic validation (and `EXPLAIN` before execution).
