---
name: chart-field-mapping
description: Shared chart field mapping rules aligned to ChartOutput.
flow: cross
scope: [chart]
always: true
priority: 80
---

[CHART FIELD MAPPING]
- Use exact column names from `sql_output` for `x`, `y`, `series`, and title references.
- `x` must be a single string.
- `y` must be a list of numeric measure columns.
- `series` must be a list of categorical columns excluding `x` and all `y` values.
- `bar_mode` must contain only `group` or `stack`; use an empty list when chart type is not `bar`.
- If a required field cannot be selected from `sql_output`, set `chart_type` to `none`.
