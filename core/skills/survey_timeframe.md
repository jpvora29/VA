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
