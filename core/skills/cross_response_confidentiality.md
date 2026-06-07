---
name: cross-response-confidentiality
description: Peer anonymity and answer-grounding contract for final answers and report prose.
flow: cross
scope: [response, pitch]
kind: confidentiality
priority: 100
risk_level: high
always: true
tables: [Peers, Carriers, GPR]
metrics: [peer_average, peer_benchmark]
---

## Definition

Peers are always confidential. They may be used as an aggregate benchmark, but
individual peer / competitor names must never appear in user-facing output
(answers, charts, report tables, or report prose).

## Required Evidence

- Refer to peers only as "Peer Group", "Peers", "Peer Average", or "peer set".
- Do not infer peer performance unless peer AGGREGATE data is present in the SQL
  output.
- Every number in the answer must come from the SQL output or the supplied query
  plan context.
- If the data is empty, say that no data was returned for the selected filters.

## Forbidden Mistakes

- Do not expose individual peer names or individual peer values.
- Do not compare against peers unless peer evidence was actually retrieved.
- Do not let Pitch Builder turn hidden peer names into section labels.
