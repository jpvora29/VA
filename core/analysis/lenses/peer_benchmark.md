---
name: peer_benchmark
description: Compare the carrier against its peer group (aggregated, confidentiality-safe).
applies_when: a carrier's premium / score / rank / growth is asked, and competitive positioning adds value.
requires: [Peers, GPR]
---

Benchmark the carrier against the average of its defined peer set for the same
slice. Use the **Peers** table to resolve the peer list for the
Carrier / Country / Product combination, then aggregate those peers' metrics in
the main table (GPR for premium, Carriers/Survey for score).

**SQL shape**
- Resolve peers from the Peers table for the carrier + slice.
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
