---
name: gpr-share-of-portfolio
description: Definition and calculation rules for Share of Portfolio, formerly called Appetite.
flow: gpr
scope: [planner, sql, response, pitch]
triggers: [appetite, share of portfolio, portfolio share, product mix, portfolio mix]
priority: 85
---

[SHARE OF PORTFOLIO]
- Definition: a carrier's premium share within its own portfolio for a requested dimension.
- Use `Share of Portfolio` in final text even if the user says `appetite`.
- Numerator: `SUM(Premium)` for the carrier and the requested dimension value.
- Denominator: `SUM(Premium)` for the same carrier across all values of that dimension.
- SQL percentage formula: `ROUND(100.0 * numerator / NULLIF(denominator, 0), 1)`.
- Group by the requested breakdown dimension, for example `Product_Line`, `Business_Line`, or `Client_Segment`.
