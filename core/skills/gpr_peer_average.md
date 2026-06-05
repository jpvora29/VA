---
name: gpr-peer-average
description: Peer group lookup, aggregation, and confidentiality rules for GPR.
flow: gpr
scope: [planner, sql, response]
triggers: [peer, peers, peer average, peer group, vs peers, against peers, peer comparison, competitor, rival, competition, versus]
priority: 90
---

[GPR PEER AVERAGE]
- Resolve peers from `Peers` using the selected `Carrier_Group` and optional `Country`.
- Use the resolved `Overall_Peer_Group` values to filter `GPR`.
- Apply all non-carrier user filters to both carrier and peer calculations.
- Return only aggregated peer metrics, never individual peer names.
- For peer premium, use an aggregate labelled `peer_average_premium`.
- If comparing carrier vs peers, return carrier aggregate and peer aggregate side by side.

[PEER ↔ CARRIER_GROUP MATCHING — read carefully]
`Peers.Overall_Peer_Group` is *meant* to hold `GPR.Carrier_Group` names, but the
two are NOT guaranteed to be byte-identical (case, trailing spaces, or slightly
different spellings occur). A direct `IN` comparison therefore silently drops
peers and understates the peer average. To be robust:
  1. ALWAYS compare case-insensitively and trimmed on BOTH sides:
     `LOWER(TRIM(Carrier_Group)) IN (SELECT LOWER(TRIM("Overall_Peer_Group")) ...)`.
  2. If the peer-average leg returns 0 rows / NULL while the carrier leg has data,
     the names diverge beyond case/space. Then list the peer set
     (`SELECT DISTINCT "Overall_Peer_Group" FROM Peers WHERE ...`) and call the
     `resolve_value` tool for each value against column `Carrier_Group` to map it
     to the canonical GPR spelling, and filter GPR on the resolved names.

[WORKED EXAMPLE — peer comparison SQL shape]
Filter `GPR.Carrier_Group` against the resolved peer set — do NOT join `Peers`
to `GPR`. Resolve the peer set in a CTE, then compute the carrier and
peer-average legs in one pass with the SAME user filters applied to both, using
case-insensitive trimmed matching throughout:

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

- For a breakdown (by product / segment / etc.), add that dimension to both
  `SELECT` and `GROUP BY`.
- For YoY, repeat the comparison per `Year` and report whether the carrier-vs-peer
  gap widened or closed.
