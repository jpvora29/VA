---
name: contradiction
description: Surface tensions where financial and perception signals disagree.
applies_when: both premium/financial and survey/perception evidence are available for the carrier (or the query spans both), and divergence would be decision-relevant.
requires: [GPR, Carriers]
---

The most decision-relevant insights are often disagreements between signals.
This lens looks for them across the premium and perception views.

**Patterns to test**
- Premium / Share of Wallet **up** but broker **Score / perception down** (growth
  that may not be durable; relationship risk).
- Premium **down** but perception **up** (latent recovery potential).
- Strong **rank** but weak growth (defending, not gaining).
- Growth concentrated in a product where perception is weakest.

**SQL shape**
- Pull the financial trend (premium / share / YoY from GPR) and the perception
  trend (Score / section / attribute movement from the survey tables) for the
  same carrier + slice + periods, then compare directions.

**Interpretation**
- Name the tension explicitly and explain what it implies for leadership
  (e.g. "premium grew while service perception declined — growth may be at risk
  if the experience gap persists"). Only assert a tension the evidence supports.
