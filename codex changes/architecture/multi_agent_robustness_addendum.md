# Multi-Agent Robustness Addendum

## Design Clarification

Chat and Pitch Builder should not be forced into one identical state or feature
surface.

The goal is shared reusable internals, not one merged workflow:

- Chat can have HITL, follow-up suggestions, streaming node labels, charts, and
  conversation memory.
- Pitch Builder can skip HITL, skip charts, run batch questions, preserve report
  evidence, and validate claims before DOCX generation.
- Future chat-only or pitch-only features should be easy to add without
  branching through unrelated code paths.

## Refinement To Prior Factory Proposal

Instead of one monolithic `QuestionAnsweringGraphFactory`, use a small set of
reusable graph modules plus profile-specific assembly.

```python
QuestionGraphProfile(
    name="chat",
    state_schema=ChatAgentState,
    features={
        "hitl": True,
        "followups": True,
        "charts": True,
        "streaming": True,
        "report_validation": False,
    },
)

QuestionGraphProfile(
    name="pitch",
    state_schema=PitchAgentState,
    features={
        "hitl": False,
        "followups": False,
        "charts": False,
        "streaming": False,
        "report_validation": True,
    },
)
```

Shared modules should be composed, not inherited blindly:

- context filling
- rephrasing
- routing
- deterministic Survey/GPR/GIMMI answer paths
- analyst evidence gathering
- SQL execution and repair
- evidence normalization

Profile-specific modules should stay separate:

- chat HITL clarify gate
- chat follow-up generation
- chat chart rendering/spec generation
- pitch batch question generation
- pitch insight extraction
- pitch KPI extraction
- pitch narrative arc
- pitch report claim validation
- pitch DOCX handoff

## State Architecture

Keep separate outer states:

- `ChatAgentState`
- `PitchAgentState`

But share smaller inner artifacts:

- `RoutingContext`
- `QuestionPlan`
- `SQLAttempt`
- `SQLEvidence`
- `AnswerEvidence`
- `FailureInfo`

This avoids broad duplicated state while still keeping pitch/chart/HITL fields
out of the wrong workflow.

## Code Layout Proposal

```text
core/
  graph_profiles/
    chat_profile.py
    pitch_profile.py
  graph_modules/
    routing.py
    deterministic_answer.py
    analyst_answer.py
    sql_repair.py
    evidence.py
  state/
    chat_state.py
    pitch_state.py
    artifacts.py
```

## Additional Robustness Changes Not Previously Captured

- Add profile flags so a node cannot accidentally write chart fields into pitch
  state or report fields into chat state.
- Add compile-time graph validation that checks every node's declared outputs are
  allowed for the selected profile.
- Add state adapters at workflow boundaries instead of passing the whole state
  into every reusable node.
- Add parity tests only for shared modules, not for profile-specific features.
- Add divergence tests proving chat has HITL/charts/followups while pitch does
  not.
- Add a `FeatureNotEnabledError` for accidental calls to disabled profile
  features.
- Add explicit graph topology snapshots per profile.
- Add a small profile manifest in logs for every run so debugging shows whether
  the chat or pitch graph executed.

## Acceptance Criteria

- A shared question can use the same router, SQL tools, and answer evidence in
  both chat and pitch.
- Chat-specific fields do not exist in Pitch Builder state unless deliberately
  added.
- Pitch-specific report fields do not exist in chat state unless deliberately
  added.
- Adding a new chat-only feature requires editing the chat profile, not the
  pitch profile.
- Adding a new Pitch Builder feature requires editing the pitch profile, not the
  chat profile.

