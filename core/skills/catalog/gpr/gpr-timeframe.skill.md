---
name: gpr-timeframe
description: GPR timeframe interpretation for Billing_Date, Year, Quarter, YoY, YTD, TTM, and renewals.
flow: gpr
scope: [planner, sql, response]
triggers: [yoy, year over year, year-over-year, last year, prior year, previous year, latest, recent, ytd, ttm, trailing twelve, rolling 12, month-on-month, mom, quarter, renewal, renewals, expiry, growth, grow, grew, trend, declining, decline, increasing, decreasing, over time, over the years, trajectory]
priority: 75
---

[GPR TIMEFRAME]
- Use explicit `Year` and `Quarter` filters when the query names them.
- Use `Billing_Date` for rolling, trailing, YTD, monthly, and date-range logic.
- For latest period, use the max available period in the dataset.
- For renewal/expiry questions, use `Cover_Expiry_Date` instead of `Billing_Date`.
- In the response, always state the timeframe used.

Default timeframe (no period given): see the always-on `gpr-default-timeframe`
rule — latest available year, never an all-years aggregate.

YoY when years are not specified:
- Default a YoY comparison to the latest year vs the immediately prior year:
  `Year = MAX(Year)` against `Year = MAX(Year) - 1`. Return both periods.

Identical / aligned periods (partial latest year):
- Always compare like-for-like windows. If the latest year is incomplete — its
  data only reaches some quarter/month (e.g. only through Q1) — bound BOTH years
  to that same elapsed window: latest-year-through-Q1 vs prior-year-through-Q1.
- Determine the cut-off from the data: `latest_q = MAX(Quarter)` (or month from
  `MAX(Billing_Date)`) within `MAX(Year)`, then constrain the prior year to
  `Quarter <= latest_q` (or the same month/date-of-year) so neither side carries
  periods the other lacks.
- Never compare a partial current year against a full prior year; that overstates
  a decline. State the aligned window used (e.g. "YTD through Q1, YoY").
