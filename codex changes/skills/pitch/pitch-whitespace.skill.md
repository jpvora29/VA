---
name: pitch-whitespace
description: Whitespace definition and evidence rules for Pitch Builder.
flow: gpr
scope: [pitch, planner, sql, response]
kind: pitch
priority: 84
risk_level: high
triggers: [whitespace, white space, opportunity, gap, absence, no premium, under-index]
requires: [gpr-marsh-market, cross-peer-confidentiality]
metrics: [whitespace, premium]
---

## Definition

Whitespace exists only when carrier premium is zero, null, or materially small in
a slice where Marsh or peers show meaningful participation.

## Required Evidence

- Carrier premium for the slice.
- Marsh or peer premium for the same slice.
- Slice label such as product, industry, segment, or geography.

## Forbidden Mistakes

- Do not use "whitespace" as a synonym for any generic opportunity.
- Do not claim whitespace when carrier participation is material.
- Do not recommend action without evidence of market or peer participation.

