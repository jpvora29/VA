---
name: survey-planner-example
description: One worked example of a grounded Survey analytical plan (structure/altitude reference).
flow: survey
scope: [planner]
always: true
priority: 30
---

[SURVEY PLANNER — WORKED EXAMPLE]
Use this only as a structure/altitude reference for the plan. Never reuse its specific
values; ground every table, column, and filter in the provided schema and valid_values,
and inherit missing filters from routing_context (do not invent them).

Example question: "How did Zurich's score in Singapore for Property compare to peers in
2025, by section?"

Example ideal plan (shape only):
- intent: "Compare Zurich's section-level Score against the peer aggregate in Singapore
  Property for 2025."
- metric: "Average Score + Peer Average"
- metric_definition: "Score = average Score (1-9); Peer Average = aggregated Score across
  the distinct peers for the Carrier/Country/Practice combination (peers never named)."
- steps:
  1. Filter Carriers to SurveyCountry='Singapore', SurveyPractice='Property', Survey_Year=2025.
  2. Average Score for Carrier='ZURICH' grouped by Section.
  3. From Peers, get the peer list for that Carrier/Country/Practice combination.
  4. Average Score across those peers grouped by Section (single aggregate, no peer names).
- tables: ["Carriers", "Peers"]
- filters: {"SurveyCountry": "Singapore", "SurveyPractice": "Property", "Survey_Year": "2025", "Carrier": "ZURICH"}
- group_by: ["Section"]
- timeframe: "2025"
- rules: ["Peers are always aggregated — never expose individual peer names"]
- notes: "Resolve relative years from valid_year_quarter when the query uses 'last year' etc."
