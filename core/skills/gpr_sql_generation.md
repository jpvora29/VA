---
name: gpr-sql-generation
description: GPR-specific SQL generation constraints.
flow: gpr
scope: [sql]
always: true
priority: 70
---

[GPR SQL GENERATION]
- Use `GPR` and `Peers` only.
- Use `Carrier_Group` for carrier filtering and grouping; do not use `Carrier_Name`.
- Financial metrics such as premium must use `SUM(Premium)` unless the plan explicitly requests an average.
- Include every requested breakdown dimension in both `SELECT` and `GROUP BY`.
- Use case-insensitive matching for text filters: `LOWER(column) = LOWER(value)`.
- Do not add default geography, product, segment, or carrier filters that are absent from the analytical plan.
