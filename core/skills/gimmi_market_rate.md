---
name: gimmi-market-rate
description: GIMMI market composite rate meaning and calculation rules.
flow: gimmi
scope: [sql, response]
always: true
priority: 85
---

[GIMMI MARKET RATE]
- GIMMI answers market composite rate changes, not carrier premium.
- `Market_Composite_Rate` is stored as a decimal rate; present it as a percentage by multiplying by 100.
- If product is missing, use `Product = 'Overall'`.
- If quarter is missing, return all available quarters for the selected/latest year.
- Region is required for a meaningful GIMMI query.
