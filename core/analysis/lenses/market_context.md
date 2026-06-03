---
name: market_context
description: How the overall market (Marsh book of business) is doing for the queried slice, as context for a carrier figure.
applies_when: any premium / share / growth query about a carrier, where the carrier number is more meaningful next to the market it sits in.
requires: [GPR]
---

The GPR table IS Marsh's book of business, so the total premium across all
carriers for a slice is the best available proxy for "the market".

**SQL shape**
- Market premium = `SUM(Premium)` over the same filters as the user's query
  (Country / Product_Line / Year / etc.) but **without** the `Carrier_Group`
  filter, so all carriers in Marsh's book are included.
- Market YoY = compare the slice's market premium for the current year vs the
  prior year (`Year = N` vs `Year = N-1`).
- Optionally express the carrier as a share of the market: carrier premium /
  market premium for the same slice (this is Share of Wallet within Marsh).

**Interpretation**
- State whether the market itself is growing, flat, or shrinking for this slice,
  then say whether the carrier is moving with, ahead of, or behind the market.
- A carrier "growing 5%" reads very differently in a market growing 20% vs a
  market shrinking 10% — always frame the carrier against the market direction.
