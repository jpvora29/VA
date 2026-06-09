# ContextEngine + Charts + Modularization — Implementation Plan

Decision record from a design/grill session on 2026-06-09. This is the agreed
plan for the next phase of Virtual Analyst. It refines the direction in
`ROBUSTNESS_CONTEXT_SKILLS_HARNESS_POINTERS.md` into concrete, sequenced
decisions, each tied to an evidence point in the current codebase.

The driving goals: a real centralized ContextEngine, less context passed per
node, faster/cheaper complex queries, dynamic (non-static) valid_values for easy
data onboarding, fixed chart quality, and modular code that is readable and
debuggable.

---

## The 12 decisions

### 1. ContextEngine topology — central assembler, shadow rollout
Build ONE ContextEngine (the 5 layers) that produces a typed `ContextBundle`
with per-audience views (`for_routing()`, `for_planner()`, `for_sql()`,
`for_solver()`, `for_response()`, ...). Roll out node-by-node **behind a flag,
planner-first** (the worst offender), comparing against current behavior before
cutover. The existing context-filling logic stays responsible for immediate
routing/filter inheritance during migration.

Evidence: `core/agents/context_filler.py:151,168` dumps the **entire** DB schema
into the first LLM call; `core/agents/common/planner.py:67` passes the **full**
`valid_values` dict to the planner.

### 2. Dynamic valid_values — DB-distinct registry + cardinality gate
Replace the static config with a **cached distinct-value registry** built from
`SELECT DISTINCT` per categorical column, mirroring the existing schema cache
(`core/data/general.py:31`) and refreshable. **Cardinality gate:** low-card
columns (<= cap, e.g. 30) inject in full; high-card columns (Carrier ~550,
CLIENT_NAME) inject ONLY fuzzy-resolved matches + a small candidate list.
Onboarding new data = zero code edits to value lists.

Evidence: `config/valid_values_config.py` is a 4,655-line hardcoded file; the
fuzzy resolver (`core/data/valid_values.py` `matching_values`) already exists and
runs in the SQL-agent path but the planner still gets the full dict.

### 3. Column metadata — declarative flow registry (per dataset)
One declarative registry per dataset describes each column: `role`
(entity / measure / temporal / continuous / filter), `cardinality_cap`,
`definition`, `confidentiality`, `aliases`. **Values** come from the DB at
runtime; **semantics** come from the registry. This is the doc's "central flow
registry" (highest-priority item) and the shared foundation feeding dynamic
valid_values, the ContextEngine collector, AND the chart critic. Definitions
migrate here out of `core/data/valid_values.py`.

```yaml
GPR:
  Carrier_Group: {role: entity,  card_cap: 8, confidential: false,
                  definition: "parent holding group ..."}
  Premium:       {role: measure, continuous: true}
  Year:          {role: temporal}
```

### 4. Layer depth in v1 — all-deterministic, interfaces for the rest
All 5 layers exist as typed interfaces, but v1 adds **zero** extra model calls:
- Retriever = structured + lexical + existing fuzzy resolver (no embeddings)
- Re-ranker = weighted deterministic scoring (no model rerank)
- Compressor = extractive selection only (no LLM summarization)

Embeddings, model-rerank, and LLM-compression are stubbed behind the interface
for later. This removes context **without adding latency** — critical, since a
naive engine with semantic retrieval + model compression would make complex
queries slower, the opposite of the goal.

### 5. Complex (analyst) path — context view only
Route the analyst solvers through `bundle.for_solver()`:
- **Drop the redundant full-schema dump** (`core/agents/analyst/common.py:316`)
  — keep only the resolved `schema_slice` the schema-identifier already produced.
- Inject resolved entity values + triggered skill **sections** (not full bodies).
- Keep the on-demand `consult_skill` catalog.

Same lenses, same loop — just smaller prompts re-sent each ReAct step. Lens-count
and recursion-budget tuning are deferred to a measured, harness-gated follow-up
(they change which analyses run and risk accuracy).

Evidence: `_solver_prompt` carries grounded slice AND full schema, full domain
rules, and the catalog — re-sent every loop step across multiple solvers
(`core/graph/analyst_subgraph.py` fans out per-lens).

### 6. Skills — full progressive-reference loader
Adopt the folder-per-flow catalog as the canonical runtime root; **port all 36
live skills** in with the richer frontmatter (`kind`, `requires`, `tables`,
`columns`, `examples`, `test_queries`). The loader gains: recursive discovery
from one configured root, `requires`/`conflicts_with` resolution, scope-filtered
loading, caching by resolved path+mtime+section, path-escape guards, and CI
checks. **References start as in-body section anchors** (`refs/foo.md#heading`
style works on existing bodies); external reference files are split out only for
the few large skills (SoW, peer-average).

Evidence: live catalog `core/skills/*.md` (36 flat files, 14-83 lines each);
shadow catalog `codex changes/skills/**/*.skill.md` (15 files, folder-based,
richer frontmatter, **no reference files yet**, not runtime).

### 7. Catalog migration — adopt folder catalog, port all 36, anchors first
Make the folder catalog canonical; migrate the missing ~21 skills; implement the
full loader per decision 6. (Sub-decision of 6, recorded separately because it is
real migration + authoring work, not just a loader change.)

### 8. Charts — registry-fed critic at the render choke point
Build a deterministic `ChartSpecCritic` as a pre-render gate inside the single
`generate_chart` path. Classify every field via the **flow-registry role** (not
substring hints): temporal -> categorical labels; rate vs. amount kept on
separate axes / combo; identifier / filter-constant / redundant legend fields
rejected; type chosen from (intent + field roles + cardinality); series capped.
Record original -> repaired spec + repair reasons. An LLM critic runs ONLY as a
tiebreak when >1 valid spec remains. All paths (deterministic, analyst, stored,
Boardroom, Pitch export) already render through `generate_chart`, so all benefit.

Observed failure modes (user): **wrong chart type**, **wrong/junk fields
plotted**, **ugly-but-correct** — all selection-quality problems that render-time
normalization can't fully recover.

Evidence: `ui/chart_functions.py:36-58` already has a render-time guard
(`_normalize_axes_and_type`, `_sanitize_spec`, `_RATE_HINTS`, trend terms); the
gap is upstream field/type/legend selection and the lack of registry-driven role
typing.

### 9. Verification — minimal golden-query set + diff harness
Author ~15-25 golden queries spanning lookup / analytical / hybrid / peer / chart
cases. For each, capture: route, selected skills, resolved entities, per-node
token count, and the post-critic chart spec. Run current-vs-ContextEngine and
diff. This is what makes "shadow mode" real and guards routing/skill/chart
behavior. Scoped to golden queries — NOT the full §8 5-layer harness.

### 10. Charts sequenced LAST (confirmed)
Despite charts being the most visible complaint, they ship last: the critic is
only as good as the registry's role coverage, so a half-built registry would mean
chart rework. Accepted trade-off: chart pain persists through the context/skills
build.

### 11. Modularization — conventions up front + opportunistic + UI tickets
- **Up front:** define the target package layout and a **soft size guardrail**
  (CI *warns* at ~400 lines, non-blocking). All new code is born small and
  single-responsibility: `core/context/{collector,retriever,reranker,compressor,
  injection}.py`, `core/registry/`, the new loader.
- **Backend, opportunistic:** split modules you already edit, behind the golden
  harness. The near-duplicate `core/graph/survey_subgraph.py` (546) /
  `gpr_subgraph.py` (514) get factored into shared routing/SQL/repair/evidence
  graph modules during the planner-shadow work. `analyst/common.py` (428),
  `core/pitch/workflow.py` (996) qualify when touched.
- **UI, separate tickets:** `ui/callbacks.py` (2,274), `ui/components/chatbot.py`
  (1,618), `ui/boardroom/editor.py` (727) become explicitly-scoped refactor
  tickets **verified in the running app/preview** — never folded silently into
  feature commits, because the golden harness is backend-only and can't catch a
  UI regression.
- **Free win:** `config/valid_values_config.py` (4,655 lines, the single biggest
  file) is deleted by the dynamic registry (decision 2).

### 12. Out of scope (deferred — interface seams left, nothing built now)
Boardroom/Pitch as separate ContextEngine consumers; the Knowledge Graph (§6);
the typed `FailureInfo` taxonomy (§2); USD / route-level cost budgets (§3);
embeddings / model-rerank / LLM-compression inside the ContextEngine.

---

## Final ordered delivery sequence

1. **Flow registry** (+ soft size guardrail / package conventions)
2. **Golden-query diff harness** skeleton
3. **Dynamic valid_values** (DB-distinct + cardinality gate) → deletes
   `valid_values_config.py`
4. **ContextEngine** (deterministic, planner-first **shadow** → cutover);
   refactor subgraph duplication here
5. **Solver `for_solver` view** (drop redundant full schema)
6. **Skill loader migration** (folder catalog, all 36, section-anchors)
7. **UI modularization tickets** (callbacks / chatbot / editor) — verified in
   preview
8. **Chart critic** (registry-fed, render choke point) — LAST

---

## Largest files today (modularization reference)

| Lines | File | Disposition |
|---:|---|---|
| 4,655 | `config/valid_values_config.py` | Deleted by dynamic registry (#2) |
| 2,274 | `ui/callbacks.py` | UI refactor ticket (#11) |
| 1,618 | `ui/components/chatbot.py` | UI refactor ticket (#11) |
| 996 | `core/pitch/workflow.py` | Opportunistic backend split |
| 745 | `ui/chart_functions.py` | Touched by chart critic (#8) |
| 727 | `ui/boardroom/editor.py` | UI refactor ticket (#11) |
| 546 | `core/graph/survey_subgraph.py` | Factor shared graph modules (#4/#11) |
| 514 | `core/graph/gpr_subgraph.py` | Factor shared graph modules (#4/#11) |
| 438 | `core/skills/loader.py` | Rewritten by loader migration (#6/#7) |
| 428 | `core/agents/analyst/common.py` | Opportunistic backend split |
