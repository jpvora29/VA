---
name: gpr-marsh-market
description: Marsh book as the market proxy — total/market premium denominator rules for GPR.
flow: gpr
scope: [planner, sql, response]
kind: domain
priority: 80
risk_level: medium
triggers: [marsh, marsh book, market premium, total market, book of business]
tables: [GPR]
columns: [Premium, Carrier_Group, Country, Region, Product_Line, Business_Line, Client_Segment, Year]
metrics: [market_premium, share_of_wallet]
---

## Definition

The GPR table IS Marsh's book of business and serves as the market proxy. "Marsh
premium" / "market premium" means `SUM(Premium)` across ALL carriers after
applying the user's non-carrier filters. Marsh is the broker/market book — it is
not a carrier and not a client.

## Expected SQL Shape

- Do NOT filter `Carrier_Group` when computing Marsh / market premium.
- Preserve every requested non-carrier filter (country, region, year, product,
  business line, segment, industry).
- For a breakdown, group by the requested dimension.
- For a carrier-vs-Marsh comparison, return the carrier premium and the market
  premium computed over the SAME non-carrier filters.

## Response Rules

- Say "Marsh book" or "market proxy" when explaining the denominator context.
- Do not imply this is the entire external insurance market unless the product
  explicitly defines it that way.

## Forbidden Mistakes

- Never fuzzy-match `Marsh` to a `Carrier_Group` or `CLIENT_NAME` value.
- Do not apply a carrier filter to a market-premium calculation.
