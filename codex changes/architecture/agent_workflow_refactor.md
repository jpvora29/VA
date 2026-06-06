# Agent Workflow Refactor

## Goal

Keep the current LangGraph, DSPy, and LangChain architecture, but reduce drift
between chat, analyst, and Pitch Builder workflows.

## Shared Question Graph Factory

Create a profile-driven factory that builds question-answering graphs from
shared modules and workflow-specific feature flags:

```python
build_question_graph(
    state_schema,
    include_hitl: bool,
    include_followups: bool,
    include_charts: bool,
    terminal_node: str,
    checkpointer,
)
```

Chat would call it with HITL and follow-ups enabled. Pitch Builder would call it
with HITL disabled by default, follow-ups disabled, and report-safe output.

Important: this does not mean merging Chat and Pitch Builder into one identical
state. Keep separate outer states so charts, HITL, streaming, follow-ups, and
report-only fields can evolve independently.

## State Boundaries

Replace one broad state surface with smaller typed objects:

- `TurnInput`: user message, user id, thread id.
- `RoutingDecision`: flow, inherited filters, depth, ambiguity.
- `SQLPlan`: flow, tables, filters, metrics, grouping, notes.
- `SQLEvidence`: SQL, rows, columns, row count, warnings.
- `AnswerArtifact`: markdown answer, evidence ids, charts.
- `PitchEvidence`: question, answer, extracted metrics, supporting rows.

The LangGraph state can still carry these objects, but each node should read and
write a narrow subset. Chat and Pitch Builder should share these inner artifacts,
not necessarily the same outer state schema.

## MCP Tool Contract

Make the MCP/tool layer the only execution path for data access:

- deterministic SQL nodes call `execute_sql()`
- analyst tools call `execute_sql()`
- Pitch Builder question graph calls `execute_sql()`
- tests and future external clients call the same contract

The contract should return typed data with:

- `ok`
- `rows`
- `columns`
- `row_count`
- `overflow`
- `warnings`
- `validation_error`
- `normalized_sql`
- `evidence_id`

## Middleware Placement

Use LangChain middleware only around the LangChain analyst agents. Use registry
and deterministic validation around all paths.

Recommended insertion points:

- Before model call: inject compact registry slice, relevant skills, and evidence budget.
- Around tool call: validate flow, normalize SQL, retry transient failures, compress rows.
- After model call: validate answer references only executed evidence.

## Drift Reduction

Rules of thumb:

- One flow registry entry per data family.
- One skill loader for all prompts.
- One SQL execution contract.
- One chart spec normalizer.
- One evidence object shape.
- Separate orchestration policies for chat and pitch, but shared nodes wherever
  behavior is meant to match.
