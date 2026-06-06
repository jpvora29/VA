---
name: cross-sql-readonly-safety
description: Read-only SQL safety and validation contract shared by every SQL-producing node.
flow: cross
scope: [sql, validation]
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
---

## Definition

Every generated query must be a single read-only SQLite statement. Data access
must happen through the shared SQL execution contract.

## Expected SQL Shape

- Start with `SELECT` or `WITH`.
- Use exactly one statement.
- Use only registry-approved tables and schema columns.
- Use `NULLIF()` around denominators in derived-rate calculations.
- Use clear aliases for all computed metrics.

## Forbidden Mistakes

- Do not return markdown fences or explanation text with SQL.
- Do not include comments or a trailing semicolon.
- Do not use write, DDL, attachment, pragma, transaction, or vacuum keywords.
- Do not add filters that are not in the plan, inherited context, or registry default.

## Runtime Validation

Even with this skill, code must still enforce read-only SQL with deterministic
validation and `EXPLAIN` before execution.

