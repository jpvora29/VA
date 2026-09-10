# QBR Studio commentary diagnosis

Historical diagnosis from 10 September 2026, before implementation. The export commentary code and prompts have since changed; see [implementation and validation](qbr-commentary-implementation.md). Findings and line references below describe the earlier version.

The problem spans analytical interpretation, evidence preparation, finding selection, and writing. A better model or a longer prompt would still receive misleading or incomplete evidence. ICG needs commentary that clearly explains the carrier's performance with Marsh, its position against a defined benchmark, the material gaps, and the next question or action supported by those findings.

The user's examples are illustrative, not verified portfolio data or a specification to hard-code. This review inspected the local Studio export path and exercised its functions offline. It did not reproduce a live AI generation or establish the source of the exact pasted wording.

## Confirmed findings

### 1. The momentum calculation compares different growth bases

`studio/compute.py:676` computes period-over-period change; `qoq` at line 698 uses quarters. `studio/template_fill/facts_trend.py:42` subtracts annual year-on-year growth from the latest quarter-on-quarter growth and labels the result accelerating, slowing, or holding. The glossary repeats this interpretation in `core/definitions/terms.yaml:280`.

These are different comparisons. Their difference alone does not establish acceleration, deceleration, or an annual run rate. Seasonality and the previous quarter's size can dominate the quarterly percentage.

Offline reproduction: two years both containing quarterly premium of `[100, 100, 100, 200]` have 0% annual growth and 0% Q4 year-on-year growth. Q4 grows 100% over Q3 in both years. The current function nevertheless labels the latest result **accelerating**.

For the illustrative 4,651% sentence, the actual prior-quarter premium, absolute change, period completeness, and comparison basis must be checked before interpreting the percentage. A small denominator is a possibility, not a confirmed explanation of the user's example. Fast growth is also not automatically appropriate for a “What's not working” column.

Later fix: report quarter versus the same quarter last year and YTD versus matched prior-year YTD. Keep QoQ available with its comparison explicitly labelled. Require comparable time series and adequate context before making a momentum claim. Correct the computation, glossary, examples, and tests together.

### 2. Some evidence loses the direction of change and the prior value

`studio/template_fill/commentary_evidence.py:129` renders carrier percentage movement with `abs()`. The money movement at line 132 and Marsh growth at line 144 do the same without adding an increase/decrease label. The quarter fact at line 297 also removes its sign. Other evidence families do preserve direction, so the defect is not universal.

Offline reproduction: otherwise identical inputs with carrier movement of +20% / +$20 and -20% / -$20, Marsh movement of +10% and -10%, and quarterly movement of +25% and -25% produce **identical evidence packs** when these are the only relevant families.

The carrier's prior premium is present in the raw input but is not emitted as its own fact. Without a draft or other directional facts, an AI cannot reliably reconstruct whether these movements were gains or losses. Numeric token verification also strips signs (`studio/ai/verifier.py:25`).

Later fix: preserve signed raw values and explicit direction; include current value, prior value, absolute change, percentage change, unit, and comparison periods. Verify that the sentence's direction agrees with the cited metric.

### 3. Product, geography, denominator, and benchmark need explicit context

The raw feedback facts at `studio/template_fill/feedback.py:394` use the correct filtering inputs for calculations, but the resulting pack does not carry a structured product/country scope. Evidence repeatedly says “in this scope.” The section prompt at `studio/template_fill/commentary_batch.py:316` names the carrier but does not supply an explicit product and geography header.

When the input describes a product such as Environmental, industry-level movers do not necessarily reveal which product they belong to. The AI must be told the actual scope; it should not have to reconstruct it from figures or a deterministic draft.

There is also a definition mismatch. `studio/compute.py:585` averages the largest up-to-five carriers in the scope. It removes the subject-carrier filter, does not explicitly exclude the subject, and does not resolve a configured peer group in this function. `core/definitions/terms.yaml` describes the peer average as coming from the Peers table. The evidence always labels this “top-5.”

Offline reproduction: with only three carrier premiums of 50, 30, and 20, this function returns an average of 33.33 and share of 33.33%, without returning an actual peer count. The downstream label still says top-5.

Later fix: define the intended comparison population, state whether the subject is excluded, return the actual count and selection basis, and ensure displayed terminology matches the calculation. Add explicit carrier, product, geography, reporting period, and denominator metadata to every pack. Distinct scopes must remain distinguishable even if their rounded figures happen to match.

### 4. AI fact selection bypasses an existing materiality filter

`studio/template_fill/feedback.py:574` uses 1% of carrier premium as a minimum for naming certain deterministic movers. However, `_mover_items` at `studio/template_fill/commentary_evidence.py:239` includes movements without this filter.

Offline reproduction: a $2K Manufacturing decline on a synthetic $100M carrier book is excluded from the deterministic named-mover sentence but remains available to the AI as a citable fact. Whether $2K matters in the user's actual example is unknown; the issue is that both writing paths apply different selection standards.

Later fix: rank and qualify findings before authorship. Use absolute size, relative importance, comparison reliability, and the slide's purpose. Do not impose one universal dollar threshold on every product and country. Permit fewer bullets when fewer findings deserve attention.

### 5. The writing instructions reward dense, ambiguous commentary

`studio/template_fill/commentary.py` asks for a claim, driver, comparison, and consequence in every line, with sentences around 25 words. It tells the model to form a connected argument, look for tension, avoid hedging, and name the carrier once before referring to “the book” (lines 328, 384, 418, 431, and 529).

The challenges brief asks for a mechanism involving renewals and future persistence, while the verifier correctly disallows renewal, retention, appetite, or capacity assertions without evidence. This creates pressure to supply an explanation that premium totals alone cannot establish.

These rules plausibly explain the writing style reported by the user, though attributing the exact output requires a captured generation. The prompt's worked “GOOD” example itself joins several metrics and comparisons into one sentence.

Later fix: one finding per bullet, normally one or two short sentences. Name the carrier/product and comparison plainly where ambiguity is possible. Allow a clear observed result without forcing a causal story. Separate a measured contribution (“Manufacturing accounts for the decline”) from an operational explanation (“pricing caused the decline”). Use operational explanations only when supported by operational data.

### 6. Verification does not establish usefulness or correct section placement

The numeric gate checks whether the sentence's number tokens appear in evidence. The style gate mainly checks punctuation, prohibited expressions, metric restatement, and repeated carrier openings (`commentary.py:725`).

The semantic verifier does check unsupported claims and incorrect terminology. However, its prompt says “When in doubt, KEEP” and explicitly excludes style, length, and tone (`commentary_verify.py:91`). It receives sentences and evidence without the owning column's brief. If the verifier response is missing or has the wrong number of verdicts, it keeps the input (`commentary_verify.py:132`). Offline mocking confirmed the missing-response behavior; it was not observed in a live run.

Final commentary QA logs issues rather than blocking delivery (`studio/template_fill/assemble.py:290`). Editorial deduplication exists, but a unique point is not necessarily a useful point or a point in the correct column.

Offline reproduction: three adapted versions of the user's examples passed numeric validation and the style gate, and produced no commentary QA issues. Adaptations normalized numeric formatting and sentence punctuation and excluded the pasted HTML entity; this was not a test of exact end-to-end reproduction or live semantic approval.

Later fix: give verification the column's purpose and explicit evidence semantics. Add checks for an understandable subject and comparison, supported direction, meaningful size, appropriate section, and an implication that follows from the evidence. Missing verification should result in retry or a clearly unverified state, rather than a successful verification label. Repair only failed findings.

### 7. Existing tests and a separate engine can give misleading confidence

The authoring export calls `studio.template_fill.assemble.assemble_deck` (`studio/authoring/generate.py:261`). A separate `studio/commentary` implementation, used by `studio/pipeline/qbr_pipeline.py`, has checks for prior/current premium, materiality, and large percentage movements. Passing those tests does not prove the template export uses those protections.

100 targeted tests passed in this review. Some tests in `tests/test_commentary_fact_families.py:85` explicitly expect the invalid comparison of annual growth and quarterly growth to produce a momentum label. The tests therefore preserve part of the problem.

Later fix: add regression cases at the evidence-to-commentary seam actually used by Studio export. Replace incorrect expected business interpretations; retain valid existing coverage. Confirm shared controls are wired into both paths before relying on them.

## What the illustrative points should communicate

**Manufacturing, conditional on matching scope and period:**

> The carrier's Manufacturing premium placed through Marsh fell by $2K, while Marsh's total Manufacturing premium rose by $6K over the same period. The carrier therefore received a smaller share of those placements.

This identifies two different quantities rather than referring ambiguously to “the same book.” It describes the result, not the reason for it. It only deserves slide space if the movement is material.

**Environmental, conditional on the intended denominator and benchmark:**

> The carrier received 12.9% of Environmental premium placed through Marsh in the selected scope, compared with an average of 18.5% for the defined comparison group—a gap of 5.6 percentage points.

The final sentence must replace “selected scope” and “defined comparison group” with the actual geography, period, and benchmark description, either in the text or an unambiguous nearby header. This is a relative placement position; it is not Environmental's share of the carrier's own portfolio and is not total-market share.

Being below the comparison group is a finding to investigate, not proof of poor execution or a realistically winnable premium opportunity. Appetite, capacity, access, and relevant placement/renewal evidence determine the next action. A safe proposed next step is to review whether the gap sits in segments the carrier wants and is able to write.

**The 4,651% statement:** do not simply improve its wording. Establish the comparison periods and absolute premiums first. Remove the annual-run-rate conclusion unless a valid analysis supports it.

The `&#x20;` in the pasted example is an encoded space. Its origin in export, copying, or another text layer has not been established. Treat cleanup separately from analytical quality.

## Proposed sequence for the later fix

1. **Correct the evidence:** direction, prior values, comparable periods, explicit scope, and actual benchmark definition/count. Correct the momentum glossary and calculation together.
2. **Select meaningful findings:** attach materiality, reliability, positive/negative/neutral classification, and eligible slide sections before asking the AI to write. Keep performance, shortfalls, and opportunities distinct.
3. **Simplify authorship:** use one finding per bullet and plain business language. Give the AI facts and analytical constraints; it can still author all final prose. Do not require unsupported “why” statements or fill a fixed quota with weak points.
4. **Evaluate the exported result:** build a reference set of 20–30 evidence packets across Portfolio Solutions and Trading Landscape, including cases where the correct answer is to omit a point. Have ICG reviewers choose or write acceptable commentary from the same evidence. Compare results without revealing which version produced them.
5. **Release against that reference set:** require correct facts, direction, period, scope, and benchmark; understandable meaning on first reading; appropriate materiality and section; and no unsupported causal or opportunity claims. Include tests for tiny bases, negative growth, seasonal quarters, incomplete periods, fewer than five peers, and insufficient findings. Version the prompt/glossary and invalidate affected commentary caches.

The reference examples define the quality standard, not a set of sentences to repeat with different numbers. Measure whether a carrier-facing reader understands what happened, against what comparison, why it deserves attention, and what remains to be investigated.

## Verification record

- Read the local authoring-to-template-export path, evidence builders, trend computation, glossary, writer prompts, verifiers, editorial routing, and relevant tests.
- Ran offline probes through the existing functions using synthetic facts and a mocked unavailable verifier. No paid model calls or external data transfers were made.
- Ran `tests/test_commentary_fact_families.py`, `tests/test_commentary_evidence.py`, `tests/test_commentary_acceptance.py`, `tests/test_commentary_qa.py`, and `tests/test_commentary_engine.py`: **100 passed**.
- No application implementation, existing test, configuration, or user artifact was edited. This diagnostic document is the only added deliverable.
