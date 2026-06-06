# Migration Plan

## Phase 0: Keep Shadow Package Non-Invasive

- Keep all proposed files under `codex changes/`.
- Do not import shadow skills or docs from runtime code.
- Use this folder as review and implementation reference.

## Phase 1: Test Current Behavior

- Add real tests for current `SkillLoader`.
- Snapshot current loaded skills by flow/scope.
- Add golden query fixtures for top business questions.
- Confirm whether current skills replace or augment legacy rules.

## Phase 2: Introduce Flow Registry

- Add a registry module with current Survey, GPR, and GIMMI metadata.
- Keep old helper function names but implement them through the registry.
- Add tests that prove returned schemas, definitions, valid values, and table
  slices are unchanged.

## Phase 3: Enrich Skills Without Runtime Dependency Changes

- Add richer frontmatter fields.
- Keep loader ignoring unknown fields at first.
- Add validation tests for required metadata and dependencies.
- Update skill README and coverage reports.

## Phase 4: Make Skill Loading Observable

- Log loaded skills, matched triggers, dependencies, and skipped skills.
- Add a debug endpoint or CLI command:

```powershell
python -m core.skills.inspect --flow gpr --scope sql --query "Zurich SoW by product"
```

## Phase 5: Decide Skill Fallback Policy

Choose one policy:

- Replacement: skills are primary and complete; legacy rules retire.
- Additive: compact base rules always load, and skills add focused details.

Recommended: additive during migration, replacement only after golden tests pass.

## Phase 6: Refactor Shared Graph Construction

- Create a profile-driven graph assembly layer.
- Keep chat and pitch outer states separate.
- Share only reusable graph modules and typed inner artifacts.
- Preserve chat-only features such as HITL, charts, streaming, and follow-ups.
- Preserve pitch-only features such as batch questions, report evidence, KPI
  extraction, narrative arc, and DOCX validation.
- Add parity tests proving Pitch Builder and chat answer the same direct question
  with the same route and evidence contract when HITL is disabled.

## Phase 7: Fix Pitch Builder

- Enforce filters in question prompts.
- Align KPI field names.
- Add evidence summarization.
- Fix progress callback id.
- Add advisory report claim validation.

## Phase 8: Add Middleware To Analyst Path

- Add tool and model call limits first.
- Add tool retry for transient failures.
- Add context summarization/editing.
- Add fallback model last, after structured-output tests pass.

## Phase 9: Improve Chart Selection And Rendering

- Add chart-output golden evals for line-vs-bar decisions.
- Add deterministic renderer guardrails for bad LLM chart specs.
- Force year-like x axes to categorical/integer ticks.
- Update chart skills and legacy chart prompts so `Year` alone does not imply
  `line`.
- Log chart overrides for debugging.

## Phase 10: New Dataset Onboarding

For every new data family:

1. Add registry entry.
2. Add baseline skills.
3. Add valid values and definitions.
4. Add golden queries.
5. Add Pitch Builder eligibility if needed.
6. Run coverage and confidentiality checks.
