---
name: gpr-share-of-portfolio
description: Share of Portfolio definition and rules for product mix, formerly called Appetite.
flow: gpr
scope: [planner, sql, response, pitch]
kind: metric
priority: 88
risk_level: high
triggers: [appetite, share of portfolio, portfolio share, product mix, portfolio mix]
requires: [cross-sql-readonly-safety]
tables: [GPR]
columns: [Premium, Carrier_Group, Product_Line, Business_Line, Country, Year]
metrics: [share_of_portfolio, premium]
---

## Definition

Share of Portfolio is the share of a carrier's own premium allocated to a
product, business line, segment, region, or other requested slice. It is not the
same as Share of Wallet.

## Expected SQL Shape

- Numerator: `SUM(Premium)` for carrier plus requested breakdown slice.
- Denominator: `SUM(Premium)` for the same carrier and same base filters, without
  the breakdown filter.
- Use `NULLIF()` for the denominator.

## Response Rules

- Use "Share of Portfolio" in user-facing prose.
- If the user says "appetite", translate it to "Share of Portfolio".
- Pair the percentage with premium where evidence includes premium.

## Forbidden Mistakes

- Do not call this Share of Wallet.
- Do not use Marsh total premium as denominator.
- Do not use peer premium as denominator.

