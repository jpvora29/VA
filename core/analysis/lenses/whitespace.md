---
name: whitespace
description: Find slices where the Marsh book is strong/growing but the carrier is absent or materially thin.
applies_when: a carrier's product/industry/segment footprint is discussed and gaps versus the market are useful (portfolio gaps, growth headroom).
requires: [GPR]
---

Whitespace = the carrier has **zero, null, or materially insignificant** premium
for a slice while the **market (Marsh book) has meaningful premium** for that
same slice. Use the exact term **"whitespace"** — never "untapped",
"underpenetrated", "uncaptured", or similar synonyms.

**SQL shape (typically depends on a prior breakdown step)**
1. If targeting "the top product", first take the top `Product_Line` from a
   `dimensional_breakdown` step.
2. For that product, compute per-industry (`SIC_Major_Class`) totals:
   - market premium = `SUM(Premium)` over all carriers (the Marsh book),
   - carrier premium = `SUM(Premium)` filtered to the `Carrier_Group`,
   - and the market's YoY growth for that industry.
3. Flag industries where market premium is high AND (ideally) growing, but the
   carrier premium is zero or a very small share of the market for that slice.

**Interpretation**
- Only classify whitespace where there is meaningful market/peer participation —
  an industry no one writes is not whitespace.
- Explain the business implication: a portfolio gap in a large, growing market
  the carrier is not capturing.
