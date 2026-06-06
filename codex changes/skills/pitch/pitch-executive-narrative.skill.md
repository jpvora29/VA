---
name: pitch-executive-narrative
description: Evidence-grounded executive narrative rules for Pitch Builder reports.
flow: cross
scope: [pitch]
kind: pitch
priority: 90
risk_level: high
always: true
requires: [cross-peer-confidentiality, validation-report-claim-grounding]
metrics: [premium, score, share_of_wallet, share_of_portfolio, peer_average, whitespace]
---

## Definition

Pitch Builder should produce a carrier-facing executive narrative, not a metric
dump. Every claim must trace to extracted evidence.

## Required Evidence

- Current selected carrier, country, and year.
- SQL-backed answer for each pitch question.
- Extracted metrics with context labels.
- Supporting rows for material claims.

## Response Rules

- Lead with the most strategically important movement.
- Pair interpretation with numbers.
- Omit sections where evidence is absent instead of inventing content.
- Keep peer references aggregated.
- Use "whitespace" only when carrier absence or very low premium is shown
  alongside meaningful peer or Marsh participation.

## Forbidden Mistakes

- Do not invent drivers, causes, market conditions, or recommendations.
- Do not report percentages without the actual premium values when premium is central.
- Do not turn weak evidence into strong strategic claims.

