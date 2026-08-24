---
name: survey-timeframe
description: Interpretation of relative time references (YoY, last year, recent, latest) against the Survey_Year column.
flow: survey
scope: [planner]
triggers: [yoy, y-o-y, year over year, year-over-year, last year, prior year, previous year, recent, recently, latest, most recent, this year, current year, trend, improvement, improving, declining, over time, over the years]
priority: 60
---

- For YoY growth, YoY change or YoY Score, if specific years are not mentioned consider the most recent two years from the dataset.
- Ensure relative or vague time references in the user query (like last year, recent period, latest survey, etc.)
  are correctly interpreted using the Survey_Year column before generating the reasoning plan.
  Example:- If the user query mentions "last year", interpret it as:
            Survey_Year = (MAX(Survey_Year) - 1)
- Default timeframe (no year named): see the always-on `survey-default-timeframe`
  rule — latest survey year, never an all-years average.
- YoY without explicit years: compare the latest year vs the immediately prior
  year, `Survey_Year = MAX(Survey_Year)` against `Survey_Year = MAX(Survey_Year) - 1`,
  and return both periods.
- Aligned periods: compare like-for-like. If the latest survey year is only
  partially collected (data through an early wave/quarter), restrict the prior
  year to the same elapsed window before computing YoY — never compare a partial
  latest year against a full prior year. State the aligned window used.
