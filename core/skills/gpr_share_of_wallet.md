---
name: gpr-share-of-wallet
description: Definition and calculation rules for Share of Wallet in GPR data.
flow: gpr
scope: [planner, sql, response]
triggers: [sow, share of wallet, wallet share, share in marsh book, marsh book share]
priority: 85
---

[SHARE OF WALLET]
- Definition: carrier premium divided by total market premium for the same filters.
- Numerator: `SUM(Premium)` with the selected `Carrier_Group` filter.
- Denominator: `SUM(Premium)` with all non-carrier filters and no `Carrier_Group` filter.
- Apply country, region, product, segment, industry, and timeframe filters equally to numerator and denominator.
- SQL percentage formula: `ROUND(100.0 * numerator / NULLIF(denominator, 0), 1)`.
- Response label: `Share of Wallet`.
