---
name: gpr-marsh-market
description: Marsh book as market proxy for premium, Share of Wallet, and market context.
flow: gpr
scope: [planner, sql, response, pitch]
kind: domain
priority: 86
risk_level: medium
triggers: [marsh, marsh book, market premium, market share, total market, book of business]
tables: [GPR]
columns: [Premium, Country, Product_Line, Business_Line, Client_Segment, Year]
metrics: [market_premium, share_of_wallet]
---

## Definition

The GPR table represents Marsh's book of business. Market or Marsh-book premium
means premium across all carriers after applying the user-requested non-carrier
filters.

## Expected SQL Shape

- Do not filter `Carrier_Group` when calculating Marsh market premium.
- Preserve requested filters such as country, year, product, segment, and industry.
- For breakdowns, group by the requested dimension.

## Response Rules

- Say "Marsh book" or "market proxy" when explaining denominator context.
- Do not imply this is the entire external insurance market unless the product
  explicitly defines it that way.

