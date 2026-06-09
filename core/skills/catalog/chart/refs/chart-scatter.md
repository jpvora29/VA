[SCATTER PLOT — `chart_type='scatter'`]

When: examining the RELATIONSHIP between TWO numeric measures, one on each axis —
e.g. does higher share-of-wallet go with higher growth? Use scatter when both
quantities are continuous numbers, especially of different types (an amount vs a
percentage, a score vs an NPS).

Field mapping:
- `x` = the FIRST numeric measure (a column name that is numeric, NOT a category).
- `y` = a LIST with the SECOND numeric measure, e.g. `["Growth_%"]`.
- `series` = an optional category to colour the points (e.g. Carrier_Group,
  Segment) so each entity is distinguishable. Exclude x and y.
- `bar_mode` = `[]`.

Worked examples:
- "Relationship between SoW and growth across carriers" → x=Share_of_Wallet,
  y=[Growth_%], series=[Carrier_Group].
- "Score vs NPS by section" → x=Score, y=[NPS], series=[Section].

Common mistakes:
- Using a categorical column for `x` (that is a `bar` chart, not scatter).
- Choosing scatter when the user wants a comparison across categories (use `bar`)
  or a trend over time (use `line`).
