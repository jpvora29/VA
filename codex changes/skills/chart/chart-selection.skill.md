---
name: chart-selection
description: Chart type decision rules and exact chart_type enum contract.
flow: cross
scope: [chart]
kind: chart
priority: 95
risk_level: medium
always: true
metrics: []
---

## Chart Type Contract

Allowed values:

- `bar`
- `line`
- `pie`
- `donut`
- `scatter`
- `waterfall`
- `combo`
- `none`

## Selection Rules

- Use `bar` for category comparison and rankings.
- Use `line` only for real temporal progression, not merely because a `Year`
  column exists.
- Use `combo` for premium plus rate/share movement over time.
- Use `scatter` only when two numeric measures exist at the same grain.
- Use `pie` or `donut` only for part-to-whole with a small category count.
- Use `waterfall` only for bridge/movement decomposition.
- Use `none` for scalar results, empty rows, or unchartable text.

## Line Chart Gate

Before choosing `line`, all of these must be true:

- The user asks for movement, trend, change over time, YoY, MoM, rolling,
  quarterly/monthly trajectory, or the SQL output is explicitly ordered as a time
  series.
- The x field is a true time field: date, month, quarter, year-quarter, or year
  used as a time progression.
- There are at least two distinct time periods.
- The chart is not primarily comparing categories within each year.

If `Year` appears only as a filter or as a discrete comparison bucket, use `bar`.

## Year Axis Rules

- `Year` is a discrete category unless the question is explicitly about trend.
- Never render year ticks as decimals.
- If x is `Year`, force categorical or integer ticks: `2023`, `2024`, `2025`.
- If the data has multiple rows per year and another category such as product,
  carrier, segment, section, or country, use grouped/stacked `bar` with `Year`
  as x and that category as `series`, unless the user explicitly requested a
  trend line.

## Examples

- "Premium by year for Zurich from 2023 to 2025" -> `line`, x=`Year`.
- "Premium by product for each year" -> `bar`, x=`Year`, series=`Product_Line`.
- "Top carriers in 2024 and 2025" -> `bar`, x=`Year`, series=`Carrier_Group`.
- "YoY premium trend" -> `line`, x=`Year`.
- "Score by section for 2024" -> `bar`, x=`Section`.

## Forbidden Mistakes

- Do not invent fields not present in SQL output.
- Do not pick a chart if the result has only one row and one measure.
- Do not use approximate enum names.
- Do not choose `line` only because `Year` exists.
- Do not allow fractional year ticks such as `2024.2`.
