---
name: gpr-timeframe
description: GPR timeframe interpretation for Billing_Date, Year, Quarter, YoY, YTD, TTM, and renewals.
flow: gpr
scope: [planner, sql, response]
triggers: [yoy, year over year, year-over-year, last year, prior year, previous year, latest, recent, ytd, ttm, trailing twelve, rolling 12, month-on-month, mom, quarter, renewal, renewals, expiry]
priority: 75
---

[GPR TIMEFRAME]
- Use explicit `Year` and `Quarter` filters when the query names them.
- Use `Billing_Date` for rolling, trailing, YTD, monthly, and date-range logic.
- For latest period, use the max available period in the dataset.
- For YoY, compare equivalent periods and return both periods.
- For renewal/expiry questions, use `Cover_Expiry_Date` instead of `Billing_Date`.
- In the response, always state the timeframe used.
