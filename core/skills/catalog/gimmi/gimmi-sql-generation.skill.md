---
name: gimmi-sql-generation
description: GIMMI-specific SQL generation constraints.
flow: gimmi
scope: [sql]
always: true
priority: 70
---

[GIMMI SQL GENERATION]
- Use the `GIMMI` table only.
- Always return `Region`, `Product`, `Year`, `Quarter`, and `Market_Composite_Rate`.
- Use case-insensitive matching for text filters.
- Do not invent a region if the user and context do not provide one.
- Do not use carrier filters; GIMMI is market data.
