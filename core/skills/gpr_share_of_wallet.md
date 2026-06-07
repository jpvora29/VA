---
name: gpr-share-of-wallet
description: Share of Wallet definition, calculation, SQL shape, and response wording for GPR.
flow: gpr
scope: [planner, sql, response]
kind: metric
priority: 85
risk_level: high
triggers: [sow, share of wallet, wallet share, share in marsh book, marsh book share]
requires: [gpr-marsh-market, cross-sql-readonly-safety]
tables: [GPR]
columns: [Premium, Carrier_Group, Country, Region, Product_Line, Business_Line, Client_Segment, Year]
metrics: [share_of_wallet, premium]
examples:
  - user_query: What is Zurich share of wallet in Canada by product?
    expected_sql_shape: carrier premium divided by Marsh-book total premium for each product slice
test_queries:
  positive: [Zurich SoW in Canada, share in Marsh book by product, wallet share by segment]
  negative: [Zurich survey score in Canada, Zurich appetite by product]
---

## Definition

Share of Wallet (SoW) is the selected carrier's premium divided by the total
Marsh-book (market) premium for the SAME filters and breakdown slice. The GPR
table is Marsh's book of business, so the denominator is market premium with no
carrier filter.

## When To Use

- The user asks for "share of wallet", "SoW", "wallet share", or "share in the
  Marsh book".
- NOT for "appetite" / "share of portfolio" — that is a carrier's own product mix
  (see gpr-share-of-portfolio), whose denominator is the carrier's own premium.

## Required Evidence

- Carrier premium for the requested slice.
- Marsh-book (market) premium for the same non-carrier filters (see
  gpr-marsh-market for the denominator contract).

## Expected Plan Shape

- Metric: `share_of_wallet`.
- Numerator: `SUM(Premium)` filtered to the selected `Carrier_Group`.
- Denominator: `SUM(Premium)` for the same country / region / product / segment /
  industry / timeframe filters, WITHOUT any `Carrier_Group` filter.
- Apply every non-carrier filter equally to numerator and denominator.
- Group by each requested breakdown dimension.

## Expected SQL Shape

Compute both legs in one pass; never apply the carrier filter to the denominator:

```sql
SELECT
    <breakdown_dimension>,
    ROUND(
        100.0
        * SUM(CASE WHEN Carrier_Group = '<carrier>' THEN Premium END)
        / NULLIF(SUM(Premium), 0),
        1
    ) AS share_of_wallet
FROM GPR
WHERE <same non-carrier filters: country/region/product/segment/year>
GROUP BY <breakdown_dimension>;
```

The percentage formula is `ROUND(100.0 * numerator / NULLIF(denominator, 0), 1)`.

## Response Rules

- Label the metric "Share of Wallet" (or "SoW").
- Pair the percentage with the underlying premium numerator and market
  denominator when the evidence includes them.
- Do not imply causation unless the evidence includes the driver.

## Forbidden Mistakes

- Do not divide by peer premium (that is a peer benchmark, not SoW).
- Do not apply a `Carrier_Group` filter to the denominator.
- Do not use `Carrier_Name`; always use `Carrier_Group`.
- Do not confuse SoW with Share of Portfolio / appetite.
