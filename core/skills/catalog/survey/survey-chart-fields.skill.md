---
name: survey-chart-fields
description: Survey field-priority and bar-mode rules for charts.
flow: survey
scope: [chart]
always: true
priority: 75
---

[SURVEY — FIELD PRIORITY FOR x AND series]

Pick `x` (and then fill `series` from what remains) using this priority order of
categorical fields, highest first:
  a) Year — the survey/reporting year (use for time trends → line).
  b) Region — broad geography (North America, EMEA, APAC, LatAm).
  c) Country — where the survey/business sits (US, Canada, Singapore).
  d) Carrier — the insurer being rated.
  e) ONE of (equal priority, pick by context):
       Practice (line of business: Property, Casualty, Cyber, Marine) /
       Section (service area: Underwriting, Claims, Policy Servicing) /
       Attribute (specific question: Responsiveness, Accuracy) /
       Segment (Large Corporate, Mid-Market).

`y` (measures): Score, Score_Growth_%, NPS, etc. — the numeric survey metric the
SQL returned. Use `y_agg='mean'` for scores when multiple rows share a key.

Assignment:
- For `scatter`, `x` is instead a numeric measure (e.g. Score vs NPS).
- Otherwise `x` = the highest-priority categorical field present.
- `series` = the remaining relevant categorical field(s), highest priority first,
  excluding `x` and `y`. Prefer a SINGLE most-decision-relevant series.

[BAR MODE for SURVEY — one entry per series]
- Use `group` (survey scores are compared side by side, they do not sum to a
  total). Only use `stack` if the measure genuinely decomposes a whole.

[DONUT / LINE for SURVEY]
- Score share across Sections (≤6) → `donut`.
- Rolling-12 / MoM / YoY score → `line`.

Confidentiality: peers are ALWAYS aggregated — never chart an individual peer
name; show a single aggregate ("Peer avg") instead.

The exact field names may differ in the SQL output; map to the closest matching
column and ALWAYS use the EXACT column name present in `sql_output`.
