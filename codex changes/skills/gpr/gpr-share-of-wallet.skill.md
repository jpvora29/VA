---
name: gpr-share-of-wallet
description: Share of Wallet definition, calculation, SQL shape, response wording, and report usage.
flow: gpr
scope: [planner, sql, response, pitch]
kind: metric
priority: 90
risk_level: high
triggers: [sow, share of wallet, wallet share, share in marsh book, marsh book share]
requires: [gpr-marsh-market, cross-sql-readonly-safety]
tables: [GPR]
columns: [Premium, Carrier_Group, Country, Product_Line, Business_Line, Client_Segment, Year]
metrics: [share_of_wallet, premium]
examples:
  - user_query: What is Zurich share of wallet in Canada by product?
    expected_sql_shape: carrier premium divided by Marsh total premium for each product slice
test_queries:
  positive: [Zurich SoW in Canada, share in Marsh book by product]
  negative: [Zurich survey score in Canada]
---

## Definition

Share of Wallet is the selected carrier premium divided by total Marsh-book
premium for the same filters and breakdown slice.

## Expected Plan Shape

- Metric: `share_of_wallet`.
- Numerator: `SUM(Premium)` filtered to the selected `Carrier_Group`.
- Denominator: `SUM(Premium)` for the same country/year/product/segment filters,
  without the carrier filter.
- Group by every requested breakdown dimension.

## Expected SQL Shape

Use CTEs or subqueries:

```sql
WITH carrier AS (... WHERE Carrier_Group = ...),
market AS (... same filters except Carrier_Group ...)
SELECT ..., ROUND(carrier_premium / NULLIF(market_premium, 0) * 100, 1) AS SoW
```

## Response Rules

- Refer to the metric as "Share of Wallet" or "SoW".
- Include the premium numerator and market denominator when available.
- Do not imply cause unless evidence includes the driver.

## Forbidden Mistakes

- Do not divide by peer premium unless the user explicitly asks for peer benchmark.
- Do not use `Carrier_Name`; use `Carrier_Group`.
- Do not apply a carrier filter to the denominator.

