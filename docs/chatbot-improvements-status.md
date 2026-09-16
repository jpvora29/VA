# Chatbot improvements: implementation status

Date: 2026-09-15
Covers: `docs/chatbot-improvements-implementation-plan.md`, milestones 1 and 2.

Scope agreed with the product owner before work began:

- Phases 0-4, 6, 7, 8 in full, plus Phase 5 items 5-9 (the survey half).
- Phase 5 items 1-4 (whitespace) deferred: its thresholds are uncalibrated.
- Phase 9 (conversation memory) and Phase 10 (rollout) not started.
- Evaluation on deterministic fixtures. This environment has no model
  credentials, so no live quality or latency number is claimed anywhere below.

## Settled defaults

Section 2 of the plan lists defaults that were product decisions rather than
engineering ones. Two were settled and are now configuration, not code:

| Decision | Settled as | Where it lives |
|---|---|---|
| Unqualified performance question | premium plus a brief survey assessment where comparable data exists | `core/analysis/intents.yaml`, `policy.performance_sources` |
| Whitespace participation rule | absence only; thin-but-present is `opportunity`, not whitespace | `core/analytics/library.py`, `ABSENT_PARTICIPATION` |

An explicit restriction in the question ("premium only") overrides the first.
The second ships with its thresholds visible and uncalibrated rather than
encoded as though ICG had approved them.

## What each phase produced

| Phase | Landed | Notes |
|---|---|---|
| 0 Baseline | `tests/evaluation/` | Hand-checked scenario, SQLite warehouse mirroring `flows.yaml`, reference oracles that import no application code, stage attribution |
| 1 Semantics | `core/analysis/requirements.py`, `intents.yaml`, `operation.py`, `alignment.py` | Per-intent evidence contracts; premium/survey mapping read from the registry |
| 2 Evidence contract | `core/analysis/evidence_ledger.py` | Stable identity, idempotent merge, requested vs executed scope |
| 3 Comparable evidence | `core/analytics/movement.py`, `periods.py` | Corresponding-period comparison and contribution decomposition |
| 4 Result-driven planning | `core/analysis/progress.py`, `observations.py` | Step outcomes, materiality, bounded budget, recorded stop reason |
| 5 (survey half) | `core/analysis/survey_movement.py` | Points not percent, response threshold, questionnaire and population changes |
| 6 Commentary brief | `core/answers/narration.py`, `narrator.py`, `writer.py` | `synthesis_focus` wired; requirements and limitations reach the writer |
| 7 Verification | `core/answers/verification.py` | Six checks, structured failures, one deterministic repair |
| 8 Chart alignment | `core/agents/analyst/chart_picker.py` | `ChartFocus` binds the chart to the finding the answer led with |

## The motivating question

`build_turn_contract` on "How was Zurich's performance in Singapore in 2025?"
now produces:

    requirements: annual_movement, product_contributors, quarterly_comparison,
                  survey_movement
    deferred:     industry_concentration (awaits an observed movement),
                  whitespace (thresholds uncalibrated)

The industry drill-down is admitted later by a material product movement, not by
the question's wording. That is asserted end to end in
`tests/test_analyst_evidence_loop.py`.

## Two decisions worth revisiting

1. **`MAX_CHAT_LENSES` raised from 3 to 6** (ceiling 8, contract-aware). The old
   cap sat below the planner signature's own "2-5 lenses" instruction, so a
   performance answer was structurally incomplete. This costs model calls and
   latency per analytical turn and has not been measured against a live model.

2. **Limitations sit beside the answer, not inside the verified ledger.** The
   stored record verifies by rebuilding its text from claims that are re-checked
   against evidence. A limitation derives from the turn's plan, which the record
   does not carry, so folding it in would create a sentence verification cannot
   check. The narrator is instructed to state limitations in the prose instead.

## Not done, and why

- **Whitespace (Phase 5.1-5.4).** Needs a calibrated meaningful-book size and a
  rule distinguishing a genuine zero from unknown participation. `find_whitespace`
  still defaults `material` to 0.0, meaning any market premium counts as
  meaningful. The knob is explicit and commented; the number is ICG's to set.
- **Phase 9, conversation memory.** The `conversation.py` 40-message / 6,000
  character cap is unchanged and there is still no historical retrieval interface.
- **Phase 10, rollout and live evaluation.** No live model run has happened. No
  latency, cost or quality claim in this document is measured.
- **Expert-reviewed expectations.** The harness scores numerical and scope
  correctness against independent oracles. Qualitative ICG usefulness is not
  scored, because no expert has reviewed the cases.

## Test state

Full suite, excluding `tests/charts` and `tests/e2e`: see the run recorded with
this change. Two failures predate this work and were verified against a clean
tree:

- `tests/test_studio_qbr_generation.py::test_swot_strengths_include_premium_scale_and_share_of_portfolio`
- `tests/test_survey_pointer.py::test_the_survey_line_lands_on_the_page_that_carries_the_score_tile`

Both are Studio deck wording, untouched here.
