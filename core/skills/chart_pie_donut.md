---
name: chart-pie-donut
description: Detailed guidance for pie and donut (part-to-whole) charts.
flow: cross
scope: [chart]
always: true
priority: 70
---

[PIE / DONUT CHART — `chart_type='pie'` or `'donut'`]

When: showing how a single total splits into components — a part-to-whole share.
Use ONLY when categories are few (≤6 meaningful slices) and they sum to a
meaningful whole. Prefer `donut` (cleaner, shows a center total) over `pie`.

Field mapping:
- `x` = the category column whose values become the slices (e.g. Segment,
  Product_Line, Section).
- `y` = a LIST with exactly ONE measure column (the slice size, e.g. `["Premium"]`).
- `series` = `[]` (pie/donut ignore series; use ONE breakdown only).
- `bar_mode` = `[]`.
- `y_agg` = `sum` (slices are summed per category).

Worked examples:
- "Premium mix by segment" → donut, x=Segment, y=[Premium].
- "Share of portfolio by product line" → donut, x=Product_Line, y=[Share_of_Portfolio].
- "Score contribution by survey section" → donut, x=Section, y=[Score].

Behaviour & mistakes:
- The engine auto-collapses a long tail into "Other" beyond ~8 slices, but if the
  question has many categories, use `bar` instead — a crowded donut is unreadable.
- Do NOT use pie/donut for time trends or for comparing independent (non-summing)
  quantities.
- Never put more than one column in `y`.
