---
name: cross-peer-confidentiality
description: Peer anonymity and aggregation contract for SQL, responses, and pitch reports.
flow: cross
scope: [planner, sql, response, pitch, validation]
kind: confidentiality
priority: 100
risk_level: high
always: true
tables: [Peers, Carriers, GPR]
metrics: [peer_average, peer_benchmark]
---

## Definition

Peers are always confidential. They may be used as an aggregate benchmark, but
individual peer or competitor names must not appear in user-facing output.

## Required Evidence

- The peer set may be resolved from `Peers`.
- The final evidence should aggregate peer rows before presentation.
- User-facing language should say "peer average", "peer set", or "peer benchmark".

## Expected SQL Shape

- Resolve peers in a subquery or CTE.
- Aggregate peer rows with `AVG()`, `SUM()`, or another metric-appropriate aggregate.
- Do not select individual peer names in final displayed rows.

## Forbidden Mistakes

- Do not list peer names in responses, charts, report tables, or report prose.
- Do not compare against peers unless peer evidence was actually retrieved.
- Do not let Pitch Builder turn hidden peer names into section labels.

