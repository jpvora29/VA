---
name: gimmi-market-rate
description: GIMMI market composite rate meaning, query shape, and response rules.
flow: gimmi
scope: [sql, response]
kind: metric
priority: 85
risk_level: medium
always: true
tables: [GIMMI]
columns: [Region, Product, Year, Quarter, Market_Composite_Rate]
metrics: [market_composite_rate]
---

## Definition

GIMMI answers market COMPOSITE RATE change by region, product, year, and quarter —
not carrier premium. `Market_Composite_Rate` is stored as a decimal rate.

## Expected SQL Shape

- Query ONLY the `GIMMI` table.
- Region is required for a meaningful GIMMI query; require region/product/time
  filters when the user asks for a specific market rate.
- If product is missing, use `Product = 'Overall'`.
- If quarter is missing, return all available quarters for the selected (or
  latest) year.
- Order by year then quarter chronologically when showing movement.

## Response Rules

- Present the rate as a percentage by multiplying the decimal by 100.
- Lead with a compact table.
- Mention direction (up/down) only when multiple periods support it.
- Do NOT connect GIMMI rate movement to carrier premium unless GPR evidence is
  also present.

## Forbidden Mistakes

- Do not report GIMMI rate as a raw decimal without converting to a percentage.
- Do not treat the composite rate as a premium amount.
