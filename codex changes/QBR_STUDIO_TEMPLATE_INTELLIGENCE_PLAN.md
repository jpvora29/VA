# QBR Studio Template Intelligence And Commentary Quality Plan

## Status

Planning note for future implementation. This document does not change the current runtime.

## Objective

Improve QBR deck quality for ICL leaders and carrier sharing by making Studio less dependent on one fixed PowerPoint template and by making each slide's commentary more evidence-grounded, business-relevant, and verifiable.

The upgraded flow should keep the code simple and modular. The source of truth remains deterministic data, rules, and validation. LLM/deep-agent behavior should assist with interpretation, mapping, and drafting, but should not become the authority for numbers or business truth.

## Current Problem

The current Studio flow works, but it is still strongly shaped by the currently registered templates and binding maps. That creates several risks:

- Future template changes may require code or hand-authored map changes.
- New templates are not easy to onboard in a governed way.
- Commentary quality is uneven because some narrative decisions live in code while other rules live in YAML.
- Semantic QA is limited compared with what is needed for a carrier-ready QBR.
- The system can fill slides, but it does not yet fully understand slide intent, evidence requirements, or commentary eligibility.

## Design Principles

- Keep deterministic code as the source of truth.
- Keep the design modular and easy to reason about.
- Use dataclasses for internal contracts.
- Use Pydantic or structured schemas only at LLM boundaries.
- Avoid complex design patterns, heavy inheritance, hidden framework behavior, and over-engineering.
- Prefer small pure functions for parsing, mapping, rule checks, and validation.
- Make orchestration read like a clear sequence of steps.
- Use a simple pipeline function that calls named sub-functions in order.
- Use `asyncio` for independent work that can safely run in parallel, especially template parsing, evidence preparation, LLM labeling, commentary drafting, and QA checks.
- Keep async output deterministic by preserving input order when results are collected.
- Make every number traceable to a fact ID.
- Make every commentary sentence verifiable.
- Keep the existing fixed-template flow working while the new flow is introduced.

## Target Architecture

```text
Structured SQL output
  -> EvidencePack
  -> Evidence graph
  -> ReportPlan
  -> TemplateDescriptor
  -> LayoutIntent
  -> BindingMap
  -> RenderPlan
  -> QAReport
  -> PowerPoint deck
```

## Pipeline Style

The implementation should have an easy-to-read pipeline function that makes the system flow obvious.

Example shape:

```python
async def build_qbr_deck_pipeline(selection: StudioSelection) -> QBRPipelineResult:
    sql_output = await load_structured_sql_output(selection)
    evidence_pack = build_evidence_pack(sql_output)
    evidence_graph = build_evidence_graph(evidence_pack)

    template_descriptor = parse_template(selection.template_path)
    layout_intent = await detect_layout_intent(template_descriptor)
    binding_map = validate_or_create_binding_map(template_descriptor, layout_intent)

    report_plan = build_report_plan(evidence_pack, evidence_graph, selection)
    render_plan = build_render_plan(report_plan, binding_map)

    commentary_plan = build_commentary_plan(report_plan, evidence_graph, render_plan)
    commentary = await draft_and_verify_commentary(commentary_plan, evidence_pack)

    qa_report = run_qbr_qa(render_plan, commentary, evidence_pack, binding_map)
    deck_path = export_qbr_deck(render_plan, commentary, qa_report)

    return QBRPipelineResult(deck_path=deck_path, qa_report=qa_report)
```

Use parallel execution inside individual steps when it is naturally safe:

```python
layout_task = detect_layout_intent(template_descriptor)
commentary_tasks = [
    draft_slide_commentary(slide_plan, evidence_pack)
    for slide_plan in commentary_plan.slides
]

layout_intent, slide_commentary = await asyncio.gather(
    layout_task,
    gather_ordered(commentary_tasks),
)
```

Rules for async usage:

- Parallelize independent LLM calls and independent QA checks.
- Do not parallelize steps that depend on prior validation.
- Do not let parallel execution change slide order, fact order, or QA issue order.
- Keep a synchronous wrapper for Dash callbacks or existing non-async entrypoints if needed.
- Keep each sub-function testable without running the entire pipeline.

## Core Contracts

### EvidencePack

Structured, validated facts from SQL output.

Responsibilities:

- Store every metric with a stable `fact_id`.
- Store rendered values for currency, percentage, rank, and count formatting.
- Store dimensions such as carrier, country, product, industry, practice, and year.
- Store provenance back to SQL/query/source.
- Store current period, comparison period, and derived movements.

This layer should contain no narrative and no slide geometry.

### Evidence Graph

A lightweight graph over the structured evidence, not a generic knowledge graph.

Recommended graph objects:

- Carrier
- Product
- Country
- Industry
- Practice
- Period
- Metric
- Movement
- Driver
- Chart series
- Commentary claim

Example relationships:

- product has current premium
- product has prior premium
- product has YoY movement
- country contributes to movement
- industry is material if premium clears threshold
- commentary claim cites fact IDs

The graph should help commentary reason across related facts, but it should not replace deterministic calculations.

### ReportPlan

The business argument for the QBR.

Responsibilities:

- Select what matters for the audience.
- Decide which findings belong in the main deck versus appendix.
- Separate observation, driver, interpretation, recommendation, and decision.
- Link every claim to fact IDs.
- Record data gaps instead of filling unsupported sections with generic commentary.

### TemplateDescriptor

Deterministic structure extracted from a PPTX.

Responsibilities:

- Slide count and slide size.
- Slide index and layout name.
- Shape IDs, names, types, positions, sizes, and text.
- Tables, charts, pictures, placeholders, and groups.
- Existing tokens/placeholders.
- Stable references that later binding maps can use.

This should be generated by Python/OpenXML logic, not by the LLM.

### LayoutIntent

Semantic interpretation of the template structure.

Responsibilities:

- Classify slide purpose, such as executive summary, trading summary, product deep dive, country view, SWOT, feedback, methodology, or appendix.
- Classify shapes as title, subtitle, KPI, commentary, chart, table, footer, source, decorative, or manual.
- Identify expected data type for each content slot.
- Identify confidence and ambiguity.

This is where `deep_agent` can help.

### BindingMap

Approved mapping between template slots and business content.

Responsibilities:

- Map shape IDs to semantic roles.
- Map chart/table placeholders to data specs.
- Map commentary boxes to commentary contracts.
- Mark manual-only, decorative, and intentionally blank objects.
- Support multiple templates without changing the compute layer.

Draft binding maps can be suggested by `deep_agent`, but activation should require deterministic validation and human approval.

### RenderPlan

The final deck population plan.

Responsibilities:

- Define which data goes into each chart, table, title, KPI, and commentary slot.
- Preserve template geometry.
- Keep chart/table data linked to source facts.
- Record intentionally hidden or blank slides/slots.

### QAReport

Validation output before final export.

Responsibilities:

- Check that all required slots are filled.
- Check that charts and tables match the selected data.
- Check that commentary cites valid facts.
- Check materiality and business rules.
- Check confidentiality rules.
- Mark errors, warnings, and informational notes.

## Deep Agent Usage

Use `deep_agent` for the parts that require semantic judgment:

- Template structure interpretation.
- Slide intent identification.
- Shape and slot role labeling.
- Binding map suggestions.
- Commentary drafting from approved evidence.
- Human-readable QA explanations.

Do not use `deep_agent` for:

- Raw PPTX geometry extraction.
- SQL generation as the final authority.
- Premium, YoY, rank, or chart calculations.
- Final chart population validation.
- Final commentary truth validation.
- Deciding whether unsupported claims are allowed.

Recommended model usage:

- Use GPT-5 mini for first-pass layout labeling, binding suggestions, and commentary drafting.
- Require strict JSON/schema outputs.
- Require confidence scores.
- Reject invented slide IDs, shape IDs, fact IDs, measures, or dimensions.
- Escalate low-confidence or complex templates to a stronger reasoning model or human review.

## Commentary Improvement Plan

Each slide should have a commentary contract that defines what the slide is allowed to say.

Recommended commentary structure:

```text
What changed
  -> Why it matters
  -> What drove it, if supported
  -> What leaders should watch or decide next
```

Commentary should be generated from allowed facts, not from broad model knowledge.

Every sentence should carry fact references:

```json
{
  "sentence": "Premium increased 18.4% YoY to $42.1M, up from $35.6M last year.",
  "fact_ids": ["premium_current_2026", "premium_prior_2025", "premium_yoy_2026"]
}
```

## YAML Rule Examples

Business rules should live in YAML so non-engineers can tune thresholds without code changes.

```yaml
yoy:
  high_growth_pct: 25
  always_include_current_and_prior: true
  require_absolute_change: true
  suppress_if_current_premium_below: 5000000

materiality:
  min_premium_for_industry_commentary: 5000000
  min_premium_for_practice_commentary: 5000000
  min_share_of_portfolio_pct: 3

drivers:
  require_driver_for_large_change: true
  large_change_pct: 20
  min_driver_contribution_pct: 40

commentary:
  max_bullets_per_slide: 3
  max_sentences_per_bullet: 2
  block_named_peer_mentions: true
  block_causal_language_without_driver_fact: true
```

Example rules:

- If YoY is mentioned, current-year and previous-year premium must also be shown.
- If growth is unusually high, include absolute movement, current premium, and prior premium.
- Do not include industry, practice, product, or country commentary unless premium is greater than the materiality floor.
- Do not say something "drove" a result unless driver/decomposition evidence exists.
- Do not mention named peers in carrier-facing output.

## Proposed Module Layout

Keep modules small and direct.

```text
studio/template_intelligence/
  descriptor.py        # dataclasses for TemplateDescriptor, SlideDescriptor, ShapeDescriptor
  parse_pptx.py        # deterministic PPTX -> TemplateDescriptor
  layout_agent.py      # deep_agent adapter: TemplateDescriptor -> LayoutIntent
  binding.py           # BindingMap dataclasses and validation
  registry.py          # approved template configs

studio/commentary/
  contracts.py         # CommentaryContract dataclasses
  planner.py           # EvidencePack/EvidenceGraph -> CommentaryPlan
  agent.py             # deep_agent adapter for draft wording
  verify.py            # sentence/fact/rule validation

studio/qa/
  report.py            # QAReport dataclasses
  template_checks.py   # slot/chart/table/template validation
  content_checks.py    # fact/commentary/rule/confidentiality validation

studio/pipeline/
  qbr_pipeline.py      # readable step-by-step orchestration
  async_utils.py       # gather_ordered, bounded concurrency helpers
```

Existing modules should be adapted gradually rather than replaced at once.

## Implementation Phases

### Phase 1: Template Descriptor

- Build deterministic PPTX parser.
- Produce `TemplateDescriptor`.
- Add tests using current overall, product, and country templates.
- Verify slide and shape IDs remain stable across repeated runs.

### Phase 2: Layout Intent Agent

- Add `deep_agent` adapter for template structure identification.
- Use GPT-5 mini with strict structured output.
- Return confidence, role labels, and ambiguity notes.
- Add deterministic validation that all returned references exist in the descriptor.

### Phase 3: BindingMapV2

- Create reusable binding map schema.
- Add adapter from existing static maps to the new schema.
- Add validation for missing, duplicate, invalid, and low-confidence mappings.
- Keep current template export path working.

### Phase 4: Evidence Graph And Commentary Contracts

- Convert structured SQL output into `EvidencePack`.
- Build lightweight evidence graph from facts and relationships.
- Add commentary contracts per slide type.
- Move key thresholds into YAML.

### Phase 5: Commentary Agent And Verifier

- Use `deep_agent` to draft commentary from a bounded evidence packet.
- Require every sentence to cite fact IDs.
- Run deterministic verifier after drafting.
- Strip or fail commentary that includes unsupported numbers, unsupported causality, or rule violations.

### Phase 6: QAReport In Studio

- Add a QA report before export.
- Show critical failures, warnings, and notes.
- Block export only on critical failures.
- Allow warnings when content is intentionally blank or manually approved.

## Testing Strategy

Template tests:

- Current templates parse successfully.
- Shape references are stable.
- Layout agent cannot return nonexistent IDs.
- Low-confidence mappings are flagged.
- A new template can produce a draft map without code changes.

Commentary tests:

- YoY commentary includes current and prior premium.
- Commentary is suppressed below materiality thresholds.
- Large movement commentary includes absolute movement.
- Driver language fails without decomposition facts.
- Unsupported numbers are removed or marked as critical failures.
- Named peer references are blocked in carrier-facing output.

QA tests:

- Charts receive expected rows and measures.
- Tables match selected data slices.
- Required slots are filled.
- Intentionally blank slots are recorded.
- QA report groups errors, warnings, and notes clearly.

Regression tests:

- Existing fixed-template exports continue to work.
- Existing generated deck path continues to work.
- `STUDIO_AI=off` still produces deterministic output.
- Missing or invalid YAML falls back to safe defaults.
- Async pipeline output remains deterministic across repeated runs.
- Parallel commentary drafting preserves slide order.
- Pipeline sub-functions can be tested independently.

## Success Criteria

- A future template can be parsed and mapped without changing compute code.
- Template changes produce explicit mapping/QA feedback instead of silent bad output.
- Commentary reads like an insurance analyst wrote it for ICL leaders and carriers.
- Every number in commentary can be traced to structured evidence.
- Charts and tables are validated against their data specs.
- Business rules can be updated in YAML.
- GPT-5 mini/deep_agent improves structure detection and wording without becoming the source of truth.
- The implementation remains understandable to a Python engineer without learning a complex framework.

## Recommended Defaults

- Default model for layout and commentary drafting: GPT-5 mini.
- Default authority for facts: deterministic SQL/EvidencePack.
- Default authority for validation: YAML rules plus Python validators.
- Default export behavior: preserve current templates until BindingMapV2 is approved.
- Default failure behavior: fail safe, show QA issue, do not invent content.
- Default orchestration style: one readable pipeline function with small named steps.
- Default async behavior: bounded parallelism for independent work only, with deterministic result ordering.
