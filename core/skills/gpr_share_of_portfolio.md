---
name: gpr-share-of-portfolio
description: Share of Portfolio (formerly Appetite) definition, calculation, and response rules for GPR.
flow: gpr
scope: [planner, sql, response, pitch]
kind: metric
priority: 85
risk_level: high
triggers: [appetite, share of portfolio, portfolio share, product mix, portfolio mix]
requires: [cross-sql-readonly-safety]
tables: [GPR]
columns: [Premium, Carrier_Group, Product_Line, Business_Line, Client_Segment, Country, Year]
metrics: [share_of_portfolio, premium]
examples:
  - user_query: What is Zurich's appetite by product in Canada?
    expected_sql_shape: carrier slice premium divided by the carrier's own total premium for the same base filters
test_queries:
  positive: [Zurich appetite by product, share of portfolio by segment, product mix for Zurich]
  negative: [Zurich share of wallet, Zurich premium vs peers]
---

## Definition

Share of Portfolio (SoP) is the share of a carrier's OWN premium allocated to a
requested slice — product, business line, segment, region, etc. It describes the
carrier's internal mix ("appetite"), NOT its position against the market.

## When To Use

- The user asks for "appetite", "share of portfolio", "portfolio share", or
  "product mix".
- NOT for share against the market — that is Share of Wallet
  (see gpr-share-of-wallet), whose denominator is the Marsh book.

## Expected Plan Shape

- Metric: `share_of_portfolio`.
- Numerator: `SUM(Premium)` for the carrier plus the requested breakdown slice.
- Denominator: `SUM(Premium)` for the SAME carrier and same base filters, WITHOUT
  the breakdown filter (i.e. the carrier's own total for that base scope).
- Group by the requested breakdown dimension.

## Expected SQL Shape

```sql
SELECT
    Product_Line,
    ROUND(
        100.0 * SUM(Premium)
        / NULLIF(
            SUM(SUM(Premium)) OVER (),
            0
        ),
        1
    ) AS share_of_portfolio
FROM GPR
WHERE Carrier_Group = '<carrier>'
  AND <same base filters: country/year/segment>
GROUP BY Product_Line;
```

The denominator is the carrier's own total premium for the base filters; use
`NULLIF()` to guard the division.

## Response Rules

- Use "Share of Portfolio" in user-facing prose even if the user said "appetite".
- Pair the percentage with premium when the evidence includes premium.

## Forbidden Mistakes

- Do not call this Share of Wallet.
- Do not use Marsh total / market premium as the denominator.
- Do not use peer premium as the denominator.
- Do not use `Carrier_Name`; always use `Carrier_Group`.
