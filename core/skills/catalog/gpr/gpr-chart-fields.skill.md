---
name: gpr-chart-fields
description: GPR (premium) field-priority and bar-mode rules for charts.
flow: gpr
scope: [chart]
always: true
priority: 75
---

[GPR / PREMIUM — FIELD PRIORITY FOR x AND series]

Pick `x` (and then fill `series` from what remains) using this priority order of
categorical fields, highest first:
  a) Year — when the premium was billed/invoiced (use for time trends → line).
  b) Region — broad geography (North America, EMEA, APAC, LatAm).
  c) Country — where the policy/risk/client sits (US, Canada, Singapore).
  d) Carrier_Group — parent grouping of carriers (e.g. AIG). NEVER Carrier_Name.
  e) ONE of (equal priority, pick by context): Product_Line / Cover_Line / Segment.

`y` (measures): Premium, Share_of_Wallet, Share_of_Portfolio, Appetite, Growth_%,
etc. — whatever numeric premium metric the SQL returned.

Assignment:
- For `scatter`, `x` is instead a numeric measure (see chart-scatter).
- Otherwise `x` = the highest-priority categorical field present.
- `series` = the remaining relevant categorical fields, highest priority first,
  excluding `x` and `y`. Prefer a SINGLE most-decision-relevant series.

[BAR MODE for GPR — one entry per series]
- `stack` when the series is a component breakdown of a carrier's book —
  Product_Line, Cover_Line, or Segment (the parts sum to the total).
- `group` otherwise (e.g. comparing Carrier_Group or Region side by side).

[COMBO / WATERFALL for GPR]
- Premium (bars) + a rate like Growth_% or Share_of_Wallet (secondary-axis line)
  → `combo` with that rate in `secondary_y`.
- Premium movement / bridge (opening → new business → rate → churn → closing) →
  `waterfall`.

Confidentiality: peers are ALWAYS aggregated — chart a single "Peer avg" series,
never one series per named peer. Marsh is the market proxy and may be named.

The exact field names may differ in the SQL output; map to the closest matching
column and ALWAYS use the EXACT column name present in `sql_output`.
