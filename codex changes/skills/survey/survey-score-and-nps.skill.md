---
name: survey-score-and-nps
description: Survey score and NPS aggregation, interpretation, and response rules.
flow: survey
scope: [planner, sql, response, pitch]
kind: metric
priority: 86
risk_level: high
triggers: [score, nps, satisfaction, perception, broker sentiment, attribute, section]
requires: [cross-peer-confidentiality]
tables: [Carriers, Peers]
columns: [Score, NPS Score, NPS_Group, Carrier, SurveyCountry, SurveyPractice, Section, Attribute, Survey_Year]
metrics: [score, nps]
---

## Definition

Survey metrics represent broker perception. Scores and NPS must be aggregated
before being presented.

## Expected SQL Shape

- Use `AVG(Score)` for score-like questions.
- Use `AVG("NPS Score")` for NPS unless a count by `NPS_Group` is requested.
- Include requested dimensions in `SELECT` and `GROUP BY`.
- Use `SurveyCountry` for country and `SurveyPractice` for product/practice.

## Response Rules

- Answer only from retrieved survey evidence.
- Explain business meaning cautiously: service quality, broker experience, or
  relationship perception only when the evidence supports it.

## Forbidden Mistakes

- Do not expose individual survey rows.
- Do not infer causes from score movement without supporting evidence.
- Do not compare to premium unless GPR evidence is also present.

