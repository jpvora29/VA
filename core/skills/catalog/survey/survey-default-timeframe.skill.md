---
name: survey-default-timeframe
description: Always-on default timeframe — no year named means latest available survey year, never an all-years average.
flow: survey
scope: [planner, sql]
always: true
priority: 90
---

[SURVEY DEFAULT TIMEFRAME — applies when the query names NO year]
- Default to the latest available survey year:
  `Survey_Year = (SELECT MAX(Survey_Year) FROM Carriers)`.
- NEVER average or aggregate across all survey years by default — mixing waves
  silently distorts scores.
- Always state the year you defaulted to in the response (e.g. "for 2025, the
  latest survey year").
- This rule is the no-time-words case. If the query DOES carry a time reference
  (YoY, last year, latest, trend...), the survey-timeframe rules take over.
