---
name: gpr-peer-average
description: GPR peer-group resolution, robust peer matching, aggregation, and confidentiality.
flow: gpr
scope: [planner, sql, response]
kind: domain
priority: 90
risk_level: high
triggers: [peer, peers, peer average, peer group, vs peers, against peers, peer comparison, competitor, rival, competition, versus]
requires: [cross-sql-readonly-safety]
tables: [GPR, Peers]
columns: [Carrier_Group, Overall_Peer_Group, Premium, Country, Region, Product_Line, Client_Segment, Year]
metrics: [peer_average, premium]
examples:
  - user_query: How does Zurich premium compare to its peers in Canada?
    expected_sql_shape: resolve peer set in a CTE, then carrier and peer-average legs in one pass with case-insensitive trimmed matching
test_queries:
  positive: [Zurich vs peers premium in Canada, peer average premium by product]
  negative: [Zurich share of wallet, list Zurich's competitors by name]
---

## Definition

A peer benchmark compares the selected carrier against the AGGREGATE premium (or
rank/share) of its peer set. Peers are confidential — only aggregates are ever
returned, never individual peer names (see cross-response-confidentiality).

## Required Evidence

- Resolve the peer set from `Peers` using the selected `Carrier_Group` and, only
  if the user named one, `Country`.
- Query GPR for those peer carriers and the selected carrier under the SAME
  non-carrier filters.
- Aggregate before responding: label peer premium `peer_average_premium`.

## Expected SQL Shape

Filter `GPR.Carrier_Group` against the resolved peer set — do NOT join `Peers` to
`GPR`. Resolve the peer set in a CTE, then compute the carrier and peer-average
legs in one pass with the SAME user filters applied to both.

`Peers.Overall_Peer_Group` is MEANT to hold `GPR.Carrier_Group` names but is not
guaranteed byte-identical (case, trailing spaces, spelling), so a direct `IN`
silently drops peers and understates the average. Therefore:

1. ALWAYS compare case-insensitively and trimmed on BOTH sides:
   `LOWER(TRIM(Carrier_Group)) IN (SELECT LOWER(TRIM("Overall_Peer_Group")) ...)`.
2. If the peer leg returns 0 rows / NULL while the carrier leg has data, the names
   diverge beyond case/space: list the peer set
   (`SELECT DISTINCT "Overall_Peer_Group" FROM Peers WHERE ...`), call
   `resolve_value` for each against `Carrier_Group` to map to the canonical GPR
   spelling, and filter GPR on the resolved names.

```sql
WITH peer_group AS (
    SELECT DISTINCT "Overall_Peer_Group"
    FROM Peers
    WHERE LOWER(TRIM(Carrier_Group)) = LOWER(TRIM('<carrier>'))
      -- add: AND LOWER(Country) = LOWER('<country>') ONLY if the user named one
)
SELECT
    SUM(CASE WHEN LOWER(TRIM(Carrier_Group)) = LOWER(TRIM('<carrier>'))
        THEN Premium END) AS carrier_premium,
    AVG(CASE WHEN LOWER(TRIM(Carrier_Group)) IN
            (SELECT LOWER(TRIM("Overall_Peer_Group")) FROM peer_group)
        THEN Premium END) AS peer_average_premium
FROM GPR
WHERE <same user filters (year, region, product, segment) applied to both legs>;
```

- For a breakdown (by product / segment / etc.), add that dimension to both
  `SELECT` and `GROUP BY`.
- For YoY, repeat the comparison per `Year` and report whether the carrier-vs-peer
  gap widened or closed.

## Forbidden Mistakes

- Do not list or expose individual peer / competitor names.
- Do not treat the Marsh book as the peer set.
- Do not compare to "top 5" unless the user explicitly asks for top 5.
- Do not use `Carrier_Name`; always use `Carrier_Group`.
