---
name: gpr-ranking
description: Ranking, top-N, bottom-N, and rank movement rules for GPR.
flow: gpr
scope: [planner, sql, response]
triggers: [rank, ranking, top, bottom, highest, lowest, leader, leaders, competitor, top 5]
priority: 80
---

[GPR RANKING]
- Ranking metrics should rank carriers by aggregated `SUM(Premium)` unless the query specifies another metric.
- For rank within a dimension, partition by that dimension and timeframe.
- For rank movement, return current rank, prior-period rank, and rank delta when available.
- Do not rank or disclose individual peer names when the query asks for peer comparison; return only carrier vs aggregated peer group.
