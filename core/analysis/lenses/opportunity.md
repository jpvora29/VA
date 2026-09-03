---
name: opportunity
description: Where the carrier is present but under-indexed versus a strong/growing market — room to grow.
applies_when: growth, strategy, or "where should we focus" questions; complements whitespace (presence-but-thin vs absent).
requires: [GPR]
---

Opportunity is the softer sibling of whitespace: the carrier **is** present in a
slice but is **under-indexed** relative to a market (Marsh book) that is large
and/or growing — so there is headroom to grow share.

**Preferred: compute it, do not query it**
- Carrier share of the market per slice = `compute_metric(name='compute_share_of_wallet',
  group_by=['<dimension>'])`; the carrier's own mix = `compute_share_of_portfolio`.
- Market size per slice = `compute_metric(name='compute_market_presence', group_by=[...])`;
  market growth = `compute_yoy_to_date` with no carrier filter.
- Then rank the under-indexed slices yourself from those computed rows.

**SQL shape (fallback only, for what the above does not cover)**
- For the relevant dimension members (product / industry / segment), compute:
  - carrier premium and carrier YoY,
  - market premium (Marsh book) and market YoY,
  - the carrier's share of the market for that slice.
- Rank slices where the market is sizeable and growing but the carrier's share
  is below its overall average share (under-indexed) — those are opportunities.

**Interpretation**
- Distinguish from whitespace: opportunity = thin-but-present in a good market;
  whitespace = absent in a good market.
- Prioritize opportunities by market size × market growth × share headroom, and
  state the specific slice and the size of the gap to a fair share.
