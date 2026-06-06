# LangChain Middleware Plan

## Scope

Use middleware around the LangChain analyst `create_agent()` path first. Keep
deterministic rails protected by existing SQL validation and registry checks.

## Recommended Middleware

### Model Retry

Use for transient model/API failures.

Insertion point:

- Analyst solvers.
- Insight writer if converted to `create_agent`.
- Pitch report writer if later moved to agent middleware.

### Model Fallback

Use a fallback model for:

- temporary Azure deployment failure
- rate-limit fallback
- lower-cost draft report generation

Critical structured JSON nodes should remain on deterministic low-temperature
models unless fallback has equivalent structured-output quality.

### Tool Retry

Use for transient tool/database failures, not for invalid SQL. Invalid SQL should
continue to use the SQL fixer loop.

### Tool Call Limit

Add hard limits per solver:

- peer solver: 4 tool calls
- generic solver: 6 tool calls
- comprehensive pitch question: 8 tool calls

### Model Call Limit

Prevent runaway reasoning loops:

- lookup path: no LangChain agent loop
- analyst single sub-question: 4 model calls
- pitch comprehensive question: 6 model calls

### Context Editing / Summarization

Apply before model calls:

- compress old tool outputs
- keep schema slice
- keep selected skill rules
- keep latest SQL errors and repairs
- drop repeated full row payloads

### Custom SQL Tool Wrapper

Use `wrap_tool_call` style middleware to:

- validate flow name
- normalize SQL identifiers
- enforce row preview limits
- attach evidence ids
- cache identical SQL within one turn
- standardize error messages for the SQL fixer

## Non-Goals

- Do not use middleware as the only safety layer.
- Do not let middleware replace deterministic SQL validation.
- Do not make Pitch Builder depend on live agent middleware until report tests exist.

