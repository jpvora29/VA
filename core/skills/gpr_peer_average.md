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

[WORKED EXAMPLE — peer comparison SQL shape]
The `Overall_Peer_Group` values stored in `Peers` ARE `Carrier_Group` names, so
filter `GPR.Carrier_Group` directly against them — do NOT join `Peers` to `GPR`.
Resolve the peer set in a CTE, then compute the carrier and peer-average legs in
one pass with the SAME user filters applied to both:

    WITH peer_group AS (
        SELECT DISTINCT "Overall_Peer_Group"
        FROM Peers
        WHERE LOWER(Carrier_Group) = LOWER('<carrier>')
          -- add: AND LOWER(Country) = LOWER('<country>') ONLY if the user named one
    )
    SELECT
        SUM(CASE WHEN LOWER(Carrier_Group) = LOWER('<carrier>') THEN Premium END)
            AS carrier_premium,
        AVG(CASE WHEN Carrier_Group IN (SELECT "Overall_Peer_Group" FROM peer_group)
            THEN Premium END) AS peer_average_premium
    FROM GPR
    WHERE <same user filters (year, region, product, segment) applied to both legs>;

- For a breakdown (by product / segment / etc.), add that dimension to both
  `SELECT` and `GROUP BY`.
- For YoY, repeat the comparison per `Year` and report whether the carrier-vs-peer
  gap widened or closed.
