# Conversational Analyst, Data Explorer, and Business Boardroom Plan

## Purpose

This note consolidates the proposed evolution of Virtual Analyst from an
analytics chatbot into an insurance analyst workspace for leaders.

The desired experience is:

> Leaders should feel that they are working with an experienced insurance
> analyst who understands the conversation, performs the appropriate analysis,
> follows presentation instructions precisely, exposes underlying data when
> requested, and converts findings into decisions and accountable actions.

This is an architecture and product plan. It is not connected to the current
runtime.

## 1. Current Architectural Fit

The current architecture can support this direction without a rewrite.

Architectural fit for the proposed capabilities: **8.5/10**.

Useful foundations already exist:

- Typed `RoutingContext`.
- LangGraph workflow routing and persistent checkpoints.
- Separate Chat and Pitch Builder state and workflow boundaries.
- Read-only SQL validation and pre-execution `EXPLAIN`.
- Flow registry, entity resolution, and valid-value grounding.
- Analytical lenses and an analyst evidence-gathering path.
- Structured chart directives.
- Conversation persistence and episodic memory.
- Chart generation, Boardroom documents, and PowerPoint export.
- Typed Boardroom widgets with provenance and revision history.

The recommended evolution is:

```text
User message
  -> Conversation Intent
  -> Response Contract
  -> Capability Router
       -> Conversational command
       -> Data lookup
       -> Insurance diagnosis
       -> Pivot / filtered extract
       -> Boardroom briefing
  -> Evidence
  -> Response Composer
  -> Surface-specific renderer
```

Do not build one large super-agent. Use one orchestrator with bounded,
typed capabilities that share evidence and response contracts.

## 2. Product Surface Boundaries

Preserve four distinct product surfaces:

1. **Chat**
   - Conversational questions, follow-ups, explanations, and concise analysis.
   - Should feel like speaking with an insurance analyst.

2. **Data Explorer**
   - Pivots, cross-tabs, filtered datasets, previews, and downloads.
   - Deterministic data operations with conversational modification.

3. **Boardroom**
   - Leadership operating review.
   - Performance, drivers, decisions, risks, actions, ownership, and progress.

4. **Pitch Builder**
   - Prepared narrative deliverables and longer-form presentation artifacts.

Shared capabilities may support all four surfaces, but their outer workflow
state, response policy, and presentation behavior should remain distinct.

## 3. Why Chat Can Still Feel Like a Chatbot

The main issue is not merely tone or model personality. The system currently
treats most messages as data questions and then applies a relatively fixed
response structure.

Important limitations:

- Presentation instructions mainly distinguish charts as `auto`, `none`, or
  `required`; they do not express `chart_only`.
- The deeper analyst writer expects headings, recommendations, and a supporting
  table even when the user wants a short answer.
- Follow-up suggestions are generated after most successful answers.
- Conversation history is persisted, but there is no dedicated command path for
  requests such as "summarize our discussion."
- Diagnostic questions such as "why did premium decline?" depend on broad lens
  selection rather than a complete driver-decomposition contract.

The solution is to model the user's requested action and response format before
analytical routing.

## 4. Conversation Intent

Add a typed conversation intent that distinguishes the action being requested.

Suggested intents:

- `lookup`
- `compare`
- `diagnose`
- `explain`
- `summarize_chat`
- `recall_previous`
- `reformat_previous`
- `brainstorm`
- `recommend`
- `pivot_data`
- `filtered_dataset`
- `data_preview`
- `download_dataset`
- `group_and_aggregate`
- `cross_tab`
- `top_bottom_analysis`
- `prepare_boardroom`
- `prepare_pitch`

Conversational and transcript commands should be handled before Survey, GPR, or
GIMMI analytical routing when they do not require a new database query.

Examples:

| User request | Intended behavior |
|---|---|
| "Summarize our discussion" | Summarize decisions, findings, open questions, and actions from the transcript |
| "Explain that simply" | Reuse prior evidence and restate it without rerunning the analysis |
| "Give me just the visual" | Render only the chart |
| "What do you think?" | Give a concise, evidence-backed analyst judgment |
| "Prepare this for leadership" | Convert the current evidence into Boardroom output |
| "What should we investigate next?" | Identify evidence gaps and propose the next analytical cuts |

## 5. Response Contract

Expand the current chart directive into a complete per-turn response contract.

Suggested fields:

```python
class ResponseContract:
    task: str
    presentation: str
    depth: str
    tone: str
    chart_count: int | None
    include_commentary: bool
    include_table: bool
    include_recommendations: bool
    include_followups: bool
    include_sources: bool
```

Recommended values:

- `presentation`: `prose`, `chart_only`, `table_only`, `pivot`,
  `dataset_preview`, `executive_brief`
- `depth`: `direct`, `analyst`, `comprehensive`
- `tone`: `neutral`, `insurance_analyst`, `boardroom`

The contract must control downstream execution and rendering, rather than being
treated only as prompt text.

### Response Depths

1. **Direct**
   - One clear answer in one or two sentences.

2. **Visual**
   - Chart only.
   - No prose, recommendations, tables, or follow-up chips.

3. **Analyst**
   - Finding, drivers, implication, and recommended action.

4. **Executive**
   - Headline, evidence, business impact, risks, decision, and actions.

Human analysts vary their response based on the request. The system should not
force every answer into the same headings, table, recommendations, and follow-up
questions.

## 6. Insurance Analyst Behavior

An analyst experience comes from analytical method and judgment, not from
repeatedly saying "as an insurance analyst."

Create explicit playbooks for common leadership questions.

### Premium Decline Diagnostic

For "Why did premium decline?", evaluate:

1. Overall period-over-period movement.
2. Product and business-line contribution.
3. Country and regional contribution.
4. Client segment and industry mix.
5. Lost, reduced, retained, and new accounts when the data supports it.
6. Rate versus exposure or volume effects when those fields exist.
7. Carrier movement versus market movement.
8. Share-of-wallet, appetite, and rank changes.
9. Concentration effects and material anomalies.
10. Data limitations and confidence.
11. Recommended commercial actions.

The response should distinguish:

- Market contraction.
- Carrier-specific share loss.
- Mix shift.
- Concentrated account loss.
- Product appetite changes.
- Data or timing effects.

Example style:

> Premium declined 8%, but the movement was not broad-based. Property in Canada
> contributed roughly two-thirds of the reduction, while Cyber continued to
> grow. The more concerning signal is that the carrier declined while the
> market expanded, indicating share loss rather than market contraction.

### Additional Playbooks

- Growth diagnosis.
- Share-of-wallet movement.
- Rank change.
- Broker-perception deterioration.
- Premium and perception misalignment.
- Product whitespace.
- Geographic opportunity.
- Peer-performance gap.
- Portfolio concentration.
- Renewal and retention risk.

Each playbook should define required evidence, calculations, fallback behavior,
confidence, and allowed conclusions.

## 7. Conversation Memory and Transcript Commands

Add a transcript-aware conversation service that can answer:

- Summarize this conversation.
- What conclusions have we reached?
- What did you recommend earlier?
- Show the analyses we ran for this carrier.
- What decisions were made?
- What remains unanswered?
- Convert this discussion into actions.

The service should use the persisted conversation transcript, not only the
small recent-user-message slice used for routing inheritance.

Recommended transcript summary structure:

```text
Objective
Key findings
Decisions
Recommendations
Open questions
Agreed actions
Referenced analyses and data views
```

Persist compact structured conversation memory alongside the raw transcript:

- Current subject and scope.
- Active filters.
- Important findings.
- Decisions.
- Action items.
- Data views created.
- Evidence references.

## 8. Pivot, Cross-Tab, and Data Extraction Capability

Add a dedicated Data Exploration and Extraction capability. Pivoting and
exporting should use deterministic SQL and dataframe operations, not prose
generation.

### Example Requests

| Request | Expected output |
|---|---|
| "Pivot premium by country and product, with years as columns" | Interactive pivot table |
| "Give me all Zurich Canada data for 2025" | Preview plus downloadable CSV/XLSX |
| "Show average score by carrier and practice" | Aggregated table |
| "Give me the underlying data for this chart" | Exact chart-source dataset |
| "Create a pivot with country in rows and product in columns" | Deterministic cross-tab |
| "Only include premium above $1M" | Filtered dataset |

### Typed Pivot Contract

```python
class PivotRequest:
    dataset: str
    filters: list[Filter]
    rows: list[str]
    columns: list[str]
    values: list[Measure]
    aggregation: str
    sort: list[Sort]
    limit: int | None
    include_totals: bool
    output: str
```

Supported aggregations should include:

- Sum.
- Average.
- Count.
- Distinct count.
- Minimum.
- Maximum.
- Percentage of total.

### Execution Flow

```text
User request
  -> detect pivot / extract intent
  -> resolve fields and filter values
  -> validate permissions and confidentiality
  -> compile read-only SQL
  -> validate and EXPLAIN
  -> execute SQL
  -> apply deterministic pivot / dataframe operation
  -> render preview
  -> provide CSV or XLSX download
```

The LLM should only:

- Interpret the requested dimensions, measures, and filters.
- Resolve ambiguous business language.
- Produce the typed operation.
- Explain the result when commentary is requested.

It should not receive or manipulate an entire large dataset.

### Output Policy

For "give me the data":

- Display the first 50-100 rows.
- State the total row count.
- State active filters and data period.
- Provide CSV/XLSX download.
- Avoid commentary unless requested.

For "give me a pivot":

- Render an interactive table.
- Support sorting, filtering, totals, and subtotals.
- Freeze row headers.
- Preserve currency, percentage, rank, and score formatting.
- Allow download of the full pivot.

For large extracts:

- Do not render all records in chat.
- Return row count, schema, preview, and downloadable file.
- Apply configurable extraction limits.
- Clearly disclose sampling or aggregation.

## 9. Conversational Data View State

Persist a typed `DataViewState` so the user can naturally modify an existing
pivot or extraction.

Suggested fields:

```python
class DataViewState:
    source_flow: str
    source_query: str
    filters: list[Filter]
    rows: list[str]
    columns: list[str]
    measures: list[Measure]
    aggregation: str
    sort: list[Sort]
    output_format: str
    row_count: int
    artifact_reference: str
```

Example conversation:

```text
User: Pivot premium by country and product.
Analyst: Displays the pivot.

User: Make years the columns.
Analyst: Modifies the active pivot.

User: Only Zurich and AIG.
Analyst: Applies the filter.

User: Download that as Excel.
Analyst: Exports the current DataViewState.
```

This supports references such as "that pivot", "same filters", "add 2024", and
"show the underlying rows."

## 10. Data and Export Guardrails

- Continue enforcing read-only SQL and pre-execution validation.
- Validate requested fields against the flow registry.
- Enforce peer confidentiality before display and export.
- Prevent unrestricted extraction of sensitive client-level records.
- Require explicit authorization for sensitive granular data.
- Record source SQL, filters, metric definitions, and row count.
- Never invent missing records or measures.
- Apply export-size and runtime limits.
- Redact or aggregate restricted fields.
- Make sampling and truncation explicit.

## 11. Current Boardroom Assessment

The current Boardroom is a strong executive analytics dashboard, but only a
moderate business decision system.

| Dimension | Score | Assessment |
|---|---:|---|
| Visual quality | 8.2/10 | Polished glass styling, responsive widgets, editing, layout controls, and PPT export |
| Analytical presentation | 7.6/10 | Strong KPI, insight, commentary, comparison, opportunity, timeline, positioning, and battlecard components |
| Business orientation | 6.3/10 | Findings are presented well, but targets, decisions, owners, and progress are weak |
| Decision usefulness | 5.8/10 | Action tracking exists manually but is not generated as part of the analytical workflow |
| Overall | 7.0/10 | Strong analysis digest; not yet a complete leadership operating review |

### Current Strengths

- Editable, multi-page Boardroom document.
- Governed grid rather than unrestricted pixel placement.
- Generated data snapshot, reset behavior, and revision history.
- Source-inspection UI.
- Chart, KPI, commentary, insight, comparison, opportunity, timeline,
  positioning, and battlecard widgets.
- PowerPoint export.
- Staged widget generation and deterministic widget eligibility signals.

### Main Business Gaps

1. The Boardroom reports findings but does not explicitly frame the decision.
2. KPI cards lack target, plan, prior period, benchmark, variance, outlook, and
   freshness.
3. Actions and owners are available only as manually added widgets.
4. Page organization follows content type rather than leadership workflow.
5. Opportunity and positioning scores can appear more precise than their
   methodology supports.
6. Source evidence shows generated widget payloads rather than full analytical
   lineage.
7. Slider navigation is less scannable than named business tabs.

## 12. Business-Oriented Boardroom Structure

Replace the default content-type sequence:

```text
Summary -> Visuals -> Opportunities -> Battlecards
```

with a leadership operating-review sequence:

```text
Executive Brief -> Performance -> Drivers -> Decisions -> Actions & Risks
```

### Page 1: Executive Brief

- What happened?
- Why does it matter?
- What decision is required?
- Three to five performance KPIs.
- One recommended action.
- Data period and confidence.

### Page 2: Performance vs Plan

- Actual versus target.
- Variance versus prior period.
- Peer or market benchmark.
- Forecast or directional outlook.
- Red/amber/green status with explanation.
- Material trend charts.

### Page 3: Business Drivers

- Product contribution.
- Geographic contribution.
- Segment and industry contribution.
- Growth and decline decomposition.
- Share movement versus market.
- Evidence-backed explanation.

### Page 4: Decisions and Opportunities

- Recommended decision.
- Alternatives considered.
- Opportunity size or estimated value.
- Feasibility and confidence.
- Strategic rationale.

### Page 5: Actions and Risks

- Action.
- Owner.
- Due date.
- Expected impact.
- Status.
- Next review date.
- Risk likelihood, impact, mitigation, and owner.

## 13. Boardroom Schema Enhancements

Add generated business objects rather than relying on manually created generic
tables.

### Performance KPI

```python
class PerformanceKPI:
    metric: str
    actual: str
    target: str
    variance_to_target: str
    prior_period: str
    variance_to_prior: str
    benchmark: str
    outlook: str
    status: str
    period: str
    source_ref: str
```

### Decision Card

```python
class DecisionCard:
    decision_required: str
    recommendation: str
    rationale: list[str]
    alternatives: list[str]
    expected_impact: str
    confidence: str
    decision_owner: str
    decision_due: str
```

### Action Item

```python
class ActionItem:
    action: str
    rationale: str
    owner: str
    due_date: str
    expected_impact: str
    status: str
    next_review_date: str
    source_ref: str
```

### Driver Contribution

```python
class DriverContribution:
    driver: str
    dimension: str
    contribution_value: str
    contribution_percent: str
    direction: str
    explanation: str
    confidence: str
```

### Business Risk

```python
class BusinessRisk:
    risk: str
    likelihood: str
    impact: str
    exposure: str
    mitigation: str
    owner: str
    review_date: str
```

### Data Confidence

```python
class DataConfidence:
    level: str
    coverage: str
    freshness: str
    limitations: list[str]
    source_refs: list[str]
```

## 14. Boardroom Evidence and Scoring

Boardroom should distinguish three kinds of values:

1. **Observed**
   - Directly present in SQL results.

2. **Calculated**
   - Deterministically computed from observed values.

3. **Judgment**
   - Analyst interpretation based on evidence.

Every material widget should retain:

- Source query or evidence reference.
- Filters.
- Metric definition.
- Calculation method.
- Data period.
- Row count or coverage.
- Confidence.

Avoid showing normalized 0-100 opportunity, gap, or positioning values unless:

- The calculation is deterministic.
- The formula is documented.
- The denominator and comparison set are known.
- The UI clearly labels it as an index.

Otherwise prefer transparent business measures such as:

- Premium gap.
- Share-of-wallet gap.
- Peer difference.
- Growth difference.
- Addressable premium.
- Number of markets or products affected.

## 15. Boardroom Navigation and Interaction

Replace the page slider with named tabs:

- Executive Brief.
- Performance.
- Drivers.
- Decisions.
- Actions & Risks.

Recommended interaction changes:

- Keep editing and PPT export.
- Add "View methodology" alongside "View source."
- Allow leaders to mark decisions as approved, deferred, or rejected.
- Allow action owners and due dates to be assigned.
- Preserve decision and action status across conversations.
- Show last updated time and data period in the header.
- Display a compact confidence/data-quality badge.
- Add a one-click "Refresh with latest data" action when appropriate.

## 16. Recommended Implementation Areas

### Routing and Contracts

- Expand `core/schemas/routing.py`.
- Extend deterministic directive detection.
- Add conversation intent and response contract schemas.

### Conversational Capabilities

- Add a transcript command handler before data routing.
- Add prior-evidence reuse and response reformatting.
- Suppress unnecessary analytical execution for meta-requests.

### Insurance Analysis

- Add diagnostic playbooks under the existing analytical lens system.
- Define required evidence and deterministic calculations.
- Preserve the current solver and insight-writer separation.

### Data Explorer

- Add typed pivot and extraction schemas.
- Add a deterministic pivot/dataframe service.
- Persist `DataViewState` separately from broad chat state.
- Add preview, CSV, and XLSX rendering.

### Response Composition

- Replace the single rigid output template with response composers for:
  - Direct answer.
  - Chart only.
  - Table only.
  - Analyst diagnosis.
  - Executive brief.
  - Conversation summary.

### Boardroom

- Extend `core/schemas/boardroom.py`.
- Generate decision and action artifacts in `core/agents/boardroom.py`.
- Update `ui/boardroom/builder.py` to use leadership-oriented pages.
- Add business widgets to `ui/boardroom/catalog.py`.
- Add methodology and lineage views.
- Preserve editable documents, provenance snapshots, and PPT export.

## 17. Recommended Delivery Order

### Phase 1: Response Precision

1. Expand the response contract.
2. Implement `chart_only`, `table_only`, and follow-up suppression.
3. Add dynamic direct/analyst/executive composers.
4. Add conversational intent classification.

### Phase 2: Conversation Intelligence

1. Add transcript summarization.
2. Add prior-evidence reuse.
3. Add structured conversation findings, decisions, and actions.
4. Add regression tests for follow-up and topic-switch behavior.

### Phase 3: Insurance Diagnostic Playbooks

1. Premium decline.
2. Growth and share loss.
3. Perception deterioration.
4. Premium/perception misalignment.
5. Opportunity and whitespace.

### Phase 4: Data Explorer

1. Typed pivot requests.
2. Deterministic dataframe operations.
3. Interactive preview.
4. CSV/XLSX export.
5. Persistent `DataViewState`.
6. Conversational pivot modification.

### Phase 5: Business Boardroom

1. Generate performance-versus-plan KPIs.
2. Add decisions and action items.
3. Add driver-contribution objects.
4. Add transparent confidence and lineage.
5. Replace content pages with leadership workflow pages.
6. Add named tabs and operating-review interactions.

## 18. Evaluation Requirements

Add golden conversational cases covering:

- "Just give me the chart."
- "No commentary."
- "Explain that simply."
- "Summarize our conversation."
- "What did you recommend earlier?"
- "Why did premium decline?"
- "Show the underlying data."
- "Pivot premium by country and product."
- "Make year the columns."
- "Download that as Excel."
- "Prepare this for leadership."

Evaluation dimensions:

- Intent accuracy.
- Filter inheritance accuracy.
- Response-contract compliance.
- SQL correctness.
- Diagnostic completeness.
- Evidence grounding.
- Confidentiality.
- Token usage.
- Number of unnecessary model calls.
- Boardroom decision usefulness.

For Boardroom, explicitly test whether every generated recommendation has:

- Supporting evidence.
- Business impact.
- Confidence.
- Decision or action owner when known.
- No invented target, opportunity value, or normalized score.

## 19. Main Risks

1. Expanding `AgentState` into a catch-all object.
2. Adding more responsibilities to `ui/callbacks.py`.
3. Building a large conversational super-agent.
4. Letting an LLM perform dataframe calculations.
5. Re-running SQL when the user only asks to reformat prior evidence.
6. Confusing Chat, Boardroom, Data Explorer, and Pitch Builder behavior.
7. Presenting model-generated scores as measured business facts.
8. Creating action items without evidence, owner confirmation, or status.

Mitigation:

- Use narrow typed artifacts.
- Keep capability handlers modular.
- Persist data-view state separately.
- Use deterministic calculations.
- Preserve evidence provenance.
- Add surface-specific renderers.
- Validate behavior with golden conversational traces.

## 20. Desired End State

The finished experience should support conversations such as:

```text
Leader:
Why did Zurich premium decline in Canada?

Analyst:
Premium declined 8%, concentrated in Property and the large-corporate segment.
The market grew during the same period, so this is primarily share loss rather
than market contraction. Two accounts explain most of the reduction.

Leader:
Just show me the visual.

Analyst:
[Driver contribution chart only]

Leader:
Give me the underlying data as a pivot, product in rows and year in columns.

Analyst:
[Interactive pivot]

Leader:
Only include Property and Cyber. Download that as Excel.

Analyst:
[Updated pivot and XLSX download]

Leader:
Summarize what we have concluded and prepare it for the boardroom.

Analyst:
[Conversation summary]
[Executive Brief -> Performance -> Drivers -> Decisions -> Actions & Risks]
```

The defining operating chain should be:

```text
Question
  -> Evidence
  -> Finding
  -> Driver
  -> Business implication
  -> Decision
  -> Owner and action
```

That chain, combined with precise response control and deterministic data
operations, is what will make Virtual Analyst feel like an actual insurance
analyst rather than an AI chatbot.

## 21. Project-Wide Feature Maturity Assessment

The current product is broader than its main chat interface suggests. It already
contains:

- Governed GPR, Survey, and GIMMI analytical flows.
- A deeper multi-lens analyst path.
- Clarification and filter inheritance.
- Custom conversation-scoped peer sets.
- Saved conversations and persistent graph state.
- User feedback and episodic memory.
- Personalized starter questions.
- Editable Boardroom documents and PowerPoint export.
- Pitch Builder and Word report generation.
- A persistent Decision Board with revision history.
- MCP-compatible analytical tools and resources.
- Structured observability and token accounting.

Overall feature maturity: **6.8/10**.

The primary limitation is no longer a lack of features. It is that mature
capabilities exist as partially disconnected product islands rather than one
continuous governed workflow.

### Feature Scorecard

| Feature area | Score | Current state | Main improvement |
|---|---:|---|---|
| Core analytical chat | 7.3/10 | Strong routed data questions and grounded answers | Add conversational intent and flexible response contracts |
| Follow-ups and clarification | 7.0/10 | HITL clarification and generated follow-up chips exist | Make clarification shorter and follow-ups contract-controlled |
| Conversation history | 6.3/10 | Conversations and graph state persist across sessions | Add transcript summaries, search, tags, and evidence reuse |
| Insurance analyst reasoning | 7.0/10 | Dynamic analytical lenses and an insight writer exist | Add deterministic diagnostic playbooks and completeness checks |
| GPR analytics | 7.7/10 | Strong premium, share, peer, ranking, and timeframe rules | Add retention, account movement, and contribution analytics |
| Survey analytics | 7.3/10 | Score, NPS, peer aggregation, and structured interpretation exist | Add sample confidence, response coverage, and significance controls |
| GIMMI analytics | 6.2/10 | Market composite-rate lookup is supported | Add trend diagnosis and tighter GPR/Survey integration |
| Hybrid premium/perception | 7.0/10 | Combined routing and cross-lens analysis exist | Improve evidence reconciliation and unified metric framing |
| Custom peer sets | 7.5/10 | Conversation-pinned peers and mismatch clarification exist | Add reusable named peer groups, approvals, and expiry rules |
| Charts | 7.6/10 | Deterministic normalization, chart skills, critic, and table switching exist | Add chart-only output, drill-down, and business annotations |
| Tables and downloads | 5.8/10 | Result tables and some Excel download capability exist | Build governed pivots, extracts, saved views, and richer XLSX |
| Context Engine | 6.5/10 | Collector, retriever, bundle views, and feature gates exist | Run shadow validation, prove parity, then enable progressively |
| Skills and analytical rules | 7.4/10 | Structured recursive skill catalog is wired into runtime | Add more business playbooks and rule-level outcome evaluation |
| Boardroom | 7.0/10 | Editable multi-page dashboard and PPT export are strong | Add targets, decisions, owners, actions, and operating-review structure |
| Pitch Builder | 6.6/10 | Filtered questions, evidence extraction, narrative arc, and DOCX exist | Add themes, editable outline, previews, versions, and partial regeneration |
| Decision Board | 6.5/10 | Persistent Kanban decisions and audit revisions exist | Connect automatically to chat, Boardroom, evidence, and actions |
| Memory and personalization | 5.8/10 | Questions, feedback, SQL fixes, and profile facts persist | Remember user role, markets, carriers, formats, and communication style |
| Feedback learning | 5.5/10 | Thumbs feedback and disliked-answer starter guidance exist | Capture reasons and feed them into evaluation and prompt/rule repair |
| MCP and integrations | 6.2/10 | In-process MCP tools/resources and stdio server exist | Add secure deployment, authentication, and reusable artifact APIs |
| Authentication and permissions | 3.5/10 | Username-only user separation exists | Add enterprise identity, RBAC, and data entitlements |
| Administration | 3.0/10 | Configuration is file/environment based | Add user, metric, registry, model, usage, and audit administration |
| Collaboration | 3.2/10 | Decisions and documents are user-scoped | Add sharing, comments, assignments, approvals, and notifications |
| Observability | 7.0/10 | Per-agent tokens and structured events exist | Add latency, cost, quality, failure, and adoption dashboards |
| Evaluation harness | 6.0/10 | Golden harness and focused unit tests now exist | Replace failed baselines with successful release-gating traces |
| Deployment readiness | 4.5/10 | Suitable for an internal prototype | Move beyond SQLite and in-process daemon jobs |
| Documentation | 3.5/10 | Architecture notes are detailed but main README is minimal | Add setup, user, architecture, security, and operations documentation |

## 22. End-to-End Product Lifecycle

The highest-value product improvement is to connect the existing features into
one lifecycle:

```text
Question
  -> Governed analysis
  -> Saved analytical artifact
  -> Boardroom briefing
  -> Approved decision
  -> Assigned actions
  -> Progress review
  -> Refreshed evidence
```

### Analytical Artifact

Introduce a durable shared artifact between Chat, Data Explorer, Boardroom,
Pitch Builder, and the Decision Board.

```python
class AnalysisArtifact:
    id: str
    title: str
    source_surface: str
    dataset: str
    question: str
    filters: dict
    dimensions: list[str]
    measures: list[str]
    metric_definitions: dict
    source_sql: list[str]
    result_snapshot: list[dict]
    chart_specs: list[dict]
    findings: list[dict]
    limitations: list[str]
    confidence: str
    created_by: str
    created_at: str
```

This artifact should support:

- Save from Chat.
- Reopen in Data Explorer.
- Add to Boardroom.
- Use as Pitch Builder evidence.
- Attach to a Decision Board record.
- Refresh against current data.
- Export with provenance.

The product should avoid copying disconnected summaries between surfaces. Each
surface should refer to the same evidence artifact and apply its own
presentation policy.

## 23. Core Analytical Chat Improvements

### Improve Request Understanding

- Add conversational intent before analytical routing.
- Distinguish new analysis from transcript commands and presentation changes.
- Detect requests to reuse current evidence.
- Add explicit `chart_only`, `table_only`, `data_only`, and `executive` modes.
- Treat directives as per-turn contracts rather than prompt suggestions.

### Improve Response Fluidity

- Suppress standard headings for simple factual answers.
- Avoid automatically adding recommendations to pure lookups.
- Suppress follow-up chips when the user requests a minimal response.
- Reuse prior findings for "explain that", "make it simpler", and "show only the
  chart."
- Let responses vary naturally between one sentence and a full analytical
  brief.

### Improve Conversational Control

- Add "stop after the answer" behavior.
- Support "go deeper", "zoom out", "compare with peers", and "show evidence."
- Allow user corrections to update the current analytical contract without
  starting a disconnected turn.
- Surface which filters were inherited and allow users to clear them.

### Improve Transparency

- Show active filters and data period unobtrusively.
- Allow users to inspect source SQL and metric definitions.
- Distinguish observed facts, calculated values, and analyst judgment.
- State confidence and material data limitations for diagnostic answers.

## 24. Clarification and Follow-Up Improvements

The current clarification workflow is a strong safety mechanism. Improve its
experience by:

- Asking only questions that materially change the result.
- Combining related ambiguity into one compact clarification card.
- Showing the likely default and why it was selected.
- Allowing "use this choice for this conversation."
- Avoiding clarification for reversible presentation choices.
- Logging clarification frequency as a product-quality metric.

Follow-up suggestions should:

- Respect `include_followups`.
- Be based on unresolved business questions, not generic route defaults.
- Offer a mix of drill-down, comparison, and action-oriented questions.
- Avoid repeating analysis already completed in the conversation.
- Allow one-click conversion into a Data Explorer view or Boardroom request.

## 25. Conversation History Improvements

Current strengths:

- User-scoped saved conversations.
- Generated titles.
- Persistent LangGraph state.
- Recent conversation list.
- Reopening restores transcript and graph memory.

Recommended additions:

- Full-text conversation search.
- Tags for carrier, country, topic, and business review.
- Pin and archive conversations.
- Conversation folders or workspaces.
- Structured conversation summary.
- Decisions and actions extracted from the conversation.
- Referenced analysis artifacts.
- Export conversation to Markdown, Word, or PDF.
- Share a read-only conversation with another authorized user.
- Retention and deletion policies.

Add a conversation overview:

```text
Objective
Scope and active filters
Key findings
Decisions
Recommendations
Open questions
Actions
Attached analyses
```

## 26. GPR Feature Improvements

Existing GPR strengths include premium analysis, Share of Wallet, Share of
Portfolio, ranking, market context, peer benchmarking, timeframes, charts, and
SQL grounding.

Recommended feature expansion:

- Renewal and retention movement.
- New, lost, increased, and decreased account decomposition.
- Client-level contribution where permissions allow.
- Rate versus exposure or volume attribution.
- Product, business-line, industry, segment, and geography contribution.
- Market growth versus carrier share movement.
- Concentration and dependency analysis.
- Rolling 12-month and seasonality views.
- Pipeline or opportunity sizing when source data permits.
- Target-versus-actual comparisons.
- Forecast and scenario analysis with assumptions clearly labelled.

Every derived metric should be registered with:

- Definition.
- Formula.
- Approved aggregation.
- Compatible dimensions.
- Required fields.
- Confidentiality level.

## 27. Survey Feature Improvements

Existing Survey strengths include score, NPS, practice, section, attribute,
segment, geography, year, and aggregated peer comparison.

Recommended expansion:

- Response count and coverage alongside every score.
- Minimum sample-size enforcement.
- Confidence intervals or significance indicators where statistically valid.
- Attribute-driver analysis.
- Score distribution, not only averages.
- Detractor/promoter composition where source fields support it.
- Response mix and year-to-year comparability warnings.
- Practice and segment contribution.
- Perception gap versus premium strength.
- Survey participation and freshness indicators.
- Text-feedback analysis if a governed text source is introduced.

Survey answers should avoid presenting small or unstable differences as strong
business conclusions.

## 28. GIMMI Feature Improvements

GIMMI currently provides market composite-rate lookup capability.

Recommended expansion:

- Quarter-over-quarter and year-over-year movements.
- Product and regional drivers.
- Rate-cycle stage classification.
- Market-rate acceleration or deceleration.
- Comparison with carrier premium growth.
- Rate-versus-broker-perception triangulation.
- Market-hardening and softening watch lists.
- Boardroom market-context widgets.
- GIMMI inclusion in Pitch Builder themes.

GIMMI should become the market-cycle context layer, not remain an isolated
lookup flow.

## 29. Hybrid Analysis Improvements

Hybrid queries should combine premium, perception, and market context without
merely placing independent answers beside each other.

Add:

- Shared entity and timeframe reconciliation.
- Cross-source evidence contracts.
- Explicit metric compatibility.
- Premium versus perception quadrants.
- Premium growth versus score movement.
- Share loss despite strong perception.
- Premium strength despite weak perception.
- Market-rate context for observed growth.
- Cross-source confidence and data-period mismatch warnings.

The final answer should identify alignment, contradiction, and business
implication across datasets.

## 30. Custom Peer Set Improvements

Current strengths:

- Conversation-scoped pinned peer sets.
- Carrier mismatch clarification.
- Confidentiality remains enforced.

Recommended additions:

- Save named peer groups.
- Define peer-group owner and purpose.
- Add effective date and expiry.
- Share approved peer groups.
- Restrict creation by role where necessary.
- Show why each carrier is included.
- Compare custom peers against the default database peer group.
- Track peer-set usage in exported evidence.
- Allow Boardroom and Pitch Builder to select a saved peer group.

## 31. Chart and Visualization Improvements

Current strengths:

- Deterministic chart normalization.
- Field mapping and chart selection skills.
- Post-generation chart critic.
- Chart/table switching.
- Boardroom chart reuse.

Recommended improvements:

- Honor chart-only output end to end.
- Add direct drill-down from a chart point.
- Add "show underlying rows."
- Add deterministic variance and contribution annotations.
- Add reference lines for targets, peer average, and prior period.
- Preserve filter and metric definitions with every chart.
- Add accessible palettes and stronger keyboard behavior.
- Add confidence and sample-size annotations for Survey charts.
- Support waterfall, variance bridge, and small-multiple layouts robustly.
- Allow chart edits to become reusable analysis artifacts.
- Test chart selection against business intent, not only schema validity.

## 32. Tables, Pivoting, and Downloads

Build a full Data Explorer rather than continuing to add isolated table
callbacks.

Capabilities:

- Drag dimensions to rows and columns.
- Select measures and aggregations.
- Totals and subtotals.
- Top-N and Bottom-N.
- Absolute and percentage variance.
- Contribution and share calculations.
- Conditional formatting.
- Sorting and filtering.
- Table-to-chart conversion.
- Drill-through to permitted records.
- CSV and XLSX export.
- Saved and shared views.
- Add a view to Boardroom.
- Ask the analyst to explain the selected view.

Excel export should preserve:

- Number formats.
- Frozen headers.
- Filters.
- Multiple sheets when useful.
- Source filters and definitions.
- Generation timestamp.
- A methodology or lineage sheet.

## 33. Context Engine Improvements

The Context Engine implementation now includes collection, value resolution,
typed audience views, extractive compression, and progressive feature gates.

Recommended next steps:

1. Repair the runtime environment and run successful golden traces.
2. Run `CONTEXT_ENGINE_PLANNER=shadow`.
3. Compare routing, entity resolution, selected skills, SQL, charts, and tokens.
4. Enable compact schema views.
5. Enable valid-value gating.
6. Enable semantic rescue only for validated conceptual columns.
7. Add route-level context budgets.
8. Log why each context item was included.

Do not turn the Context Engine into a generic vector-retrieval layer without
evidence that it improves a defined failure case.

## 34. Skill and Analytical Rule Improvements

Current strengths:

- Structured skill catalog.
- Flow, scope, trigger, dependency, and conflict metadata.
- Reference-section reuse.
- Two-phase chart skills.

Recommended additions:

- Premium decline diagnosis.
- Retention and account movement.
- Market-cycle interpretation.
- Survey confidence and sample-size rules.
- Premium/perception contradiction.
- Decision framing.
- Target-versus-actual interpretation.
- Data extraction and pivot semantics.
- Boardroom action generation.

Each skill should have:

- Positive test queries.
- Negative test queries.
- Expected dependencies.
- Expected exclusions.
- Token-size budget.
- Business outcome assertions.

## 35. Pitch Builder Improvements

Current strengths:

- Dedicated workflow and state.
- Filtered theme-led questions.
- Multi-question evidence generation.
- Structured metric extraction.
- Narrative-arc planning.
- Top KPI selection.
- DOCX report generation.

Recommended additions:

- More themes: QBR, renewal strategy, growth plan, market review, carrier
  performance, broker-perception review.
- User-created themes.
- Add, remove, reorder, and edit questions.
- Preview evidence before report generation.
- Editable outline before prose generation.
- Regenerate one section without rerunning the whole report.
- Compare report versions.
- Approve and lock sections.
- Boardroom-to-Pitch conversion.
- Use saved analytical artifacts as evidence.
- Generate both Word and PowerPoint.
- Add an evidence appendix.
- Expose unsupported claims before export.

Pitch Builder should become an evidence-controlled publishing workflow, not
only a one-shot document generator.

## 36. Decision Board Improvements

Current strengths:

- User-scoped decisions.
- Status columns.
- Priorities.
- Owners, stakeholders, decision date, and due date.
- Evidence and linked chats.
- Append-only revision history.

Recommended additions:

- Create a decision directly from Chat or Boardroom.
- Attach an immutable analysis artifact.
- Add alternatives considered.
- Add expected business impact.
- Add confidence and assumptions.
- Separate decisions from subordinate action items.
- Add approval and rejection workflows.
- Record approver and approval date.
- Add reminders and overdue status.
- Add comments and mentions.
- Track expected versus realized impact.
- Reopen the source analysis with the original filters.
- Refresh evidence and flag material changes.

The Decision Board should remain the system of record for approved decisions;
Boardroom should remain the presentation and working-review surface.

## 37. Memory and Personalization Improvements

Current memory supports:

- Recent questions.
- User feedback.
- Verified SQL corrections.
- Basic profile facts.
- Personalized starter questions.

Recommended profile facts:

- Role and business unit.
- Preferred markets and carriers.
- Preferred peer groups.
- Default response depth.
- Chart and table preference.
- Currency and formatting preference.
- Boardroom or Pitch themes.
- Approved terminology.

Memory rules:

- Store explicit preferences, not inferred sensitive facts.
- Let users inspect and delete remembered preferences.
- Separate factual business evidence from user preference memory.
- Do not learn user-edited Boardroom numbers as truth.
- Apply retention limits to old episodes.

## 38. Feedback and Quality Learning

Thumbs-up/down alone gives weak diagnostic information.

When an answer is down-voted, optionally capture:

- Wrong number.
- Wrong filters.
- Missing context.
- Poor chart.
- Too verbose.
- Too brief.
- Not business-oriented.
- Confidentiality concern.
- Other note.

Use feedback to:

- Create reproducible evaluation cases.
- Identify recurring route or skill failures.
- Improve starter questions.
- Measure quality by feature and route.
- Prioritize deterministic fixes before prompt additions.

Do not automatically fine-tune behavior from unreviewed feedback.

## 39. MCP and Integration Improvements

Current MCP capabilities expose read-only SQL, entity matching, distinct values,
schema, valid values, and definitions.

Recommended additions:

- Analysis artifact retrieval.
- Saved Data Explorer views.
- Boardroom document retrieval.
- Decision creation with explicit authorization.
- Metric catalog resources.
- Data lineage resources.
- Health and capability introspection.
- Secure external transport.
- Authentication and authorization.
- Rate limits and audit logs.

External integrations should consume the same governed contracts as internal
agents.

## 40. Authentication, Permissions, and Security

Username-only login is suitable only for a prototype.

Required enterprise controls:

- SSO through OIDC or SAML.
- Role-based access control.
- Dataset and table entitlements.
- Geography, carrier, and client-level permissions.
- Restricted export controls.
- Minimum aggregation and confidentiality rules.
- User and service-account separation.
- Session timeout.
- Audit logs.
- Central secret management.
- Encryption and retention policies.

Suggested roles:

- Viewer.
- Analyst.
- Boardroom editor.
- Decision approver.
- Data steward.
- Administrator.

Permission checks must occur at data access and export boundaries, not only in
the UI.

## 41. Administration Improvements

Add an administration surface for:

- Users and roles.
- Dataset entitlements.
- Metric definitions.
- Flow registry configuration.
- Valid-value refresh.
- Skill catalog inspection.
- Saved peer groups.
- Model deployments.
- Feature flags.
- Token and cost budgets.
- Golden evaluation results.
- Audit and export logs.
- Data freshness and health.

Business definitions and metric formulas should be stewarded through governed
configuration rather than requiring code edits for every change.

## 42. Collaboration Improvements

Recommended collaboration features:

- Share conversations.
- Share saved analytical views.
- Share Boardroom documents.
- Comments and mentions.
- Assign decisions and actions.
- Approval requests.
- Notifications for due or overdue items.
- Read-only versus editor access.
- Workspace or account-level organization.
- Activity history.

Collaboration should operate on durable artifacts and records rather than on
copied screenshots or disconnected exports.

## 43. Observability and Product Analytics

Current observability captures structured events and token usage.

Add dashboards for:

- Turn latency.
- Latency by node and route.
- Token and estimated cost by feature.
- Model retry and timeout rate.
- SQL failure and repair rate.
- Clarification rate.
- Empty-result rate.
- Chart generation and rejection rate.
- Boardroom widget fill rate.
- Pitch report success rate.
- Export usage.
- Decision conversion rate.
- User feedback by feature.
- Context Engine token reduction and behavior parity.

Create service-level objectives for:

- Response completion.
- Correct route.
- Valid SQL.
- Time to first visible progress.
- Time to final answer.
- Export success.

## 44. Evaluation and Release Gates

The golden harness is now a strong foundation, but successful live baselines are
required before it becomes a release gate.

Add evaluation suites for:

- Routing and filter inheritance.
- Entity resolution.
- SQL correctness.
- Analytical formula correctness.
- Diagnostic completeness.
- Chart selection and rendering.
- Response-contract compliance.
- Transcript commands.
- Pivot and extraction behavior.
- Boardroom decisions and actions.
- Pitch claim grounding.
- Confidentiality.
- Permission enforcement.
- Token and latency budgets.

Release checks should fail on:

- Route drift.
- Filter loss.
- Confidentiality leakage.
- Unsupported claims.
- Material token regression.
- Broken exports.
- Missing required Boardroom evidence.

## 45. Deployment and Reliability Improvements

Current SQLite storage and in-process daemon-thread jobs are appropriate for a
prototype but limit production scaling.

Recommended production evolution:

- PostgreSQL or another managed relational database.
- Durable job queue.
- Separate workers.
- Shared checkpoint storage.
- Object storage for exports and artifacts.
- Idempotent jobs.
- Job cancellation and retry policies.
- Health and readiness checks.
- Structured migrations.
- Backup and disaster recovery.
- Horizontal scaling.
- Environment validation at startup.

The application should fail fast with a clear configuration report when model,
database, or deployment settings are missing.

## 46. Documentation Improvements

The main README should document:

- Product capabilities.
- Local setup.
- Required environment variables.
- Database initialization.
- Test execution.
- Architecture overview.
- Workflow boundaries.
- Security model.
- Metric and registry ownership.
- Context Engine flags.
- MCP usage.
- Deployment guidance.
- Known limitations.

Add user documentation for:

- Asking effective questions.
- Using custom peers.
- Reading confidence and source information.
- Boardroom editing.
- Pitch Builder.
- Decision Board.
- Data Explorer and exports.

## 47. Project-Wide Priority Roadmap

### P0: Product Coherence and Trust

1. Implement conversation intent and the full response contract.
2. Establish successful golden baselines and release gates.
3. Repair and stabilize the managed runtime environment.
4. Build the analytical artifact contract.
5. Connect Chat and Boardroom to the Decision Board.
6. Begin enterprise authentication and permissions.
7. Build the Data Explorer foundation.

### P1: Analyst Depth and Business Workflow

1. Add insurance diagnostic playbooks.
2. Add transcript summarization and evidence reuse.
3. Upgrade Boardroom to decisions, actions, owners, and targets.
4. Add saved pivots, extracts, and richer Excel export.
5. Expand Pitch Builder themes and editing.
6. Add meaningful feedback reasons.
7. Enable the Context Engine after shadow validation.

### P2: Collaboration and Scale

1. Add sharing, comments, assignments, and approvals.
2. Add reminders and action tracking.
3. Build administration and stewardship tools.
4. Deploy secure external MCP and artifact APIs.
5. Add product-quality and cost dashboards.
6. Move storage and jobs to production infrastructure.

## 48. Product Success Measures

Track whether the product is becoming more useful, not merely more feature-rich.

Suggested measures:

- Percentage of questions answered without correction.
- Percentage of analytical answers with verified evidence.
- Time from question to useful answer.
- Percentage of turns requiring clarification.
- Percentage of answers reformatted without rerunning SQL.
- Data Explorer view completion rate.
- Boardroom creation and export rate.
- Chat-to-decision conversion.
- Decision-to-action conversion.
- Action completion rate.
- Reuse rate of saved analytical artifacts.
- User feedback by capability.
- Token and cost per successful business outcome.

The north-star outcome is:

> A leader can move from a business question to trusted evidence, a clear
> decision, assigned action, and measurable follow-through without leaving the
> Virtual Analyst workspace.
