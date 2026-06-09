# ContextEngine — File-Level Implementation Plan

Companion to `CONTEXTENGINE_IMPLEMENTATION_PLAN.md` (the 12 decisions). That doc
says *what* and *why*; this doc says *which files, in what order, with what
signatures, gated by what tests*. It follows the **final ordered delivery
sequence** (steps 1–8) from the decisions doc.

Grounding done 2026-06-09 against the live tree. Notable current-state facts the
plan builds on (not assumptions — verified):

- `core/skills/loader.py` is already mature: single flat root, `requires` /
  `conflicts_with` resolution, `validate()`, trigger word-boundary regex,
  `consult`-style `applicable()`/`body()`. **It needs extension, not a rewrite.**
- Dynamic valid_values is **half-built** in `core/mcp/tools.py`:
  `get_distinct_values` (cached `SELECT DISTINCT`), `match_column_values` (fuzzy,
  generic-token stripping), `_candidate_values`, `_DISTINCT_CACHE`,
  `_SCHEMA_TABLES_BY_FLOW`. The registry formalizes the cardinality gate and
  takes ownership of the role/metadata that today is implicit.
- The two cited prompt-bloat offenders are confirmed:
  `core/agents/context_filler.py:151,168-171` JSON-dumps the **entire** schema
  into the first LLM call; `core/agents/common/planner.py:69` forwards the
  **full** `valid_values` dict.
- No `core/registry/` and no `core/context/` packages exist yet.

Convention for the tables below: **N** = new file, **M** = modify existing,
**D** = delete.

---

## Step 0 — Foundations (land before step 1) — ✅ DONE (2026-06-09)

Package skeletons + the soft size guardrail, so all new code in later steps is
born in the right place and small.

| Action | File | Notes |
|---|---|---|
| N | `core/registry/__init__.py` | Re-exports `flow_registry`, `FlowSpec`. |
| N | `core/context/__init__.py` | Re-exports `ContextEngine`, `ContextBundle`. |
| N | `tools/check_file_size.py` | CI **warn** at ~400 lines (non-blocking, exit 0). Prints offenders. |
| M | CI workflow / pre-commit config | Wire `check_file_size.py` as a warning step. |
| N | `tests/registry/__init__.py`, `tests/context/__init__.py` | Test package roots mirroring source. |

Done-when: empty packages import cleanly; size check runs and reports the known
big files (`config/valid_values_config.py` 4,655, `ui/callbacks.py` 2,274, …)
without failing the build.

---

## Step 1 — Flow registry (foundation feeding everything) — ✅ DONE (2026-06-09, parity-green)

The "central flow registry" — highest-priority item. Declarative per-dataset
metadata: column `role`, `cardinality_cap`, `definition`, `confidentiality`,
`aliases`. **Values come from the DB at runtime; semantics come from here.**

| Action | File | Notes |
|---|---|---|
| N | `core/registry/flows.yaml` | Survey + GPR + GIMMI entries. Shape per `architecture/flow_registry_design.md`: `tables`, `date_columns`, `entity_columns`, `metrics` (columns/aggregation/aliases/derived), `chart_defaults`, `confidentiality`. **Add per-column `role` + `card_cap`** (the decisions-doc addition not yet in the design draft). |
| N | `core/registry/spec.py` | `@dataclass(frozen=True) FlowSpec` + `ColumnSpec(role, card_cap, definition, confidential, aliases)`. Read-only helpers: `allowed_tables`, `schema(engine)`, `metric(name)`, `resolve_alias(term)`, `columns_by_role(role)`, `pitch_filter_columns()`, `confidentiality`. |
| N | `core/registry/loader.py` | Parse YAML → `dict[str, FlowSpec]`; `flow_registry.get(flow)`; module singleton mirroring `get_skill_loader()`. Path-escape + schema-validation guards; `validate()` for CI (every metric has columns; every entity column exists in schema). |
| M | `core/mcp/tools.py` | Re-implement `_SCHEMA_TABLES_BY_FLOW` (45-49), `get_valid_values` (194), `get_definitions` (203) **through the registry** — keep the existing function signatures and return shapes byte-identical (parity-gated). `_candidate_values`/`match_column_values` stay; they now read `card_cap`/role from the registry. |
| N | `tests/registry/test_flows.py` | Asserts loaded `allowed_tables`, `definitions`, `valid_values`, schema slices **equal today's hardcoded output** for survey/gpr/gimmi (the Phase-2 parity proof from `migration_plan.md`). |

Important: at step 1 the registry **reads** definitions/valid_values from the
existing `GetValidData` objects (the design draft's `valid_values_source` /
`definitions_source` python pointers). It does **not** yet replace them — that's
step 3. This keeps step 1 a pure, parity-tested seam insertion.

Done-when: `flow_registry.get("gpr").schema(engine)` etc. equal the legacy path;
`core/mcp/tools.py` routes through the registry; all existing tests green.

---

## Step 2 — Golden-query diff harness (skeleton) — ✅ DONE (2026-06-09)

What makes "shadow mode" real. ~15-25 golden queries across
lookup/analytical/hybrid/peer/chart. There is already a seed at
`codex changes/tests/golden_queries.yaml` to absorb.

| Action | File | Notes |
|---|---|---|
| N | `tests/golden/queries.yaml` | 15-25 cases; promote/expand `codex changes/tests/golden_queries.yaml`. Each: `id`, `query`, `expected_route`, optional history. |
| N | `tests/golden/harness.py` | Runs a query through the graph and **captures**: route, selected skills, resolved entities, per-node token count, post-critic chart spec. Returns a `GoldenTrace`. |
| N | `tests/golden/diff.py` | `diff(baseline_trace, candidate_trace)` → structured delta. Drives the shadow comparison in steps 4 & 8. |
| N | `tests/golden/test_golden.py` | Snapshot test: current behavior recorded as the baseline fixture (`tests/golden/baseline/*.json`). |
| M | `core/observability.py` | Ensure per-node token counts are queryable post-run (hook into existing `record_token_usage` / turn accumulator — see `[[token-accounting]]`). Add a trace sink the harness can read. |

Done-when: `pytest tests/golden` records a baseline and re-running diffs to zero.
This harness gates every subsequent step.

---

## Step 3 — Dynamic valid_values (deletes the 4,655-line file) — 🟡 GATE BUILT (2026-06-09); DELETION DEFERRED to a live parity run

**Done now (mechanism, behind a default-off shadow flag):**
- `core/registry/values.py` — `DistinctValueRegistry` (engine-injectable, cached
  `SELECT DISTINCT`, `refresh()`, `for_flow_column`); unit-tested on in-memory SQLite.
- `core/context/injection.py` — pure `gate_valid_values` (low-card → full;
  high-card → query-resolved matches, else small sample) + `gated_valid_values`
  wiring (registry caps + fuzzy matcher, lazy) + `gate_enabled()` reading
  `CONTEXT_ENGINE_VALID_VALUES = off|shadow|on` (default off).
- `core/agents/common/planner.py` — `forward()` gates `valid_values` by
  `user_query` when enabled; default off = byte-identical to legacy.
- `tests/context/test_injection.py` + `tests/registry/test_values.py` — green.

**Deferred (needs LLM creds + real DB + the golden harness; cannot verify in a
credential-less env):** flip the flag `on`, run the golden harness to prove zero
route/skill drift while planner tokens drop, then **delete
`config/valid_values_config.py`**, switch `valid_values()` sourcing to
`DistinctValueRegistry`, migrate definitions out of `core/data/valid_values.py`,
and drop the `from config.valid_values_config import *` star-import in
`core/data/general.py`. Deleting 4,655 lines without a live parity check would be
reckless — the gate is in place so that follow-up is now just a flag flip + run.

Cached DB-distinct registry + **cardinality gate**: low-card (≤ cap, e.g. 30)
inject in full; high-card (Carrier ~550, CLIENT_NAME) inject only fuzzy-resolved
matches + a small candidate list. Most plumbing already exists in `mcp/tools.py`.

| Action | File | Notes |
|---|---|---|
| N | `core/registry/values.py` | `DistinctValueRegistry`: `SELECT DISTINCT` per categorical column, cached like `_SCHEMA_CACHE` (`core/data/general.py:22`), `refresh()`-able. Generalizes the existing `_DISTINCT_CACHE`/`get_distinct_values`. |
| N | `core/context/injection.py` (gate only; full file in step 4) | `valid_values_for(flow, query)`: per column, read `card_cap` + `role` from registry → return full list (low-card) or `match_column_values(...)` + small candidate sample (high-card). |
| M | `core/agents/common/planner.py` | Replace `valid_values=self.valid_values` (line 69) with the **gated** subset for the query. This is the planner-bloat fix (decision 1 evidence). |
| M | `core/data/general.py` | `build_human_message` (75-214) consumes gated valid_values; drop the `from config.valid_values_config import *` star-import (line 12) once nothing reads the legacy globals. |
| M | `core/mcp/tools.py` | `get_valid_values` returns registry-backed gated values; remove dependence on the static `GetValidData.valid_values*` dicts. |
| D | `config/valid_values_config.py` | **Delete** (4,655 lines) once the parity harness is green without it. The "free win." |
| M | `core/data/valid_values.py` | Migrate **definitions** into the registry (decision 3); keep `matching_values` fuzzy resolver (already used by `match_column_values`). |
| N | `tests/registry/test_values_gate.py` | Low-card column → full list; high-card (Carrier) → resolved-matches-only + capped candidates; cache hit/refresh. |

Done-when: `config/valid_values_config.py` is deleted, the golden harness shows
**zero** routing/skill diffs, and planner/first-call token counts **drop**
(record the delta — it's the headline metric).

---

## Step 4 — ContextEngine (deterministic, planner-first shadow → cutover)

ONE engine, 5 typed layers, **zero extra model calls** in v1. Produces a typed
`ContextBundle` with per-audience views. Roll out behind a flag, planner-first.

| Action | File | Notes |
|---|---|---|
| N | `core/context/bundle.py` | `@dataclass ContextBundle` + views `for_routing()`, `for_planner()`, `for_sql()`, `for_solver()`, `for_response()`. Each returns only that audience's slice. |
| N | `core/context/collector.py` | Gathers raw candidates: schema slice, registry metadata, resolved entities, triggered skill sections. |
| N | `core/context/retriever.py` | Structured + lexical + existing fuzzy resolver. **No embeddings** — interface only, stub behind it. |
| N | `core/context/reranker.py` | Weighted deterministic scoring. **No model rerank** — interface only. |
| N | `core/context/compressor.py` | Extractive selection only. **No LLM summarization** — interface only. |
| M | `core/context/injection.py` | Final assembly into `ContextBundle` (extends the step-3 gate file). |
| N | `core/context/engine.py` | `ContextEngine.build(flow, query, routing_context) -> ContextBundle`. Wires collector→retriever→reranker→compressor→injection. |
| M | `config/llm_config.py` (or settings) | `CONTEXT_ENGINE_PLANNER` feature flag (shadow / on / off). |
| M | `core/agents/context_filler.py` | **Worst offender.** Replace the full-schema JSON dump (151, 168-171) with `bundle.for_routing()` — schema slice only. Behind flag; shadow-compare first. |
| M | `core/agents/common/planner.py` | Consume `bundle.for_planner()` (supersedes the step-3 inline gate with the typed view). |
| M | `core/graph/main.py` | Construct the engine once per turn; thread the bundle to nodes. |
| M | `core/graph/gpr_subgraph.py` / `survey_subgraph.py` | **Opportunistic refactor (decision 11):** the near-duplicate 514/546-line subgraphs get factored into shared routing/SQL/repair/evidence modules **here**, under the golden harness. → new `core/graph/shared/{routing,sql,repair,evidence}.py`. |
| N | `tests/context/test_bundle_views.py` | Each view exposes only its slice; no view leaks the full schema. |
| N | `tests/context/test_shadow_parity.py` | Engine-on vs engine-off produce identical routes/plans on the golden set. |

Done-when: planner + context_filler run on the engine behind the flag, shadow
diff is zero, then flip to cutover. Subgraph duplication factored with green
parity tests.

---

## Step 5 — Solver `for_solver` view (drop redundant full schema)

Route analyst solvers through `bundle.for_solver()`. Smaller prompts re-sent each
ReAct step. **No lens/recursion tuning** (deferred — it changes which analyses
run).

| Action | File | Notes |
|---|---|---|
| M | `core/agents/analyst/common.py` | `_solver_prompt` (~316): **drop the redundant full-schema dump**; keep only the `schema_slice` the schema-identifier already produced. Inject resolved entity values + triggered skill **sections** (not full bodies). Keep on-demand `consult_skill`. |
| M | `core/graph/analyst_subgraph.py` | Pass `bundle.for_solver()` to each per-lens solver fan-out instead of the full context blob. |
| M | `core/agents/analyst/generic_solver.py`, `peer_solver.py` | Accept the solver view. |
| N | `tests/context/test_solver_view.py` | Solver prompt no longer contains full schema; still contains the grounded slice + resolved entities. |

Done-when: solver prompts shrink (record per-step token delta across a multi-lens
golden query); analyst answers unchanged on the golden set.

This is also the **opportunistic split point** for `analyst/common.py` (428) per
decision 11.

---

## Step 6 — Skill loader migration (folder catalog, all 36, section-anchors)

Make the folder-per-flow catalog canonical; port all 36 live skills with richer
frontmatter; extend the (already strong) loader. References start as in-body
section anchors; external reference files split out only for SoW / peer-average.

| Action | File | Notes |
|---|---|---|
| M | `core/skills/loader.py` | Add: **recursive discovery** from one configured root (replace `skills_dir.glob("*.md")` at 169 with `rglob("**/*.skill.md")`); cache key = resolved path + mtime + section; section-anchor resolution (`refs/foo.md#heading`); path-escape guards; scope-filtered loading. `requires`/`conflicts_with` already done. |
| N | `core/skills/catalog/<flow>/*.skill.md` | New runtime root. Migrate the live `core/skills/*.md` (36 flat files) + the ~15 shadow `codex changes/skills/**/*.skill.md` → **all 36 ported** with `kind`, `requires`, `tables`, `columns`, `examples`, `test_queries`. |
| N | `core/skills/catalog/<flow>/refs/*.md` | External reference bodies for the few large skills (SoW, peer-average) only. |
| M | `core/skills/loader.py` config | Point `skills_dir` at the new catalog root. |
| N | `core/skills/inspect.py` | The `python -m core.skills.inspect --flow gpr --scope sql --query "..."` debug CLI from `migration_plan.md` Phase 4. |
| M | existing skill-consuming nodes | No signature change (loader API stable); they just see the richer catalog. |
| N | `tests/skills/test_catalog_migration.py` | All 36 present; `validate()` clean; section anchors resolve; no path escapes; snapshot of loaded skills per flow/scope matches pre-migration set. |

Done-when: folder catalog is the runtime root, `validate()` is clean in CI, the
loaded-skills snapshot is unchanged for every flow/scope, and the inspect CLI
works.

---

## Step 7 — UI modularization tickets (verified in preview)

**Separate, explicitly-scoped tickets** — never folded into feature commits
(the golden harness is backend-only and can't catch a UI regression). Each is
verified in the running app/preview.

| Ticket | File (size today) | Target |
|---|---|---|
| UI-1 | `ui/callbacks.py` (2,274) | Split by concern (chat / boardroom / pitch / chart callbacks). |
| UI-2 | `ui/components/chatbot.py` (1,618) | Extract message rendering / streaming / input subcomponents. |
| UI-3 | `ui/boardroom/editor.py` (727) | Split schema-driven widget editors (`LIST_SPECS`/`KIND_EDITORS`) — see `[[boardroom-editor]]`. |

Each ticket: define seams → move code → **verify in preview** (screenshots /
interaction) → land. No behavior change. Do **not** start before step 6; do not
bundle with backend steps.

---

## Step 8 — Chart critic (registry-fed, render choke point) — LAST

Deterministic `ChartSpecCritic` as a pre-render gate inside the single
`generate_chart` path. Ships last because it's only as good as the registry's
role coverage (steps 1/3/6 must be in).

| Action | File | Notes |
|---|---|---|
| N | `core/charts/critic.py` | `ChartSpecCritic.review(spec, flow, intent) -> (repaired_spec, reasons)`. Classifies every field by **registry role** (not substring hints): temporal→categorical labels; rate vs amount on separate axes/combo; identifier/filter-constant/redundant-legend fields rejected; type from (intent + roles + cardinality); series capped. |
| M | `ui/chart_functions.py` (745) | Insert critic as a **pre-render gate** in `generate_chart`; it now precedes the existing render-time guard (`_normalize_axes_and_type`, `_sanitize_spec`, `_RATE_HINTS`, 36-58). All paths (deterministic, analyst, stored, Boardroom, Pitch export) already render through here → all benefit. |
| N | `core/charts/llm_tiebreak.py` | LLM critic runs **only** when >1 valid spec remains. Interface + thin call. |
| M | registry `chart_defaults` | `measure_priority`/`dimension_priority` already drafted in `flows.yaml`; critic reads them. |
| N | `tests/charts/test_critic.py` | Drives `codex changes/tests/chart_output_eval_cases.yaml`: wrong-type, junk-field, ugly-but-correct cases → asserts repair. Records original→repaired + reasons. |
| M | `tests/golden/harness.py` | Capture post-critic chart spec (already a field) and diff. |

Done-when: the three observed failure modes (wrong chart type, wrong/junk
fields, ugly-but-correct) are caught on the eval set; chart specs in the golden
harness are stable; LLM tiebreak fires only on genuine ties.

---

## Out of scope (interface seams only — build nothing now)

Per decision 12: Boardroom/Pitch as separate ContextEngine consumers; Knowledge
Graph; typed `FailureInfo` taxonomy; USD/route-level cost budgets; embeddings /
model-rerank / LLM-compression inside the engine. Leave the interfaces from
steps 4 & 8 stubbed; do not implement.

---

## Cross-cutting guardrails (every step)

1. **Golden harness gates each merge** (steps 2-8). No backend step lands with a
   non-zero unexplained diff.
2. **Parity before cutover**: registry (step 1) and dynamic values (step 3) ship
   behind byte-identical output proofs; ContextEngine (step 4) ships shadow-first.
3. **Soft size guardrail** warns at ~400 lines; new files born single-purpose.
4. **Token deltas are recorded** at steps 3, 4, 5 — the cheaper/faster goal is
   the acceptance metric, not a side effect.
5. **UI verified in preview** (step 7) — never trust the backend harness for UI.

## File scorecard (from the decisions doc, with disposition by step)

| Lines | File | Step |
|---:|---|---|
| 4,655 | `config/valid_values_config.py` | **Deleted — step 3** |
| 2,274 | `ui/callbacks.py` | UI-1, step 7 |
| 1,618 | `ui/components/chatbot.py` | UI-2, step 7 |
| 996 | `core/pitch/workflow.py` | Opportunistic (when touched) |
| 745 | `ui/chart_functions.py` | Step 8 |
| 727 | `ui/boardroom/editor.py` | UI-3, step 7 |
| 546 | `core/graph/survey_subgraph.py` | Factored — step 4 |
| 514 | `core/graph/gpr_subgraph.py` | Factored — step 4 |
| 438 | `core/skills/loader.py` | Extended — step 6 |
| 428 | `core/agents/analyst/common.py` | Split — step 5 |
