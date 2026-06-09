[COMBO CHART — `chart_type='combo'`]

When: showing an ABSOLUTE amount and a RATE/PERCENTAGE for the same categories at
once, where the two measures live on very different scales. Bars carry the
absolute amount (left axis); a line carries the rate/% on a SECONDARY right-hand
axis so both read clearly. Classic uses: Premium (bars) + Growth% (line);
Premium (bars) + Share-of-Wallet% (line); Score (bars) + YoY% (line).

Field mapping:
- `x` = the category or time dimension (Year, Product, Carrier, etc.).
- `y` = a LIST of the ABSOLUTE measure(s) drawn as BARS on the primary axis, e.g.
  `["Premium"]`.
- `secondary_y` = a LIST of the RATE/% measure(s) drawn as a LINE on the secondary
  axis, e.g. `["Growth_%"]` or `["Share_of_Wallet"]`. These MUST be different
  columns from `y`.
- `series` = usually `[]` for combo (the two measures already differentiate
  themselves); add one only if you must split bars by a category.
- `bar_mode` = `[]`.

Worked examples:
- "Premium and growth % by year" → x=Year, y=[Premium], secondary_y=[Growth_%].
- "Premium with share-of-wallet by product" → x=Product_Line, y=[Premium],
  secondary_y=[Share_of_Wallet].

Behaviour & mistakes:
- If `secondary_y` ends up empty, it is NOT a combo — use `bar` or `line` instead
  (the engine will fall back to bars automatically).
- Keep the absolute measure in `y` and the percentage in `secondary_y`, never the
  reverse.
- Do not mix two absolute amounts of the same unit here — that is a normal `bar`
  with two y columns.
