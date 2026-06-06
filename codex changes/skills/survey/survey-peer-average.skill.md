---
name: survey-peer-average
description: Survey peer average lookup and aggregation rules.
flow: survey
scope: [planner, sql, response, pitch]
kind: domain
priority: 88
risk_level: high
triggers: [peer, peers, peer average, peer score, peer group, vs peers, compared to peers, competitor]
requires: [cross-peer-confidentiality]
tables: [Carriers, Peers]
columns: [Carrier, Overall_Peer_Group, Score, SurveyCountry, SurveyPractice, Survey_Year]
metrics: [peer_average, score]
---

## Definition

Survey peer average is the aggregate score or NPS of the selected carrier's peer
set, never a list of peer carrier names.

## Expected SQL Shape

- Resolve peers from `Peers`.
- Filter `Carriers` to that peer set.
- Use `AVG()` for score or NPS metrics.
- Group only by requested dimensions.

## Forbidden Mistakes

- Do not show peer names.
- Do not average already-averaged rows unless the query grain requires it.
- Do not use GPR `Carrier_Group` in Survey SQL.

