---
name: chart-type-selection
description: Shared chart type selection rules using exact ChartOutput enum values.
flow: cross
scope: [chart]
always: true
priority: 90
---

[CHART TYPE SELECTION]
- Use exact enum values only: `bar`, `line`, `pie`, `donut`, `scatter`, `none`.
- Use `none` for single scalar outputs or when no categorical/time column exists.
- Use `line` for temporal progressions such as year, quarter, month, YoY, rolling, or month-on-month.
- Use `bar` for one or more numeric measures compared across discrete categories.
- Use `pie` or `donut` only for part-to-whole percentages with six or fewer categories.
- Use `scatter` only when both x and y are numeric measures.
