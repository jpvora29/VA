# Conversational Analyst — Architecture (Spec of Record)

> Status: agreed design, pre-implementation. This document supersedes the
> original free-form notes. It records **what we are building, why, and the
> code conventions every phase must follow**. Decisions below were resolved in
> the 2026-06-11 architecture review.

This is an **in-place refactor** of the existing `core/graph/main.py` pipeline
into a clean 4-layer model. It is *not* a greenfield rebuild — we reuse the
ContextEngine, router, analyst subgraph, skills, lenses, and flow registry that
already exist, and re-shape the front end around them.

---

## 0. Engineering conventions (apply to every phase)

These are non-negotiable for all new and touched code:

- **SOLID, single responsibility.** Each node/class does one job named after
  that job. New behavior is added by extending a list/registry (OCP), not by
  editing a branching ladder.
- **Dictionary dispatch over `if/elif`.** A `key -> handler` table is the
  default for any multi-way decision (family → columns, node → view, kind →
  validator). The repo already does this (`_FLOWS_BY_FAMILY`, `_KIND_BY_ATTR`).
- **Dependency injection.** Collaborators (resolvers, matchers, value loaders,
  clients, hook bundles) are passed in via constructor/factory params with
  sensible production defaults — never hard-constructed inside the logic. The
  repo already does this (`ContextEngine(resolver_factory=…)`, the collector's
  provider params).
- **Names read like English.** Functions are verb-first and read as a sentence
  at the call site (`resolve_entities`, `assemble_bundle`,
  `missing_mandatory_filters`, `roll_up`). Classes are role nouns
  (`MandatoryFilterGate`, `ContextInjector`, `HierarchyResolver`).
- **Shared protocols, defined once.** Where several things produce the same kind
  of output, define one protocol and iterate over implementations rather than
  growing parallel branches: `ClarifyQuestionSource`, `NodeHooks`,
  `AfterModelValidator`.

---

## 1. The four layers (and where each already lives)

```
Layer 1  Filter Extraction      context_filler + resolve_entities  (+ new mandatory gate)
Layer 2  Intent Classifier      new thin IntentClassifier node     (reuses schema_identifier downstream)
Layer 3  Router                 router  (already pure deterministic dispatch — unchanged)
Layer 4  Analyst Agent          analyst subgraph  (planner + lenses + skills — unchanged core)
```

### Layer 1 — Filter Extraction

Extracts the filters from the user query (carrier, country, timeframe, section,
optional table) and inherits missing ones from conversation history.

**Example.** *"Comprehensive analysis for Markel underwriting in Spain using
survey data — what went well, what needs attention, plus YoY?"*

| Filter | Value | Source |
|---|---|---|
| Carrier | Markel | query |
| Country | Spain | query |
| Timeframe | [2025, 2024] | data — default-timeframe function returns latest years |
| Section | Underwriting | query (additional filter beyond the mandatory set) |
| Table | *(optional)* | only if the query supplies it |

This stays in `context_filler` + `resolve_entities` (rapidfuzz contract
resolution). It runs on the **legacy path** because the ContextEngine remains in
shadow (see §4). Follow-up / down-the-line turns fill missing filters from
conversation history before any clarification.

**New: deterministic mandatory-filter gate.** HITL fires only when a **mandatory
filter is still missing** after history inheritance + fuzzy resolution + context.
The mandatory set is **Carrier + Country** — timeframe is excluded because it
always auto-defaults to the latest years.

- New `MandatoryFilterGate` (SRP: only decides which mandatory filters are
  missing): `missing_mandatory_filters(routing_context) -> list[FilterRequirement]`.
- Family→required-columns as a **dispatch dict** (family-aware on the Country
  column):
  ```python
  _MANDATORY_COLUMNS_BY_FAMILY = {
      "premium": ("Carrier_Group", "Country"),
      "survey":  ("Carrier", "SurveyCountry"),
      "both":    ("Carrier_Group", "Country", "Carrier", "SurveyCountry"),
  }
  ```
- It reads `resolved_filters` ∪ `inherited_*`, so a follow-up turn that inherits
  Carrier/Country from history does **not** re-ask.
- The gate is added as a **third clarify source**, not a replacement. The three
  sources share one `ClarifyQuestionSource` protocol and `clarify_decide`
  iterates an injected `Sequence[ClarifyQuestionSource]`, ordered:
  1. **Missing mandatory filter** (new, deterministic)
  2. **Unresolved-entity "did you mean…?"** (existing, deterministic)
  3. **LLM ambiguity classifier** (existing, fallback)

### Layer 2 — Intent Classifier

A **thin pre-router node** (`IntentClassifier`) owning **Intent** and
**Additional Intent** only — largely a relabel of today's `intent_type`,
`analysis_depth`, and output directives. The directive detectors fold over a
`_DIRECTIVE_DETECTORS` tuple.

Heavy **Table / Column identification** (`Tables: [Carrier, Peer, GPR]`,
`Cols: within a table`) is *not* promoted upstream. It stays as the existing
`schema_identifier` (`tables` like `["GPR","Peers"]`, join keys,
`values_to_resolve`), which runs **only on the analytical path, after the
router**. Cheap lookup turns stay cheap — no extra LLM call on the fast path.

### Layer 3 — Router

Unchanged. Already a pure deterministic function lifting
`routing_context.table_family` + `analysis_depth` into the dispatch the
conditional edges fire on (lookup rails vs `analyst_agent`). No LLM, no token
cost.

### Layer 4 — Analyst Agent

Takes filters + intent context and builds a plan. The planner already does
**progressive-disclosure lens selection**: the catalog shows only
`name / description / applies_when`; the full lens body is injected only for the
chosen lenses (the same pattern as `skill.md` execution). Skills load the same
way. The planner decides the additional sub-questions, required lenses, and
required skills.

**New: before/after-model hook parity** across the two runtimes.

- One `NodeHooks` protocol: `before_model(ctx)` = inject context from the
  ContextEngine; `after_model(result)` = log + validate + trace.
- **Analyst (LangChain `create_agent`)** keeps `AgentMiddleware` (already has
  `after_model` observability/token accounting/retry/summarization).
- **Rails (DSPy + LangGraph)** get an equivalent thin decorator
  `with_node_hooks(predictor, *, hooks=…)` — **same contract, two
  implementations, no rail rewrite** (DIP/OCP).
- After-model validators selected by a **dispatch dict** `{"sql": validate_sql,
  "chart": validate_chart}`; tracing for full auditing (LangSmith-style spans)
  layered on the existing `log_event`/observability.

---

## 2. Knowledge Graph

Captures deeper table relationships and **column hierarchies** — Section →
Attribute, Product Line → Business Line → Cover Line, SIC Major → SIC Minor —
for richer, more analyst-like grounding. The listed hierarchies are all
**within-flow taxonomy rollups on existing entity columns**; the registry today
declares those columns flat, with no parent/child edges.

**Representation — declarative, no new infrastructure:**

- A new `hierarchies:` block per flow in `core/registry/flows.yaml` declares the
  parent→child **column** edges.
- The actual instance **value** mappings (which cover lines roll into which
  business line) are **derived from the DB at load and cached**.
- The cross-table **join semantics** already noted ad-hoc in `schema_identifier`
  (e.g. `GPR.Carrier_Group ↔ Peers.Overall_Peer_Group`, no row-join) are
  formalized here too.
- No graph database, no networkx — the registry stays the single source of
  structural truth.

**Component:** `HierarchyResolver`, built via factory
`build_hierarchy_resolver(flow, *, value_loader=…)` (DI of the DB value source
so tests pass a stub). Methods read as sentences: `parent_of(column, value)`,
`children_of(column, value)`, `roll_up(value, to_column)`. Edge derivation is
keyed by a `column_role -> derivation_strategy` dispatch dict.

**Scope for v1: grounding first.** The KG feeds *upstream grounding only* —
filter resolution, `schema_identifier`, valid-values enrichment — and is
exposed through the ContextEngine. We prove the edges are correct before any
output consumer trusts them. **Learned / semantic edges** (carrier competition,
similarity, co-occurrence) are explicitly **out of scope** for v1.

---

## 3. Interpretation layer (commentary relationships)

A declarative, `flows.yaml`-style structure capturing **relationships between
output values** so commentary reads richer and more analyst-like than restated
numbers. Lives in a new `core/registry/interpretation.yaml`, validated against
the registry to prevent drift, read by the commentary / boardroom path.

It encodes all four relationship kinds:

1. **Dimension parent→child** value mappings — *reuses the KG's derived
   mappings* (one structure, two consumers). Lets commentary say "X, part of the
   Marine book…".
2. **Metric relationships / definitions** — how Share-of-Wallet vs
   Share-of-Portfolio vs Premium relate (leans on the registry metric specs).
3. **Carrier ↔ peer framing** — that a result is read against its
   `Overall_Peer_Group` (reuses the GPR↔Peers join).
4. **Directional / expected-sign hints** — higher SoW = good, rising composite
   rate = hardening market. This is the one **net-new editorial layer** to
   maintain.

**Component:** `InterpretationLibrary`, mirroring the existing `LensLibrary`
shape. Sentence-named lookups: `direction_of(metric)`, `relate(metric_a,
metric_b)`, `peer_framing(carrier)`.

---

## 4. ContextEngine — stays shadow, gets readable

The ContextEngine should hold data schema, column definitions, and per-column
unique values — kept **in full when distinct count ≤ the column's `card_cap`**
(default 30), and **fuzzy-resolved** down to the query's matches when above it.
Its layers — Collector, Retriever, Re-ranker, Compressor, Injector — all exist
and provide relevant context to every node.

The pipeline is well-architected (strong DI, pure functions, per-audience views)
but **hard to follow** in three specific ways. This effort fixes readability
**without behavior change**; the `CONTEXT_ENGINE_*` flags stay in **shadow**
(diff against legacy, no cutover). We only wire the injection seams so nodes
*can* consume the bundle later.

**Fix 1 — the orchestrator shows the full pipeline it advertises.** Today
`ContextEngine.build()` only does `collect → assemble_valid_values → bundle`,
while every docstring promises `collector → retriever → reranker → compressor →
injection → bundle`. Make `build()` call every stage explicitly with
sentence-named locals, so the orchestration reads top-to-bottom and the reserved
stages are visibly identity functions, not missing:

```python
raw      = self.collect_raw_context(flow, query)     # collector
resolved = self.resolve_entities(raw, query)         # retriever
ranked   = self.rank_candidates(resolved, query)     # reranker  (identity in v1)
selected = self.compress(ranked)                     # compressor (identity in v1)
gated    = self.gate_valid_values(selected, query)   # cardinality gate
return self.assemble_bundle(...)                     # bundle
```

**Fix 2 — resolve the "injector" naming collision.** `core/context/injection.py`
is really the **valid-values cardinality gate**, not a context injector. The
doc's *Context Injector* is the thing that injects the right per-audience view
into each node's prompt. Separate the two:

- Rename `injection.py → core/context/gate.py` (`gate_*` functions); update all
  importers.
- Introduce the genuinely-named `ContextInjector` whose `inject_for(node_name,
  bundle) -> view` uses a **dispatch dict** — the one place node→view mapping
  lives:
  ```python
  _VIEW_BY_NODE = {
      "router":   ContextBundle.for_routing,
      "planner":  ContextBundle.for_planner,
      "sql":      ContextBundle.for_sql,
      "solver":   ContextBundle.for_solver,
      "response": ContextBundle.for_response,
  }
  ```
  This is also the **before-model hook** Layer 4 (§1) consumes.

**Fix 3 — a one-screen pipeline legend** at the top of `engine.py`: each stage,
its input→output types, and whether it is active or a reserved seam.

---

## 5. Out of scope (this effort)

- UI ToDo / plan-checklist widget (good-to-have; defer).
- Learned / semantic KG edges (carrier competition, similarity).
- ContextEngine cutover — flags stay shadow.

---

## 6. Phasing

| Phase | Work | Depends on | Notes |
|---|---|---|---|
| **0** | ContextEngine readability — linear `build()` + legend, `injection.py`→`gate.py`, add `ContextInjector` dispatch | — | Pure clarity; creates the injector seam Phase 4 needs. Shadow. |
| **1** | Mandatory-filter HITL gate (Carrier + Country) as 3rd clarify source | — | Smallest, self-contained, high value. |
| **2** | `flows.yaml` `hierarchies:` + DB-derived mappings + KG grounding | — | Feeds resolution / `schema_identifier` / valid-values. |
| **3** | Thin `IntentClassifier` node re-layering | — | Relabel + wire before router; keep lookups cheap. |
| **4** | Hook parity — `NodeHooks` protocol, DSPy `with_node_hooks` decorator | 0 | Consumes `ContextInjector`. |
| **5** | Interpretation layer + commentary consumer | 2 | Reuses KG mappings; adds directional hints. |
