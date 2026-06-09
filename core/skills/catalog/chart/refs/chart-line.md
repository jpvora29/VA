[LINE CHART — `chart_type='line'`]

When: showing a measure's progression over time. STRONGLY prefer line for
rolling-12-month, month-on-month, quarter-on-quarter, and year-over-year views,
or any result spanning more than one period.

Field mapping:
- `x` = the time dimension (Year, Quarter, Month, or a Year-Quarter label). Keep
  it ordered chronologically (the engine respects natural row order / `sort`).
- `y` = the measure(s) plotted over time, e.g. `["Premium"]` or
  `["Carrier_Premium","Peer_Avg_Premium"]`.
- `series` = a category that yields one line per value (e.g. Region, Segment,
  Carrier_Group). Exclude x and y.
- `bar_mode` = `[]` (never used for line).
- `y_agg` = `mean` for scores/rates, `sum` for amounts, when multiple rows share
  a period.

Worked examples:
- "Premium trend 2019–2024" → x=Year, y=[Premium], series=[].
- "Rolling 12-month score by region" → x=Month, y=[Score], series=[Region].
- "Carrier vs peer-average premium over time" → x=Year,
  y=[Carrier_Premium, Peer_Avg_Premium], series=[].

Common mistakes:
- Using line for a single period (use `bar`).
- Mixing an absolute amount and a percentage on one line axis — if the user wants
  both together, use `combo` (amount as bars, % as the secondary-axis line).
