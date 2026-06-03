---
name: gimmi-response-formatting
description: GIMMI market-rate response formatting (table-first, light read).
flow: gimmi
scope: [response]
always: true
priority: 70
---

[GIMMI RESPONSE FORMAT]
- Start with the heading `GIMMI Data`.
- Present all returned rows in a markdown table.
- Format market composite rate as a percentage rounded to one decimal place.
- Include product, year, quarter, and region for every row.

[LIGHT CONTEXTUAL READ]
- GIMMI is market data, so stay close to the numbers. You may add at most ONE plain sentence above the table noting the overall direction or range of the rate change actually shown (e.g. "Rates are easing across the quarters shown.").
- Do not speculate on causes, forecast, or add recommendations. If the data is empty, say so and add nothing else.
- Every figure must come from the SQL output.
