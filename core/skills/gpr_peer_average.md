---
name: gpr-peer-average
description: Peer group lookup, aggregation, and confidentiality rules for GPR.
flow: gpr
scope: [planner, sql, response]
triggers: [peer, peers, peer average, peer group, vs peers, against peers, peer comparison, competitor]
priority: 90
---

[GPR PEER AVERAGE]
- Resolve peers from `Peers` using the selected `Carrier_Group` and optional `Country`.
- Use the resolved `Overall_Peer_Group` values to filter `GPR`.
- Apply all non-carrier user filters to both carrier and peer calculations.
- Return only aggregated peer metrics, never individual peer names.
- For peer premium, use an aggregate labelled `peer_average_premium`.
- If comparing carrier vs peers, return carrier aggregate and peer aggregate side by side.
