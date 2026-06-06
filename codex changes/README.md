# Codex Changes

This folder is a shadow implementation package. It is intentionally not imported,
executed, or wired into the current Virtual Analyst runtime.

Purpose:

- Capture architecture improvements without touching existing code.
- Provide richer proposed `skill.md` files for future migration.
- Draft Pitch Builder fixes as copy-ready reference material.
- Define tests and rollout steps before changing production behavior.

Runtime guarantee:

- No files in `core/`, `ui/`, `document_builder/`, `config/`, or existing tests
  are modified by this package.
- The app should behave exactly as it did before this folder was added.

Suggested reading order:

1. `architecture/flow_registry_design.md`
2. `skills/SKILL_SCHEMA.md`
3. `architecture/agent_workflow_refactor.md`
4. `architecture/multi_agent_robustness_addendum.md`
5. `pitch_builder/pitch_builder_shadow_patches.md`
6. `middleware/langchain_middleware_plan.md`
7. `tests/proposed_test_plan.md`
8. `migration_plan.md`
