---
name: gpr-default-timeframe
description: Always-on default timeframe — no year/quarter/date named means latest available year, never an all-years aggregate.
flow: gpr
scope: [planner, sql]
always: true
priority: 90
---

[GPR DEFAULT TIMEFRAME — applies when the query names NO year/quarter/date]
- Default to the latest available year: `Year = (SELECT MAX(Year) FROM GPR)`.
- NEVER aggregate across all years by default — an unfiltered SUM over every
  year silently mixes periods and overstates totals.
- Always state the year you defaulted to in the response (e.g. "for 2025, the
  latest available year").
- This rule is the no-time-words case. If the query DOES carry a time reference
  (YoY, last year, TTM, rolling, quarter, renewal...), the gpr-timeframe rules
  take over.
