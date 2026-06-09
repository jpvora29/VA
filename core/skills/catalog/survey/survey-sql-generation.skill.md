---
name: survey-sql-generation
description: Survey-specific SQL generation constraints.
flow: survey
scope: [sql]
always: true
priority: 70
---

[SURVEY SQL GENERATION]
- Use `Carriers` and `Peers` only.
- Score-like metrics must use `AVG()`, not raw row values.
- Never return individual peer rows or peer names.
- Include requested breakdown dimensions in both `SELECT` and `GROUP BY`.
- Use `SurveyCountry` for country filters and `SurveyPractice` for product/practice filters.
- Use case-insensitive matching for text filters: `LOWER(column) = LOWER(value)`.
- Do not add filters absent from the analytical plan.
