---
name: gpr-marsh-market
description: Marsh book / total market premium rules for GPR.
flow: gpr
scope: [planner, sql, response]
triggers: [marsh, marsh book, market premium, total market, book of business]
priority: 80
---

[MARSH / MARKET VIEW]
- Marsh is the broker/market book, not a carrier and not a client.
- Marsh premium means `SUM(Premium)` from `GPR` after applying all user filters except `Carrier_Group`.
- Never fuzzy-match `Marsh` to `Carrier_Group` or `CLIENT_NAME`.
- For carrier vs Marsh comparisons, return carrier premium and market premium for the same non-carrier filters.
