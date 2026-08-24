---
name: survey-market-geography
description: Mapping of market/region/country phrasings to the Region and SurveyCountry filters.
flow: survey
scope: [planner]
triggers: [market, markets, region, regional, asia, asian, latam, latin america, emea, apac, europe, european, north america, global, overall market, worldwide]
priority: 60
---

[ENTITY & FILTER INTEPRETATION RULES]:
- 'Market' generally refers to a geographical region.
For example:
- 'Asia market' or 'Asian market' -> Region = 'Asia'
- 'LATAM market' -> Region = 'Latin America'

- If both 'market' and 'country' are mentioned, prioritize Country as the filter, but still ensure Region is inferred correctly if needed for hierarchy checks.
- If only 'market' is mentioned, map it directly to the Region field.
- The word 'global' or 'overall market' means no regional filter should be applied.
