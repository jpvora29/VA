---
name: chart-field-mapping
description: Field-level contract for the ChartOutput object (x, y, series, etc.).
flow: cross
scope: [chart]
always: true
priority: 80
---

[CHART FIELD MAPPING — the ChartOutput contract]

Use the EXACT column names from `sql_output` for every field (case and spelling
must match a real column). Fields:

- `chart_type` — one enum value (see chart-type-selection).
- `x` — a SINGLE column name (string). Usually the categorical / time dimension.
  For `scatter` it is a numeric measure instead.
- `y` — a LIST of numeric measure columns (e.g. `["Premium"]`,
  `["Score_2023", "Score_2024"]`). Never put a categorical column here.
- `series` — a LIST of categorical columns that split the data into colour groups
  in the legend. MUST exclude whatever is in `x` and `y`. Empty list when there is
  only one breakdown.
- `bar_mode` — only for `chart_type='bar'`: a list of `group` / `stack` markers,
  one per `series` entry. Empty list for every non-bar type.
- `secondary_y` — only for `chart_type='combo'`: the rate/% measure column(s)
  drawn as a LINE on the right-hand axis; the columns in `y` stay as bars on the
  left axis. Empty otherwise.
- `waterfall_measures` — only for `chart_type='waterfall'`: a list, one entry per
  X step in order, each `relative` (a +/- movement) or `total` (an absolute
  subtotal/total bar). Leave empty to make every step relative (the engine then
  appends a closing total).
- `y_agg` — aggregation when multiple rows share an x/series key: `sum`, `mean`,
  `count`, `median`, `min`, `max`, or `none`. Use `mean` for scores/rates, `sum`
  for amounts like premium.
- `sort` — `asc` / `desc` (by the first y) for rankings, else `none`.
- `title` — a short, specific title (metric + breakdown + period), e.g.
  "Premium by Product Line, 2024".

[ROBUSTNESS — the renderer is forgiving, so AIM for clean specs but don't fail]
- The engine reconciles near-miss column names, coerces measures to numeric,
  aggregates duplicates, and CAPS high-cardinality series into an "Other" bucket.
- Therefore prefer the clearest single breakdown; do NOT refuse to chart just
  because there are several categories. Pick the most decision-relevant dimension
  for `series` and leave the rest out.
- If, after honest effort, nothing in `sql_output` is chartable (pure scalar / no
  dimension), set `chart_type='none'`.
