---
name: survey-peer-average
description: Peer Average / peer score calculation for Survey flow — Peers table lookup followed by Carriers table filter.
flow: survey
scope: [planner]
triggers: [peer, peers, peer average, peer score, peer group, vs peers, against peers, compared to peers, peer comparison, competitor, rival, competition]
priority: 70
---

[DOMAIN METRICS]
- When query asks about Peer Average or peer score:
1. Query the `Peers` table first.
    - Apply `Carrier` filter
    - Apply `Country` and `Practice` filters only if explicitly mentioned in the query or derived from context.
    - Get the unique list of `Peers`.
2. Use this list to filter the `Carriers` table.
    - Apply all other user filters (year, region, attribute, section, etc.).
    - Compute the Peer Average score for that group.
