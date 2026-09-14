---
name: whitespace
description: Find slices where the Marsh book is strong/growing but the carrier is absent or materially thin.
applies_when: a carrier's product/industry/segment footprint is discussed and gaps versus the market are useful (portfolio gaps, growth headroom).
requires: [GPR]
primitives:
  - call: find_whitespace
    group_by: [Product_Line, SIC_Major_Class]
  - call: compute_market_presence
    group_by: [SIC_Major_Class]
---

Whitespace = the carrier writes **nothing** in a slice where the **market (Marsh
book) has premium**. Use the exact term **"whitespace"** — never "untapped",
"underpenetrated", "uncaptured", or similar synonyms.

**Absent, not thin.** A carrier that writes a little in a large slice is
*headroom* and belongs to the `opportunity` lens, not this one. The shipped rule
in `find_whitespace` is carrier premium == 0; a thinness threshold has not been
calibrated with ICG, so do not describe a slice as "materially thin" unless the
returned fact's `participation` says `thin`. Each returned fact carries the
thresholds that admitted it — read them rather than assuming.

**Preferred: compute it, do not query it**
- `compute_metric(name='find_whitespace', group_by=['SIC_Major_Class'])` applies
  the thin-carrier / present-market rule below and returns the flagged slices.
- Market size for context = `compute_metric(name='compute_market_presence', group_by=[...])`.

**SQL shape (fallback only; typically depends on a prior breakdown step)**
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
- A slice the carrier is simply MISSING from the result set is not proof of zero
  participation. Say the carrier's premium is not present in this scope; do not
  upgrade an absent row into a confirmed whitespace finding.
- Explain the business implication: a portfolio gap in a large, growing market
  the carrier is not capturing.
