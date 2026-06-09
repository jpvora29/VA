---
name: survey-peer-average
description: Survey peer-average lookup (Peers table → Carriers filter) and aggregation rules.
flow: survey
scope: [planner]
kind: domain
priority: 70
risk_level: high
triggers: [peer, peers, peer average, peer score, peer group, vs peers, against peers, compared to peers, peer comparison, competitor, rival, competition]
requires: [cross-sql-readonly-safety]
tables: [Carriers, Peers]
columns: [Carrier, Overall_Peer_Group, Score, NPS, SurveyCountry, SurveyPractice, Section, Attribute, Survey_Year]
metrics: [peer_average, score, nps]
examples:
  - user_query: How does Zurich's score compare to peers in Singapore?
    expected_sql_shape: resolve peers from Peers, filter Carriers to that set, AVG(Score) by requested dimension
test_queries:
  positive: [Zurich peer average score, peer score by section, vs peers NPS]
  negative: [Zurich premium vs peers, name Zurich's peers]
---

## Definition

Survey peer average is the AGGREGATE score (or NPS) of the selected carrier's peer
set — never a list of peer carrier names. Peers are confidential
(see cross-response-confidentiality).

## Required Evidence

1. Query the `Peers` table first:
   - Apply the `Carrier` filter.
   - Apply `Country` / `Practice` filters ONLY if explicitly mentioned or derived
     from context.
   - Get the unique list of peer carriers.
2. Use that list to filter the `Carriers` table:
   - Apply all other user filters (year, region, attribute, section, etc.).
   - Compute the peer-average score/NPS for that group.

## Expected SQL Shape

- Resolve peers from `Peers`, then filter `Carriers` to that peer set.
- Use `AVG()` for score / NPS metrics.
- Group only by the requested dimensions.

## Forbidden Mistakes

- Do not show individual peer names.
- Do not average already-averaged rows unless the query grain requires it.
- Do not use GPR `Carrier_Group` in Survey SQL — Survey carriers live in
  `Carriers.Carrier`.
