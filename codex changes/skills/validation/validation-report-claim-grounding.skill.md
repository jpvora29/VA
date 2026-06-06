---
name: validation-report-claim-grounding
description: Report validation rules that map every important claim back to evidence.
flow: cross
scope: [validation, pitch]
kind: validation
priority: 95
risk_level: high
always: true
---

## Validation Contract

Before a report is rendered, validate that each KPI, comparison, whitespace
claim, peer statement, and product/industry/segment statement is supported by
extracted evidence.

## Claim Record

```json
{
  "claim": "Carrier premium declined by 9.2%.",
  "section": "Executive Summary",
  "evidence_ids": ["q1.row3"],
  "status": "supported"
}
```

## Failure Modes

- `unsupported`: remove or rewrite the claim.
- `ambiguous`: lower confidence or add limitation.
- `confidentiality_risk`: aggregate peer details.
- `format_error`: fix number or unit formatting.

