---
name: dimensional_breakdown
description: Split the headline metric by the dimension that best explains it (product, industry, segment, region).
applies_when: a headline/aggregate metric is asked and the user would benefit from knowing what is driving it; or a later step needs the "top" member of a dimension.
requires: [GPR]
---

Decompose an aggregate to find what drives it and to identify the leading
member of a dimension (often a prerequisite for whitespace/opportunity steps).

**Dimensions available (GPR / Marsh book)**
- `Product_Line` (e.g. Property, Casualty, FINPRO)
- `SIC_Major_Class` / `SIC_Minor_Class` — the **industry** dimension
- `Client_Segment`
- `Region` / `Country`

**Preferred: compute it, do not query it**
- The split = `compute_metric(name='compute_breakdown', group_by=['<dimension>'])`.
- Where the carrier stands per member = `compute_metric(name='compute_rank', ...)`.
- YoY per member = `compute_metric(name='compute_yoy_to_date', group_by=[...])`.

**SQL shape (fallback only, for what the above does not cover)**
- `GROUP BY` the chosen dimension with `SUM(Premium)` (and YoY per member where
  trend matters), ordered descending, for the carrier slice.
- To find the "top product"/"top industry" for a downstream step, return the
  members ranked by premium so the agent can pick the leader and pass it on.

**Interpretation**
- Lead with the strongest and weakest members; do not list every member.
- Prioritize members that materially move the total or show notable momentum.
