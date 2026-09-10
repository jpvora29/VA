# QBR Studio: concrete commentary solution

Design specification recorded 10 September 2026. Implementation is now in the local checkout; see [implementation and validation](qbr-commentary-implementation.md). The failure probes below describe the earlier version. The user's examples are illustrative; the underlying figures and reporting scope have not been verified.

## Product standard

Write commentary that an ICG consultant can read aloud to a carrier without translating it. A reader should immediately know whose performance is described, what changed, which comparison matters, and why the finding deserves attention. Include an action where the section calls for one and the evidence supports it.

Each bullet contains one finding, normally expressed in one or two short sentences. The quality measure is understandable, useful analysis. Sentence-opening variety, causal words, and the number of implications are not substitutes for that measure.

## Additional evidence from the latest examples

An offline probe of the existing `_keep_lines` function returned:

| Input | Current writing check |
|---|---|
| “Share of Marsh Services premium held by Example Carrier fell by 8.9 percentage points to 16.8%.” | Rejected as `metric_readout` |
| The user's Services example, with its typo corrected | Accepted |
| The user's unnamed client-segment example, with its typo corrected | Accepted |

The unnamed example also scores 100% on the existing regex-based implication measure because it contains “so.” This does not establish that a live AI reviewer approved these sentences; it establishes the behavior of the deterministic writing check and score.

`studio/template_fill/segment_prose.py` explicitly explains that the wording avoids opening with “Share,” and that dropping consequence clauses worsened the implication metric. The current behavior therefore has a concrete connection to the style of the generated prose.

There is another evidence defect directly relevant to these examples: `_losing_value` in `studio/template_fill/commentary_evidence.py:370` renders the Marsh premium change using `abs()`. Synthetic Services rows with Marsh premium growth of +38.6% and decline of -38.6% both produce “on a pool that moved 38.6%.” The writer is missing information needed to choose “grew” or “fell.”

## Proposed generation flow

**Validated metrics → selected findings → AI-written bullets → factual and reader checks → slide.**

Final prose remains AI-authored. Deterministic code calculates metrics, checks comparability, and makes findings eligible for sections. Structured finding records replace finished prose as the planning input. This should use the existing section author and reviewer calls where practical; the proposal does not require a new model call for every bullet.

### 1. Give each figure a complete meaning

Every evidence packet must carry:

- Carrier, product, geography, dimension name, and named dimension value.
- Reporting period and comparison period, including whether each is complete.
- Metric name, unit, signed raw value, and approved display value.
- Current and prior premium; absolute and percentage changes where valid.
- Current and prior share; share movement explicitly in percentage points.
- The share denominator: Marsh premium in the same product/geography/period.
- Benchmark population, selection method, actual count, and subject inclusion/exclusion.
- Materiality and comparability status; missing or unreliable inputs.

Use separate citable facts for separate metrics. A text value such as “16.8% of a $5M pool that moved 38.6%” should not be the only representation of three distinct measurements.

Compute any new display value before authorship. For example, 25.7% is the implied prior share from the illustrative 16.8% current share and 8.9-point decline. A production writer should receive the actual calculated prior share from raw source values rather than independently deriving it from rounded prose.

Correct the previously identified sign loss, missing prior values, momentum comparison, and benchmark mismatch in this stage. The glossary must agree with those computations.

### 2. Select findings for a business question

Prepare candidate findings such as share loss in a growing Marsh placement segment, a material contributor to premium growth, or a gap against an explicitly defined benchmark. A candidate should include:

- A stable finding ID and supporting fact IDs.
- The named entity and exact metric relationship.
- Materiality and evidence quality.
- Eligible sections and any limits on interpretation.

Examples of interpretation limits: a share decline alone does not establish a premium decline; premium growth does not establish higher demand; an observed placement gap does not establish appetite, access, capacity, or winnable business.

Rank eligible findings by materiality, evidence quality, and relevance to the section. The largest percentage should not automatically win. Choose the strongest non-duplicative findings; allow a section to have fewer bullets when evidence is limited.

| Section | Question the finding must answer |
|---|---|
| What's working | Where did the carrier perform well, and against what comparison? |
| What's not working | Where is the material decline, share loss, or benchmark shortfall? |
| Growth opportunities | Which named placement gaps deserve investigation, and what must be validated? |
| Trading Landscape | How does the carrier compare with Marsh placements and the defined comparison group? |
| Priorities | What specific investigation or action follows from the strongest findings? |

A positive growth observation cannot become a challenge solely because the challenge column needs another bullet. A gap should not become an execution failure without evidence of the carrier's intended appetite or objectives.

### 3. Replace the competing writing rules with a short brief

Recommended author instruction:

> Write clear QBR commentary for ICG to discuss with a carrier. Use only the selected findings and cited evidence. Each bullet must stand on its own and contain one finding, normally in one or two short sentences. Name the relevant carrier, product, industry, or client segment, and say exactly which metric changed. State the comparison in plain language. Use only the figures needed to understand the finding; supporting detail can remain in the chart or evidence panel. Prefer “share fell from X% to Y%” where both values are available. Add a business implication only when it follows from the evidence. Recommend an action only in an appropriate section and distinguish an investigation from a confirmed solution. You may begin with “Share,” “Premium,” or the carrier name. Do not force a causal explanation, a dramatic conclusion, a linking phrase, or a fixed bullet count. If a finding lacks a named segment, a defined comparison, or sufficient evidence, return that gap for repair instead of guessing. Return the finding ID and fact IDs with every bullet.

Supporting house rules:

- Explicit references take priority over variety. Repeating the carrier name is acceptable when it prevents ambiguity.
- Use “Marsh-placed premium” or “premium placed through Marsh” where that is the measured quantity. Reserve “demand” for evidence that actually measures demand.
- Use “share of Marsh placements” or “share of Marsh premium” with the relevant product/segment context. Avoid an unexplained “share of a pool.”
- Normally show two or three essential figures, rather than all available metrics. This is an editorial guide, not a numeric rejection threshold.
- Remove endings such as “pressure sat in the placement base” unless they can be replaced with a specific supported observation.
- “Fastest-growing,” “largest,” “clearest,” and other comparative rankings require a defined, sufficiently complete comparison population and a suitable metric. Otherwise omit them.
- Do not infer why the carrier lost share from premium and share alone. Pricing, retention, submissions, quote conversion, appetite, capacity, and service need their own evidence.
- Do not force an action into every performance bullet. A useful observed finding can stand on its own.

### 4. Check factual correctness and comprehension separately

Replace the metric-opening rejection. Retain meaningful checks for malformed output and unsupported values, while checking direction, units, denominator, and period against structured evidence.

Give the existing semantic reviewer the selected finding, the section question, the scope, and the relevant facts. Ask it to assess:

1. **Correctness:** Does every asserted value, direction, comparison, ranking, and explanation follow from the evidence?
2. **Clarity:** Can the reader identify the entity, metric, and comparison without interpreting “the book,” “same pool,” or an unnamed segment?
3. **Relevance:** Does this finding answer the section's question, and is it material enough for the slide?
4. **Usefulness:** Does the bullet contribute a specific finding without a redundant or unsupported concluding clause?
5. **Independence:** Does it stand on its own without an earlier “also” or “the same” sentence?

Return concrete repair reasons such as `unnamed_segment`, `ambiguous_metric`, `comparison_period_missing`, `unsupported_superlative`, `share_confused_with_premium`, or `wrong_section`. A missing verifier response must not count as successful verification. Retry or expose an unverified state according to the chosen delivery policy.

Repair only affected bullets or findings, using the existing batched workflow. If the missing information cannot be recovered, omit the finding or show a deliberate data-availability note in the appropriate place. Never fill the space with a weaker invented conclusion.

## How the latest examples should read

### Services

Assuming all figures describe the same product, geography, and comparison period:

> The carrier lost share in Marsh's Services placements despite growth in the overall Services premium placed by Marsh. Its share fell by 8.9 percentage points to 16.8%, while Marsh's Services premium grew 38.6%.

A more compact alternative, if the source confirms prior share of 25.7%:

> The carrier's share of Marsh's Services premium fell from 25.7% to 16.8%, while Marsh's Services premium grew 38.6%.

These are alternative expressions of the same finding; only one should appear. The slide header should identify the reporting and comparison periods and product/geography. If it does not, the bullet must include that context. The $5M figure can remain in the supporting table unless the segment's size is essential to establishing materiality.

This is relative share loss. Whether the carrier's absolute premium also fell must be checked separately against the raw values.

### Unnamed client segment

The first example cannot become finished commentary until the system retrieves the segment name and establishes what the 3.7% average measures. It also needs evidence for the claim that the segment was fastest-growing.

Conditional writing example only:

> The carrier's share of Marsh placements in [named client segment] fell by 1.5 percentage points, while Marsh's premium in that segment grew 149.5%.

The placeholder must never reach the slide. Add the 3.7% benchmark only if its meaning is established and it helps explain this particular finding. Check the growth base and period completeness before selecting such an extreme percentage. The $17M size may belong in the supporting evidence rather than in the bullet.

If the segment cannot be identified or the comparison is unreliable, the system should not write the point.

## Implementation order and completion criteria

1. **Evidence and calculations:** update `commentary_evidence.py`, `facts_trend.py`, the relevant `compute.py` and segment evidence interfaces, and `core/definitions/terms.yaml`. Complete when opposite movements remain distinct, comparable periods are explicit, and benchmark labels match computation.
2. **Finding selection:** update feedback-to-authoring preparation and editorial allocation. Allocate actual eligible findings to columns, not just broad fact families. Complete when a column cannot receive an incompatible finding merely to avoid repetition or fill space.
3. **Writer and checks:** simplify `commentary.py`; remove the misleading opening gate in `commentary_metrics.py`; update `commentary_batch.py` and `commentary_verify.py` to pass section purpose and typed evidence through review. Review `segment_prose.py` wherever deterministic prose remains in use or reaches the author. Complete when the clear metric sentence survives and the ambiguous examples are repaired or rejected for specific reasons.
4. **End-to-end evaluation:** use 20–30 ICG-reviewed packets across Portfolio Solutions and Trading Landscape. Include strong growth, premium growth with share loss, decline, tiny bases, seasonal patterns, missing segments, ambiguous benchmarks, thin evidence, and different portfolio sizes. Inspect both commentary and rendered slide fit.
5. **Controlled release:** compare current and proposed outputs on identical evidence without identifying their source to reviewers. Proposed target: zero factual/comparison errors in the reviewed set and at least 90% of bullets understandable on first reading. Review usefulness and section relevance separately. This is an evaluation target, not a guarantee of future performance. Version prompts, evidence schemas, and glossary changes, and invalidate affected caches.

Keep the current model constant for the first comparison so the effect of these changes is measurable. Consider a different model only after the evidence and quality standard are corrected and a reference evaluation can show whether it improves the outcome.

The user-provided sentences belong in the evaluation set as failure examples. They should not become universal templates or hard-coded exceptions.
