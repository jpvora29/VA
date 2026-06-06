---
name: gimmi-market-rate
description: GIMMI market composite rate query and response rules.
flow: gimmi
scope: [sql, response, pitch]
kind: metric
priority: 85
risk_level: medium
always: true
tables: [GIMMI]
columns: [Region, Product, Year, Quarter, Market_Composite_Rate]
metrics: [market_composite_rate]
---

## Definition

GIMMI provides market composite rate by region, product, year, and quarter.

## Expected SQL Shape

- Query only the `GIMMI` table.
- Require region/product/time filters when the user asks for a specific market rate.
- Order quarter and year chronologically when showing movement.

## Response Rules

- Use a compact table first.
- Mention direction only when multiple periods support it.
- Do not connect GIMMI movement to carrier premium unless GPR evidence is present.

