---
name: commentary-style
description: House style for QBR slide commentary — fact-cited, executive-grade insurance broking prose. Use when drafting or redrafting slide commentary from an evidence packet.
---

# QBR commentary style

Commentary is read by ICL leaders and carrier executives. Every sentence must be
defensible in the meeting: a deterministic verifier drops any sentence whose
numbers are not covered by cited fact ids.

## Hard rules (verifier-enforced — violations are discarded)

1. Every sentence lists the `fact_ids` that support it.
2. Every number, currency amount, percentage and rank is copied EXACTLY from a
   cited fact's `rendered` value. Never recompute, re-round or aggregate.
3. Never invent fact ids — only ids present in the evidence packet.
4. Never name an individual peer carrier. Peers are discussed only in aggregate
   ("the peer set", "the market"). Naming Marsh is fine.
5. No causal language ("drove", "because", "due to") unless a decomposition
   fact is cited in the same sentence.

## Structure

Slide commentary follows the contract order:

1. **What changed** — the movement, with the current and prior values.
2. **Why it matters** — rank / share-of-wallet context.
3. **What drove it** — only when a decomposition fact explains enough of the move.
4. **What to watch** — only when the contract allows recommendations.

## Tone

- Declarative, front-loaded: the number and its direction first, qualifier after.
- One idea per sentence; no hedging ("it appears", "roughly"), no filler
  ("it is worth noting"), no preamble.
- Imperatives for recommendations: "Defend…", "Scale…", "Enter…".
