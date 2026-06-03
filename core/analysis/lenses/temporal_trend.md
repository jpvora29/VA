---
name: temporal_trend
description: Year-over-year / period-over-period movement of the queried metric.
applies_when: any metric where "vs when?" matters and multiple periods exist; almost always useful unless the user pinned a single point in time.
requires: []
---

Turn a point-in-time figure into a trajectory.

**SQL shape**
- Compute the same metric for the current period and the prior period(s) using
  `Year` (premium/GPR) or `Survey_Year` (survey), and report the absolute change
  and % change.
- Use the available periods in `valid_year_quarter` to pick the correct current
  and prior periods; do not assume periods that are not present.
- For rolling/12-month metrics, follow the flow's existing premium rules.

**Interpretation**
- Always state both periods explicitly ("in 2024, up from 2023").
- Call out acceleration or deceleration, and inflection points (a metric that
  was rising and is now falling is more newsworthy than a steady value).
