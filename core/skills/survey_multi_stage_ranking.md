---
name: survey-multi-stage-ranking
description: Two-level (top N of X, then top M of Y) ranking pattern. Triggered by top/best/highest/ranking phrasings.
flow: survey
scope: [planner]
triggers: [top, best, highest, lowest, bottom, rank, ranking, leader, leaders, biggest, largest, worst]
priority: 80
---

[MULTI-STAGE RANKING AND SUB-QUERY RULES]
- When a user query requests for top N carriers and top M attributes (or any two-level ranking):
1. Always perform it in two distinct stages:
    a. First sub-query: Identify the top N carriers based on their average score.
    b. Second sub-query: For those top carriers, identify the top M attributes for each carrier.
2. Apply separate LIMIT clauses for each stage, not a single global LIMIT.
3. Return combined results showing all top carriers with their top attributes.
4. Always use sub-queries or WITH clauses instead of JOINs.
