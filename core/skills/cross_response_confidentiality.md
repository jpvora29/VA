---
name: cross-response-confidentiality
description: Confidentiality rules for final answers and report-ready narratives.
flow: cross
scope: [response, pitch]
always: true
priority: 100
---

[CONFIDENTIALITY]
- Never expose individual peer names or individual peer values.
- Refer to peers only as `Peer Group`, `Peers`, or `Peer Average`.
- Do not infer peer performance unless peer aggregate data is present in the SQL output.
- If data is empty, say that no data was returned for the selected filters.
- Every number in the answer must come from the SQL output or the supplied query plan context.
