# Robustness, Context Engine, Skills, and Evaluation Pointers

## Purpose

This note consolidates the main improvement pointers for Virtual Analyst. It is
an implementation guide and index for the more detailed proposals under
`codex changes/`. Nothing in this file is connected to the current runtime.

The core direction is:

> Keep workflow boundaries explicit, centralize governed context, load focused
> skills progressively, enforce critical rules in code, and validate behavior
> through an observable evaluation harness.

Reference used for the Context Engine discussion:
[Qodo - Understanding the Context Engine](https://docs.qodo.ai/core-concepts/context-engine).

Qodo describes its Context Engine as a shared knowledge layer that gathers,
connects, and reasons over repository, historical, organizational, and workflow
context. The five-stage design below is the proposed VA implementation model;
the linked Qodo page describes the goals and capabilities, but does not publish
that exact internal five-stage decomposition.

## 1. Current Architecture Assessment

Overall assessment: **6.4/10**.

The current system is a good prototype/internal-beta architecture with several
strong runtime controls, but it is not yet a consistently measurable production
analytical platform.

| Dimension | Score | Assessment |
|---|---:|---|
| Runtime robustness | 7/10 | Timeouts, scoped retries, SQL validation, HITL, checkpointing, fallbacks, recursion limits |
| Accuracy architecture | 6.5/10 | Structured outputs and grounded SQL help, but golden evaluations are not active release gates |
| Pricing effectiveness | 6/10 | Token tracking exists, but USD budgets, route budgets, escalation policies, and cost-quality benchmarks do not |
| Runtime harness | 7.5/10 | Strong LangGraph orchestration, streaming, telemetry, cancellation, and specialist solvers |
| Test/evaluation harness | 4/10 | Coverage is narrow relative to the production surface |
| Modularity | 6.5/10 | Improved from the original monolith, but workflow assembly and some large modules remain duplicated or broad |
| Maintainability | 5.5/10 | Broad state, oversized modules, implicit contracts, and broad exception handling increase change risk |
| Data/security safety | 7/10 | Read-only SQL validation, pre-execution checks, redaction, and peer confidentiality are solid foundations |
| Deployment readiness | 5/10 | SQLite and daemon-thread execution suit a prototype better than multi-worker production |

### Current Strengths

- Chat and Pitch Builder already have separate states and checkpointers.
- Deterministic routing avoids unnecessary model calls for clear requests.
- SQL is validated as read-only and checked before execution.
- Model calls have timeouts and bounded retries.
- Usage is measured by call, agent, turn, and conversation.
- Analyst solvers have bounded recursion and context summarization.
- Boardroom, Chat, and Pitch Builder are conceptually separate surfaces.

### Main Score Limiters

1. Accuracy is mainly prompt-designed rather than empirically demonstrated by
   an active golden evaluation suite.
2. Boardroom widget reliability depends on strict normalized fields surviving
   a potentially lossy evidence handoff.
3. Token visibility is not cost control; there are no dollar ceilings,
   route-level budgets, or explicit model escalation policies.
4. Main-graph routing, HITL resume, SQL repair, Boardroom, persistence, and
   Pitch Builder need stronger direct coverage.
5. Several workflow and UI modules still own too many responsibilities.
6. Environment reproducibility has been fragile because the managed virtual
   environment can point to a missing interpreter.

The most direct route toward **8/10** is an executable evaluation harness,
lossless evidence contracts, cost budgets, graph-level tests, and bounded
context assembly.

## 2. Robustness

### Preserve Workflow Boundaries

Chat, Boardroom, Pitch Builder, and deterministic data flows should not be
collapsed into one broad agent or state object.

- Keep separate outer states for Chat and Pitch Builder.
- Share narrow typed artifacts such as `RoutingContext`, `SQLPlan`,
  `SQLEvidence`, `AnswerEvidence`, and `FailureInfo`.
- Compose reusable graph modules for routing, SQL execution, repair, evidence
  normalization, and deterministic answers.
- Keep HITL, follow-ups, streaming, and charts as Chat-specific capabilities.
- Keep batch questions, KPI extraction, narrative construction, claim
  validation, and DOCX handoff as Pitch-specific capabilities.
- Treat Boardroom as a presentation of normalized evidence, not as another
  synonym for Chat or Pitch Builder.

### Add Deterministic Guardrails

LLM instructions alone should not enforce high-risk constraints.

- Validate allowed tables and columns before SQL execution.
- Enforce read-only SQL in code.
- Normalize chart specifications before rendering.
- Prevent profile-disabled fields or features from being written.
- Validate that generated claims reference executed evidence.
- Add hard limits for model calls, tool calls, retries, and row payloads.
- Distinguish transient failures from invalid SQL and business-rule failures.

### Make Failures Structured

Use typed failure information instead of passing arbitrary exception strings:

```text
FailureInfo
  category: routing | validation | sql | tool | model | evidence | rendering
  retryable: true | false
  node: string
  message: safe user-facing summary
  diagnostic: internal technical detail
  attempt: integer
```

This makes fallback behavior, telemetry, tests, and UI messaging consistent.

Detailed reference: `architecture/multi_agent_robustness_addendum.md`.

## 3. Context Engine

The Context Engine should be a governed context assembly layer, not a growing
conversation transcript pasted into every prompt.

Proposed runtime flow:

```text
Context Collector
    -> Context Retriever
    -> Context Re-ranker
    -> Context Compressor
    -> Context Injection
```

The existing context-filling logic should remain responsible for immediate
routing and filter inheritance during the first migration. The Context Engine
prepares the broader, bounded evidence package consumed by that logic.

### Layer 1: Context Collector

Normalize repo-native sources into typed `ContextItem` records:

- Current query and recent conversation turns.
- LangGraph checkpoint state.
- Structured routing context and inherited filters.
- User semantic profile.
- Episodic questions, feedback, and successful SQL repairs.
- Database schemas, definitions, and valid values.
- Relevant skills and analytical lenses.
- Current-turn SQL results and analytical evidence.
- Knowledge Graph entities, relationships, and metric definitions when added.

Each item should carry source, content, type, scope, timestamp, confidence,
sensitivity, authority, and provenance metadata.

Collection means making context discoverable. It does not mean injecting all
collected content into the model.

### Layer 2: Context Retriever

Expose source-specific retrievers through one interface:

```python
retrieve(request: ContextRequest) -> list[ContextItem]
```

Retrieval should:

- Apply user, conversation, workflow, route, and data-family filters first.
- Use structured and lexical matching before expensive semantic retrieval.
- Retrieve a wider candidate set than will ultimately be injected.
- Degrade gracefully when an optional source is unavailable.
- Prevent context leakage between Chat, Boardroom, and Pitch Builder.
- Keep interfaces ready for embeddings, document connectors, or graph
  traversal without requiring those systems in the first release.

### Layer 3: Context Re-ranker

Apply hybrid ranking in this order:

1. Deterministic eligibility, confidentiality, and workflow filtering.
2. Weighted scoring for query overlap, route compatibility, entity matches,
   recency, source authority, prior feedback, and evidence confidence.
3. Deduplication and diversity limits so one source cannot consume the budget.
4. Optional model reranking only when deterministic scores remain ambiguous.

Critical system rules, explicit current-turn facts, exact entity matches, and
executed evidence should rank above old conversational summaries. Negatively
rated or unsupported context should be penalized.

### Layer 4: Context Compressor

Compress only after ranking:

- Preserve numbers, dates, identifiers, SQL provenance, filters, qualifiers,
  and confidentiality labels.
- Use extractive selection for schemas, skills, valid values, and tabular data.
- Use summarization only for long conversational or episodic material.
- Group content into typed sections instead of one opaque summary.
- Enforce per-source and total token budgets.
- Keep a source reference for every compressed fragment.
- Fall back to bounded extractive content if model compression fails.

### Layer 5: Context Injection

Build a typed `ContextBundle` with audience-specific views:

```python
bundle.for_routing()
bundle.for_rephrasing()
bundle.for_planner()
bundle.for_sql()
bundle.for_response()
bundle.for_boardroom()
bundle.for_pitch()
```

Each node should receive only the context needed for its responsibility.
Retrieved content must be delimited and treated as untrusted data, never as
executable instructions.

### Context Bundle

```text
ContextPacket
  workflow_profile
  user_intent
  routing_context
  inherited_filters
  registry_slice
  selected_skills
  evidence_refs
  recent_failures
  output_contract
  token_budget
  evidence_budget
```

### Integration Sequence

Initial Chat graph:

```text
START
  -> context_engine
  -> context_filler
  -> clarification
  -> rephraser
  -> router
```

Recommended rollout:

1. Add contracts, policies, source adapters, and deterministic processing.
2. Run in shadow mode and compare with current context and routing behavior.
3. Enable routing and rephrasing views with legacy fallback.
4. Expand to planners, SQL agents, and response writers.
5. Evaluate Boardroom and Pitch Builder as separate consumers with different
   source policies and budgets.

### Context Assembly Order

1. Base role and workflow profile.
2. Route and domain glossary from the flow registry.
3. Selected `skill.md` rules.
4. Node-specific input and output contract.
5. Validation and error policy.
6. Bounded runtime inputs and evidence references.

### Context Hygiene

- Compress old tool outputs.
- Keep schema slices rather than the entire database schema.
- Keep selected skill rules rather than all domain rules.
- Retain the latest SQL error and attempted repair only while repairing.
- Drop duplicated rows once they have an evidence id and summary.
- Never silently inherit filters across unrelated workflows or threads.
- Log context selection metadata without logging confidential row payloads.

Related references:

- `architecture/flow_registry_design.md`
- `architecture/agent_workflow_refactor.md`
- `middleware/langchain_middleware_plan.md`

## 4. `skill.md` Architecture

Skills should hold focused, reusable domain guidance. They should not become
unbounded replacement prompts.

### What Belongs In Skills

- Metric definitions and aliases.
- Trigger and negative-trigger phrases.
- Required evidence.
- Expected plan and SQL shape.
- Response rules and terminology.
- Confidentiality constraints.
- Examples and test queries.
- Dependencies and conflicts.

### What Belongs In Code

- SQL read-only enforcement.
- Allowed table and column checks.
- State and output-schema validation.
- Retry and call limits.
- Chart-axis normalization.
- Evidence-id creation.
- Feature-profile enforcement.

### Loader Improvements

- Support `negative_triggers`.
- Resolve `requires` dependencies.
- Detect `conflicts_with`.
- Deduplicate cross-flow skills.
- Validate required frontmatter in CI.
- Emit diagnostics for matched, loaded, skipped, and conflicting skills.
- Generate coverage by flow, scope, metric, and risk level.
- Keep dependency-free frontmatter parsing as a runtime fallback.

### Prompt-Layer Rule

Avoid combining incompatible instructions such as "facts only" and
"consulting insight" in one shared prompt. Assign each node one clear
responsibility and output contract, then load only the skills needed for it.

### Referencing Other Files

The live loader currently reads bodies from top-level `core/skills/*.md`. It
does not recursively discover skill folders or resolve supporting references.
The shadow catalog under `codex changes/skills/**/*.skill.md` is not a runtime
source.

Add optional reference metadata:

```yaml
---
name: gpr-share-of-wallet
flow: gpr
scope: [planner, sql, response]
triggers: [share of wallet, sow]
references:
  planner:
    - references/gpr/share_of_wallet_definition.md
  sql:
    - references/gpr/share_of_wallet_sql.md
  response:
    - references/gpr/share_of_wallet_response.md
examples:
  - examples/gpr/share_of_wallet.yaml
evaluation_cases:
  - tests/evals/gpr_share_of_wallet.yaml
reference_policy: on_demand
max_reference_tokens: 1200
---
```

Recommended behavior:

1. Discover canonical skills recursively from one configured root.
2. Resolve paths relative to the skill file, never the process working
   directory.
3. Reject paths that escape the approved skill/reference roots.
4. Load only references for the active node scope.
5. Allow section anchors such as
   `references/gpr/metrics.md#share-of-wallet`.
6. Parse Markdown by heading and YAML/JSON through structured parsers.
7. Cache content by resolved path, modification time, and selected section.
8. Detect missing, cyclic, duplicated, and oversized references in CI.
9. Include loaded reference paths and token counts in diagnostics.
10. Never let a referenced file silently override deterministic safety rules.

References should provide progressive disclosure:

- The skill body stays short and explains when the skill applies.
- Definitions, long examples, SQL patterns, and edge cases live separately.
- The loader selects only the node-specific sections required for the query.
- Evaluation fixtures are linked for validation but never injected into
  production prompts.

### Reduce Skill Context

- Maintain one canonical catalog instead of live and shadow duplicates.
- Remove prose already enforced by schemas or deterministic validators.
- Keep a compact always-on base contract.
- Trigger metric and chart-type guidance only when relevant.
- Load dependencies only when the selected skill actually requires them.
- Store large few-shot examples outside the skill body.
- Add `max_body_tokens`, `max_reference_tokens`, and `risk_level`.
- Fail CI for unreachable skills, broken references, conflicting selected
  skills, or oversized always-on payloads.
- Emit a prompt contribution report by skill and reference.

Detailed reference: `skills/SKILL_SCHEMA.md`.

## 5. Why Planner Context Reaches 7-10k Tokens

The planner currently receives several broad payloads at once:

- Full table schemas rather than selected columns.
- All definitions rather than definitions for relevant fields.
- Full valid-value dictionaries, including large carrier and product lists.
- Year and quarter lists.
- Routing context.
- Matched skill bodies or legacy rule bundles.
- DSPy signature and framework overhead.

The problem is therefore not only long prose. Large structured catalogs are
being included by default even when the query needs a small slice.

### Planner Context Builder

Build the planner prompt from:

- Query-relevant tables and columns.
- Definitions only for selected columns and metrics.
- Exact resolved entity values instead of full valid-value catalogs.
- Applicable skill sections only.
- Compact routing and inherited-filter context.
- Explicit lookup tools for additional values when needed.

Keep complete schemas and valid values outside the prompt for deterministic
post-generation validation.

### Budget Policy

Set per-node budgets rather than one global maximum:

| Context section | Planner policy |
|---|---|
| Base contract | Fixed compact budget |
| Routing/inherited filters | Small, structured |
| Schema | Selected tables and columns only |
| Definitions | Selected metrics/dimensions only |
| Valid values | Exact matches plus small candidate list |
| Skills | Triggered sections only |
| Examples | At most one or two closest examples |
| History | Summary or relevant turns only |

Add observability for tokens contributed by signature, schema, definitions,
valid values, routing, skills, references, examples, and framework overhead.
Warn and fail harness tests when planner input exceeds the configured budget.

## 6. Knowledge Graph

The current architecture does **not** contain a domain Knowledge Graph.
`core/graph` is LangGraph workflow orchestration.

A Knowledge Graph should be introduced as a semantic control layer over the
existing SQL data access, not as a replacement for the SQL warehouse.

### Current Findings

1. Entity knowledge is fragmented across static lists, fuzzy matching,
   prompts, skills, valid values, and SQL rules.
2. Cross-source identity is fragile because Survey, GPR, and peer data use
   different carrier concepts and column names.
3. Relationship knowledge such as peer mapping is repeated as prompt prose.
4. The analyst schema identifier reconstructs table and relationship context
   on each run, approximating a temporary graph.
5. Metric semantics such as SoW, Share of Portfolio, peer average, NPS, and
   market rate are scattered across definitions, rules, skills, and lenses.
6. Existing semantic memory is user-scoped key/value memory, not semantic
   graph memory.
7. Episodic retrieval relies mainly on lexical overlap rather than entity,
   metric, or relationship similarity.
8. Evidence lineage lacks canonical entities, metric definitions, filters,
   periods, source columns, and confidence.
9. Boardroom and Pitch Builder receive separate, sometimes lossy evidence
   packages instead of a reusable claim/evidence graph.
10. The centralized MCP/data-tool layer is the best KG integration point.

### How It Helps

- Canonicalize carrier aliases across Survey, GPR, and peer data.
- Represent geography, product, business-line, cover, and industry
  hierarchies.
- Store peer relationships with country, workflow, year, source, and
  confidentiality scope.
- Give routing deterministic concept-to-flow mappings.
- Tell planners which metrics, dimensions, dependencies, and sources are
  required.
- Connect Survey perception and GPR premium semantically without pretending
  their tables directly join.
- Connect claims, KPIs, charts, opportunities, and risks to supporting query
  evidence.
- Detect stale aliases, broken mappings, conflicting definitions, and schema
  impact.

### Recommended Graph Model

Nodes:

```text
Carrier, CarrierGroup, Country, Region, ProductLine, BusinessLine,
CoverLine, Industry, Segment, Metric, Table, Column, Lens,
Query, Evidence, Claim, User
```

Edges:

```text
ALIAS_OF, MEMBER_OF, LOCATED_IN, PARENT_OF, PEER_OF,
MAPS_TO_COLUMN, DEFINED_BY, REQUIRES, DERIVED_FROM,
SUPPORTS, CONTRADICTS, MENTIONS
```

Relationships should carry provenance, confidence, effective dates, workflow
scope, source authority, and confidentiality classification.

### Implementation Areas

1. Create `core/knowledge/` with a storage-independent
   `KnowledgeRepository`.
2. Bootstrap canonical entities from valid-value configuration and database
   distinct values.
3. Replace direct fuzzy matching with graph-backed canonicalization; retain
   fuzzy matching for candidate discovery.
4. Materialize scoped peer relationships from the `Peers` data.
5. Register metric definitions and dependencies from skills and lenses.
6. Add tools such as `resolve_entity`, `get_relationships`,
   `get_metric_definition`, and `get_required_sources`.
7. Enrich routing context with canonical entity IDs.
8. Replace free-text relationship notes with typed graph relationships.
9. Expand evidence with canonical entities, metric, filters, period, SQL,
   source columns, rows, confidence, and provenance.
10. Feed the same evidence graph to Chat, Boardroom, and Pitch Builder through
    workflow-specific views.
11. Validate aliases, orphan entities, invalid peer mappings, cycles, stale
    edges, and confidentiality.
12. Observe graph hits, resolution confidence, fallbacks, and stale
    relationships.

Start with SQLite-backed graph tables rather than Neo4j. The first valuable
slice is canonical carrier aliases, typed peer relationships, and evidence
provenance. Adopt a dedicated graph database only when traversal volume or
graph operations justify it.

## 7. Chart Quality and Critic

The reported chart failures are not solved reliably by adding a general LLM
critic. The existing year normalization addresses only part of the path;
field selection, legend selection, intent classification, and alternate render
paths still need one shared deterministic quality gate.

Add a `ChartSpecCritic` between chart selection and rendering that:

- Classifies fields as time, category, identifier, filter constant, amount,
  rate, score, or count.
- Forces year-like values to categorical integer labels on either axis.
- Rejects constant, redundant, identifier-like, and filter-only legend fields.
- Limits series to one meaningful grouping dimension by default.
- Chooses line only for actual temporal progression with trend intent.
- Uses bars for category comparisons even when a year column is present.
- Rejects pie/donut for non-additive scores or excessive categories.
- Separates amounts and rates into a compatible combo chart.
- Verifies that every selected field contributes visible information.
- Records the original spec, repaired spec, confidence, and repair reasons.

Use an LLM critic only when multiple valid chart specifications remain after
deterministic scoring. The model critic must not override hard field, year,
confidentiality, or legend constraints.

Apply the same gate to deterministic, analyst, stored-chat, Boardroom, and
Pitch export chart paths so fixes do not depend on which workflow rendered the
chart.

Detailed reference: `architecture/chart_output_improvement_plan.md`.

## 8. Evaluation Harness

The harness should test the complete decision path, not only final wording.

### Test Layers

1. Unit tests
   - skill parsing and selection
   - registry lookup and alias resolution
   - SQL validation and normalization
   - chart-spec normalization
   - evidence and failure-object construction

2. Contract tests
   - node-declared inputs and outputs
   - tool response schema
   - Chat and Pitch profile feature boundaries
   - state adapters at workflow boundaries

3. Golden-query evaluations
   - expected route
   - expected loaded skills
   - expected plan shape
   - allowed tables and required columns
   - forbidden columns and confidential output
   - expected evidence shape
   - required and forbidden response terms

4. End-to-end scenario tests
   - direct deterministic lookup
   - ambiguous query with Chat HITL
   - equivalent Pitch query without HITL
   - SQL failure and successful repair
   - hybrid Survey plus GPR analysis
   - Boardroom widget eligibility from normalized evidence
   - Pitch report claim validation and DOCX handoff

5. Resilience tests
   - model timeout or rate limit
   - transient database/tool failure
   - malformed model JSON
   - empty result set
   - oversized evidence payload
   - unavailable optional dependency
   - disabled workflow feature invocation

### Harness Output

Each run should capture:

- query and scenario id
- workflow profile and graph version
- route and selected skills
- registry version
- tool/model call counts
- SQL attempts and normalized SQL
- evidence ids and row counts
- retries, fallbacks, and override reasons
- latency and token usage by node
- assertion results
- sanitized failure diagnostics

### Regression Gates

- No confidentiality regression.
- No new route mismatch on golden queries.
- No change in deterministic SQL shape without explicit fixture updates.
- Shared modules pass parity tests across Chat and Pitch.
- Profile-specific divergence tests remain intentional.
- Chart overrides and evidence omissions are visible in diagnostics.

Existing fixtures and plans:

- `tests/proposed_test_plan.md`
- `tests/golden_queries.yaml`
- `tests/chart_output_eval_cases.yaml`

## 9. Observability and Debugging

Every run should make the system's decisions inspectable.

- Log the workflow profile and graph topology version.
- Log route candidates, selected route, and confidence/reason.
- Log selected skills, trigger hits, dependencies, and skipped reasons.
- Log referenced skill files, selected sections, and token contribution.
- Log context candidates, ranking scores, compression ratio, and final
  injection by consumer.
- Log Knowledge Graph entity resolutions, relationship hits, and fallbacks.
- Log SQL validation, repair attempts, and final evidence id.
- Log chart-spec input, normalized output, and override reason.
- Log Boardroom digest eligibility and missing-field reasons.
- Log Pitch claim-to-evidence validation results.
- Provide a debug CLI or endpoint for inspecting context and skill selection.

Suggested command shape:

```powershell
python -m core.skills.inspect --flow gpr --scope sql --query "Zurich SoW by product"
```

## 10. Main Areas Of Improvement

### Highest Priority

- Central flow registry for tables, metrics, aliases, schemas, and
  confidentiality.
- One typed SQL execution and evidence contract across all workflows.
- Context Engine with bounded, observable context assembly.
- Canonical entity and metric semantics through a lightweight Knowledge Graph.
- Golden-query harness covering routing, skills, SQL, evidence, and output.
- Lossless evidence handoff into Boardroom and Pitch Builder.

### Next Priority

- Rich skill metadata, dependency resolution, and coverage checks.
- Progressive skill references and prompt contribution budgets.
- Profile-driven graph assembly with separate Chat and Pitch outer states.
- Structured failure taxonomy and retry policy.
- Deterministic chart guardrails.
- Report claim grounding and advisory validation.

### Later Improvements

- Model fallback after structured-output parity is proven.
- Context and evidence caching within a turn.
- Dataset-onboarding automation from registry metadata.
- Offline quality dashboards for route, skill, SQL, chart, and grounding scores.
- Human review queues for low-confidence or unsupported executive claims.

## 11. Recommended Delivery Sequence

1. Baseline current behavior with unit tests and golden queries.
2. Introduce the flow registry behind existing helper interfaces.
3. Standardize typed SQL, evidence, and failure contracts.
4. Add canonical carrier identity, peer relationships, and evidence provenance.
5. Build Context Engine selection and diagnostics without changing outputs.
6. Consolidate skills, add progressive references, and enforce prompt budgets.
7. Add profile-driven shared graph modules while retaining separate workflows.
8. Harden Boardroom and Pitch evidence handoffs.
9. Add middleware limits, retries, and context compression.
10. Add deterministic chart normalization and report claim validation.
11. Promote harness, quality, and cost results to CI release gates.

## 12. Definition Of Done

The architecture is meaningfully more robust when:

- A query can be traced from context selection through route, skills, SQL, and
  evidence to the final answer.
- Chat, Boardroom, and Pitch Builder reuse internals without losing their
  distinct workflow contracts.
- High-risk business and safety rules are enforced deterministically.
- Skill selection is explainable and covered by tests.
- Skill references are loaded progressively and their token cost is visible.
- Planner context stays within a measured per-node budget.
- Canonical entities and evidence relationships are shared without merging
  workflow states.
- Failures are bounded, typed, observable, and recoverable where appropriate.
- Golden-query and resilience evaluations prevent silent behavior drift.
- Adding a dataset primarily requires a registry entry, focused skills, and
  harness fixtures instead of edits scattered across the application.
