---
name: cross-sql-readonly-safety
description: Read-only SQL safety contract shared by all SQL generation nodes.
flow: cross
scope: [sql]
always: true
priority: 100
---

[READ-ONLY SQL SAFETY]
- Return exactly one SQLite statement.
- The statement must start with `SELECT` or `WITH`.
- Do not include markdown fences, comments, explanations, or a trailing semicolon.
- Do not use `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`, `DETACH`, `PRAGMA`, `VACUUM`, or `REPLACE`.
- Use only tables and columns provided in the route schema.
- Include only filters present in the analytical plan.
- Use `NULLIF()` for division and clear aliases for computed metrics.
