---
name: gpr-planner-base
description: Baseline planning rules for all GPR premium analytics questions.
flow: gpr
scope: [planner]
always: true
priority: 100
---

[GPR PLANNER BASE]
- Plan only; do not write SQL.
- Use `GPR` for premium/financial analytics and `Peers` only when peer context is requested.
- Use `Carrier_Group` for carrier filters and grouping.
- Use only filters and dimensions stated in the user query or inherited context.
- Treat `Premium` as a financial metric; default aggregation is `SUM(Premium)`.
- Put every requested breakdown dimension into `group_by`.
- Do not expose individual peer names in the plan.
- State the exact calculation needed for derived metrics.
