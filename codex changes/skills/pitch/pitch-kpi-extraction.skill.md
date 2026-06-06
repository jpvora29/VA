---
name: pitch-kpi-extraction
description: Carrier-only KPI extraction rules for report header values.
flow: cross
scope: [pitch]
kind: pitch
priority: 88
risk_level: high
triggers: [premium, yoy, rank, score, policy, policies, kpi]
columns: [Premium, Score, Rank, Policy_Count]
metrics: [premium, yoy, rank, score, policies]
---

## Definition

Header KPIs must be carrier-only values. They must not be calculated from peer,
Marsh, or market rows unless explicitly labeled as such in a separate section.

## Field Contract

Use one premium field consistently:

- `total_curr_premium`
- `yoy`
- `gpr_rank`
- `rank_delta`
- `survey_score`
- `policies`
- `last_year_rank`

## Forbidden Mistakes

- Do not map Marsh premium to carrier premium.
- Do not map peer average premium to carrier premium.
- Do not fill empty KPI fields with guessed values.

