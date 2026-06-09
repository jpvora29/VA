---
name: survey-confidentiality-aggregation
description: Peer confidentiality + AVG() aggregation requirements for every Survey + GPR planner output. Peers must never be exposed individually.
flow: survey
scope: [planner]
always: true
priority: 90
---

[CONFIDENTIALITY AND AGGREGATION RULES]

1. Always use **average values** for all metrics when aggregating data for carriers, products, countries, or any other dimension.
- Example: Instead of showing raw score sum of scores, show the average score or average score for that group.
- If data is grouped by multiple dimensions (e.g., Product + Country), calculate the average within each group.

2. For **peer-level metrics**, never display or calculate results for individual peers.
- Only compute the **average peer score or value** for the selected carrier or filter combination.
- Never reveal individual peer-level data — this is a **confidentiality constraint**.

3. For all metrics involving comparisons (Carrier vs Peer):
- Compute both sides as **average values**.
- The comparison should be Carrier’s average vs Peer Average score.
- Avoid using raw or total values unless explicitly requested.

4. When generating reasoning steps or query plans:
- Explicitly state when an average is being computed (e.g., “Calculate average score per carrier”).
- For peer metrics, explicitly write “Calculate peer average only, not individual peers”.

5. Do not include carrier identifiers for peers.
- Only refer to them collectively as “Peers” or “Peer Group”.

These rules apply to all reasoning and planning outputs, regardless of metric type (score, nps, response count).
