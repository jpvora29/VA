---
name: chart-axis-normalization
description: Deterministic axis typing, year tick formatting, and chart override rules.
flow: cross
scope: [chart, validation]
kind: chart
priority: 98
risk_level: high
always: true
metrics: []
---

## Purpose

Chart rendering must protect users from poor LLM chart specs. If the LLM chooses
an unsuitable chart type or axis, deterministic post-processing should correct it
before Plotly renders.

## Year Axis Contract

- Treat year-like columns as categorical unless the chart is an explicit time
  trend.
- Year-like columns include: `Year`, `Survey_Year`, `Policy_Year`,
  `Billing_Year`, and aliases ending in `_Year`.
- Display year ticks as whole labels only: `2023`, `2024`, `2025`.
- Never let Plotly infer a continuous numeric year axis that creates fractional
  ticks such as `2024.2`.

## Deterministic Overrides

Override `line` to `bar` when:

- x is not a date/month/quarter/year-like field.
- x is year-like but the query intent is category comparison, ranking, mix,
  top/bottom, or breakdown.
- there is only one distinct period.
- there are multiple rows per year split by a category and the user did not ask
  for trend/movement.

Keep `line` only when:

- the user intent or metric is explicitly temporal: trend, movement, YoY, MoM,
  QoQ, rolling 12, over time, trajectory, increasing, declining.
- at least two distinct periods exist.
- x represents ordered time.

## Sorting Rules

- Sort year-like categories numerically ascending for trend charts.
- For comparison bars, sort by requested order or by measure descending.
- For month names, use calendar order rather than alphabetical order.
- For quarter labels, sort `Q1`, `Q2`, `Q3`, `Q4` within year.

## Forbidden Mistakes

- Do not render a line chart for carrier/product/segment/country comparison just
  because a year column is present.
- Do not use a numeric continuous axis for discrete years.
- Do not connect unrelated categories with a line.

