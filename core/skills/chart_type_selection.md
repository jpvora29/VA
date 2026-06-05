---
name: chart-type-selection
description: Master decision tree for choosing the chart_type enum value.
flow: cross
scope: [chart]
always: true
priority: 90
---

[CHART TYPE SELECTION — decide `chart_type` first, then read the matching per-type skill]

Allowed `chart_type` enum values ONLY: `bar`, `line`, `pie`, `donut`, `scatter`,
`waterfall`, `combo`, `none`.

Step 1 — Is there anything to chart?
- If the result is a single scalar / KPI (one number, no breakdown) → `none`.
- If there is NO categorical or time column to put on an axis → `none`.

Step 2 — What is the user really asking? Match intent to type:
- **Trend over time** (Year, Quarter, Month, rolling-12, MoM, YoY) → `line`.
- **Movement / bridge / "what drove the change"** — an opening value adjusted by
  signed contributions to a closing value (e.g. premium walk: opening → new
  business → rate → churn → closing) → `waterfall`.
- **Two measures on different scales together** — an absolute amount AND a rate/%
  for the same categories (e.g. Premium bars + Growth% line, Premium + SoW%) →
  `combo`.
- **Part-to-whole share** — components summing to a meaningful 100% with ≤6
  categories (portfolio mix, appetite split, score by section) → `donut`
  (preferred) or `pie`.
- **Correlation** — relationship between TWO numeric measures, one per axis
  (e.g. SoW% vs Growth%, Score vs NPS) → `scatter`.
- **Comparison across discrete categories** (default) — one or more measures
  across categories like Carrier, Product, Country, Segment → `bar`.

Step 3 — Disambiguation of the common confusions:
- More than one year of data present → prefer `line` over `bar`.
- Exactly one period, comparing categories → `bar`, not `line`.
- Comparing two measures of the SAME unit across the same categories → `bar`
  (two y columns). Of DIFFERENT units (amount vs %) → `combo`.
- > 6 categories for a share question → `bar`, not `pie`/`donut`.

Step 4 — After picking the type, follow the dedicated per-type skill below for
exact field mapping, and the flow-specific field-priority skill for which columns
go on x / y / series.

Do NOT invent columns. Every field you set must be an EXACT column name from
`sql_output` (see chart-field-mapping).
