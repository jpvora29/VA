---
name: chart-waterfall
description: Detailed guidance for waterfall (bridge / movement) charts.
flow: cross
scope: [chart]
always: true
priority: 70
---

[WATERFALL CHART — `chart_type='waterfall'`]

When: decomposing a CHANGE into its drivers — a "bridge" from a starting value to
an ending value through signed contributions. Classic uses: a premium walk
(opening book → new business → rate change → exposure → churn → closing book), a
YoY premium movement, or a budget-to-actual variance.

The data must be a SEQUENCE OF ORDERED STEPS: one row per step, in the order they
should appear left-to-right, with a SIGNED delta per step (positive = increase,
negative = decrease).

Field mapping:
- `x` = the step/label column (e.g. Movement, Driver, Component) in display order.
- `y` = a LIST with ONE column: the SIGNED change for each step (e.g. `["Delta"]`,
  `["Premium_Change"]`).
- `series` = `[]`.
- `bar_mode` = `[]`.
- `waterfall_measures` = a list, ONE entry per step in the same order, each:
  - `relative` — a +/- movement that adds onto the running total.
  - `total` — an absolute anchor bar (the opening base, a subtotal, or the closing
    total).
  Leave EMPTY to treat every step as `relative`; the engine then appends a closing
  `Total` bar automatically.

Worked examples:
- Premium bridge with explicit anchors: x=Movement
  (rows: Opening, New Business, Rate, Churn, Closing), y=[Premium_Change],
  waterfall_measures=["total","relative","relative","relative","total"].
- Driver decomposition without anchors: x=Driver, y=[Contribution],
  waterfall_measures=[] (engine adds the final Total).

Common mistakes:
- Unordered steps — make sure the SQL returns rows in the intended bridge order.
- Putting a category that should be compared side-by-side here (that is `bar`).
- More than one column in `y`.
