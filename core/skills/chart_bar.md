---
name: chart-bar
description: Detailed guidance for grouped and stacked bar charts.
flow: cross
scope: [chart]
always: true
priority: 70
---

[BAR CHART — `chart_type='bar'`]

When: comparing one or more numeric measures across discrete categories
(Carrier, Product, Country, Segment, Industry) for a single period, or one
measure split by a second category.

Field mapping:
- `x` = the primary category (highest-priority categorical field for the flow).
- `y` = the measure(s), e.g. `["Premium"]` or two same-unit measures
  `["Score_2023","Score_2024"]`.
- `series` = the secondary category that defines colour groups (e.g. Carrier
  within each Product). Exclude x and y.
- `bar_mode` = one entry per `series`:
  - `stack` when the series parts SUM to the x-category total (component mix —
    Product_Line, Cover_Line, Segment building up a carrier's premium).
  - `group` when the series are independent comparisons side by side (e.g.
    carriers compared within each product).
- `sort='desc'` for ranking / top-N questions.

Worked examples:
- "Premium by product line for each carrier" → x=Product_Line, y=[Premium],
  series=[Carrier_Group], bar_mode=[group].
- "Carrier premium broken down by segment" (parts of a whole) → x=Carrier_Group,
  y=[Premium], series=[Segment], bar_mode=[stack].
- "Top 10 countries by premium" → x=Country, y=[Premium], series=[], bar_mode=[],
  sort='desc'.

Common mistakes to avoid:
- Putting a categorical column in `y` (y is numeric only).
- `bar_mode` length not matching `series` length.
- Using a bar chart for a clear time trend (use `line`) or for amount-vs-rate
  (use `combo`).
