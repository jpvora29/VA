---
name: peer_benchmark
description: Compare the carrier against its peer group (aggregated, confidentiality-safe).
applies_when: a carrier's premium / score / rank / growth is asked, and competitive positioning adds value.
requires: [Peers, GPR]
---

Benchmark the carrier against the average of its defined peer set for the same
slice.

**Preferred: compute it, do not query it**
- Peer average premium = `compute_metric(name='compute_peer_average_total')` —
  the average of each peer's TOTAL, which is the like-for-like benchmark for an
  additive measure.
- Peer average score = `compute_metric(name='compute_peer_average')` — the
  average per response, the right shape for an averaged metric.
- Carrier's own leg = `compute_breakdown` (premium) or
  `compute_attribute_breakdown` (score), so both legs share one definition.
- These resolve the peer set from the **Peers** table, scope it to the selected
  country, and honour a pinned custom peer set — none of which you have to build.

**SQL shape (fallback only, when a computed leg comes back empty)**
- Resolve peers from the Peers table for the carrier + slice, matching
  `Peers.Overall_Peer_Group` to `GPR.Carrier_Group` with `LOWER(TRIM(...))` on
  BOTH sides.
- Peer average premium = `AVG(SUM(Premium) per peer)` for the same filters.
- Compare: carrier value, peer-average value, absolute gap, and % difference.
- For YoY, compute the same comparison for the prior year to show whether the
  gap is widening or closing.

**Confidentiality (hard rule)**
- Report peers ONLY in aggregate. Never name an individual peer, never reveal an
  individual peer's premium, rank, or score. Present a single peer-average figure.

**Interpretation**
- Always pair the percentage with the actual values ("carrier premium X vs peer
  average Y, a gap of Z (A%)"). Say whether the carrier is above, near, or below
  the peer benchmark, and whether the position is improving or weakening YoY.
