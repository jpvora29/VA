---
name: qbr-decline-diagnosis
description: How to explain a fall in Marsh-placed premium the way an ICL would — find the line that caused it, size its share of the fall, set it against the market, the peers and (when available) the survey. Load when the carrier's premium declined.
applies-when: premium_down
order: 40
---

# When premium fell

A decline is the page the carrier's leadership reads most closely. Do not soften it and do
not spread it evenly: find where it came from.

## Work through it in this order

1. **Name the biggest contributor.** Use the `driver.*` fact: which line (or industry,
   segment, country) accounts for most of the fall, and how much of it. "Casualty accounts
   for $4.2M of the $5.0M fall." If one line explains most of the move, say so plainly; if
   the fall is spread across several, say that instead — it is a different conversation.
2. **Separate the carrier from the market.** Use the `pool.*` / Marsh market facts for the
   same line: did Marsh's own placements in that line fall too (a market that shrank), or
   did the carrier lose ground in a line that held up (a share problem)? These lead to very
   different meetings.
3. **Bring in the peers.** Use the `peer.*` facts: is the peer group moving the same way?
   A fall the whole peer group shares reads differently from one the carrier suffered
   alone.
4. **Bring in the survey, when it is in the evidence.** If a `survey.line.*` fact exists
   for the same line, put it beside the premium movement: "…and Casualty is also where the
   survey score slipped most, down 0.3 to 3.6." Only pair a survey score with a premium line
   when the fact names the same line. Never imply the score caused the premium movement.
5. **Point to where the room is.** Use `headroom`, `peer.gap_value` or whitespace
   (`segment.*.absent.*`) facts: where would recovering share, or entering, matter most in
   Marsh-placed premium?

## Framing

- State the movement flatly; offer the reading as a reading ("the fall is concentrated
  in…"); ask for the cause ("worth understanding what changed in Casualty renewals").
- Never invent the cause — pricing, appetite, capacity, a lost account and market events
  are not in the evidence. They are the questions the ICL takes into the room.
