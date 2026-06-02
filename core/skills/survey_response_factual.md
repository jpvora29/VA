---
name: survey-response-factual
description: Survey factual response formatting and grounding rules.
flow: survey
scope: [response]
always: true
priority: 70
---

[SURVEY RESPONSE FORMAT]
- Answer only from the SQL output and query plan.
- Format score values with consistent precision.
- For peer comparisons, show only carrier aggregate vs peer aggregate.
- If more than three rows are returned, prefer a compact markdown table.
- Include the survey year/timeframe when present in the output or query plan.
- Do not add causes, recommendations, or business implications in factual response mode.
