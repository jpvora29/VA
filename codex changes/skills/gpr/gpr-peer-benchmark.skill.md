---
name: gpr-peer-benchmark
description: GPR peer benchmark resolution, aggregation, and response contract.
flow: gpr
scope: [planner, sql, response, pitch]
kind: domain
priority: 92
risk_level: high
triggers: [peer, peers, peer average, peer group, vs peers, against peers, competitor, competitors, benchmark]
requires: [cross-peer-confidentiality, cross-sql-readonly-safety]
tables: [GPR, Peers]
columns: [Carrier_Group, Overall_Peer_Group, Premium, Country, Product_Line, Year]
metrics: [peer_average, premium]
---

## Definition

The peer benchmark compares the selected carrier against the aggregate premium,
rank, score, or share for its peer set.

## Required Evidence

- Resolve the peer set from `Peers`.
- Query GPR only for those peer carriers.
- Aggregate before response or report generation.

## Expected SQL Shape

- Use `Peers` to get peer carriers for the selected carrier and relevant market.
- Use an `IN` subquery or CTE rather than exposing peer names.
- Aggregate peer metrics as averages or totals according to the metric.

## Forbidden Mistakes

- Do not list individual peer names.
- Do not compare to top 5 unless the user or pitch section asks for top 5.
- Do not treat Marsh book as peers.

