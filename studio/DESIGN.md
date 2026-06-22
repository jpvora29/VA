# Studio — Deterministic Boardroom Analysis Page (Design)

> Status: design agreed via grilling session (2026-06-19). Not yet built.
> Owner: jpvora29. v1 target: thin vertical slice, GPR-only.

A **separate, form-driven analysis page** (not a chatbot) that produces leadership
artifacts (QBR, executive summary, recap) from deterministic computations. It
**reuses** the existing deterministic engine and exporters; only the page / flow /
rules / narrator layer is new and isolated.

---

## 1. Architecture

```
Form (filters + table scope: GPR / Survey / both)
   │
   ▼
Scoped function registry      ← @cut decorator catalog; ONLY user-selected cuts are scoped in
   │
   ▼
Deterministic compute         ← REUSES core/analytics primitives (+ a few new ones)
   │
   ▼
Per-session fact store        ← AnalyticsFact indexed by (entity, dimension, metric, period)
   │
   ▼
YAML rule engine              ← whitespace / YoY / rank-band / SWOT / truncation thresholds
   │
   ▼
Deterministic renderers       → tables + charts per page  (numbers placed HERE, not by the LLM)
   │
   ▼
LLM narrator (temp 0)         → SWOT / QBR / exec prose
   │
   ▼
Deterministic faithfulness verifier  → every number/entity in prose must exist in the fact store
   │
   ▼
Block-contract export         → ppt_export / document_builder  (file-template binder = future)
```

- **No per-page agents.** The "orchestrator" is a deterministic dispatcher.
- **KG deferred to v2** — the per-session fact store covers all v1 cross-references.
- **LLM = narration only.** It never produces a number, ranking, or selection.

---

## 2. Decisions locked

| Area | Decision |
|---|---|
| Engine | **Reuse + extend** `core/analytics` primitives. "Separate code" = page/rules/narrator/export layer only. |
| LLM role | **Narration only.** All numbers/tables/rankings/filtering deterministic. |
| Interaction | **Interactive explorer.** Form sets global filters; navigate page-by-page; toggle cuts live; "snapshot to deck" is a separate accumulation step. |
| "Both tables" | **Parallel Premium + Survey sections + deterministic alignment layer** (normalize carrier/country/year, practice↔product) for cross-refs (e.g. "high premium, low broker score"). No SQL join. |
| Rules | **Declarative YAML** + small rule engine. Primitives stay pure. |
| Rank band | **Symmetric ±N window** around rank R (exclude R). N tunable. |
| SWOT | **Fact-driven quadrant selectors in YAML.** LLM only phrases. |
| Truncation | **>20 rows → top-10 + bottom-10** by sort metric (premium / score) + labeled hidden-rows gap. Trigger tunable. |
| Registry | `@cut(...)` populates a module **catalog**; per-request **scoped** registry runs only selected cuts. No import-time global mutation (consistent with `core/analytics`). |
| Faithfulness | **Post-narration verifier**: extract every number/%/entity, confirm against fact store within tolerance; violation → strip sentence or one bounded regenerate. Numbers templated by renderer where possible. |
| Export | **Block-contract** now (QBR / exec-summary / recap = ordered blocks); uploaded-file templates = future binder. |
| Code location | **New top-level package `studio/`**; imports `core/analytics`, `ui/boardroom` exporters, `document_builder`. Nothing in the chatbot graph imports it. |
| v1 scope | **Thin vertical slice, GPR-only**: Form → Overall + Industry → facts → rules → tables/charts → narrator+verifier → export exec-summary. Then fan out. |

---

## 3. Cross-cutting constraint — confidentiality

`flows.yaml` sets `peer_names_allowed: false` for **both** GPR and Survey.
- Never render or export an **individual peer's name**.
- Peer comparison = **aggregate average only** (already enforced by `compute_peer_average`).
- The faithfulness verifier must also flag any individual peer name leaking into narration.

---

## 4. Package layout (`studio/`)

```
studio/
  cuts/            # @cut decorator + cut catalog (per-request scoped registry)
  rules/           # rules.yaml + deterministic rule engine
  facts/           # per-session fact store (index by entity/dimension/metric/period)
  align/           # GPR↔Survey normalization for "both" cross-refs
  narrate/         # constrained LLM narrator + faithfulness verifier
  export/          # block contract → ppt_export / document_builder adapters
  page/            # Dash view + callbacks (new `active-view` = "studio")
  skills/          # future-scope Claude-like skills (see §8)
  DESIGN.md        # this file
```

---

## 5. Primitive work needed (small; mostly reuse)

Already covered by `core/analytics/library.py`:
- top/bottom-5 = `compute_breakdown` / `compute_attribute_breakdown` + sort + truncation
- appetite (SoP) = `compute_share_of_portfolio`; SoW = `compute_share_of_wallet`
- rank = `compute_rank`; whitespace = `find_whitespace`; peer avg = `compute_peer_average`
- section scores = `compute_breakdown` grouped by Section; NPS = `compute_nps`; service gaps = `find_service_gaps`

New:
- **`compute_yoy` absolute mode** — Survey wants absolute score change, not % (current primitive is %-only). Add a `mode` param or sibling primitive.
- **SWOT composite** — pure rule layer over existing facts (no new math).
- **Alignment helper** — carrier/country/period/practice↔product normalizer for "both".

---

## 6. Rule thresholds — NEED stakeholder numbers (author into `rules.yaml`)

| Rule | Value | Default if unconfirmed |
|---|---|---|
| Rank window N | ? | 5 |
| YoY "significant" premium floor (current-year) | ? | $1,000,000 |
| Whitespace: market GWP threshold | $5,000,000 (given) | 5M |
| Whitespace: carrier premium ceiling | strictly ~0 vs small floor? | ~0 |
| Truncation trigger (rows) | ? | 20 |

YoY rule: show >100% growth only when current-year premium ≥ floor. Always show
previous-year and current-year premium side-by-side for comparison.

---

## 7. Recommended defaults for un-grilled items (confirm/correct)

- **Navigation**: left sub-nav inside the `studio` view listing analysis levels;
  Country page has a country multiselect → one SWOT panel per country.
- **Filter cascade**: reuse `GetValidData` + DB-backed dependent dropdowns
  (country → carriers), same pattern as the pitch builder.
- **Overall page**: headline KPIs (total premium, YoY, rank + Δ, survey score if
  Survey selected) + top movers.
- **Auth/shell**: same login + `app-root` shell; new `active-view` value `"studio"`.

---

## 8. Future scope — Template Analyser (Claude-like skill approach)

> Not v1. Captured now so the block-contract export (§2) is designed to plug into it.

Goal: let a user **upload a prior QBR / executive deck** and have the system (a)
reuse it as a branded template and (b) generate a **recap** slide from it. Built as
a **Claude-like skill** following the repo's existing conventions, with the LLM used
**minimally** (deterministic-first, LLM-rescue only).

### Conventions to mirror (already in the repo)
- **Deterministic script** → `skill creation reference code/skills/ppt/template_analyzer.py`:
  unzips `.pptx`, parses theme colors/fonts, slide masters, layouts + placeholder
  roles, recommends layout indices, detects light/dark. Library **and** CLI. No LLM.
- **Skill-as-source-of-truth** → `document_builder/skills/pitch_report_design.md`:
  Markdown + YAML frontmatter parsed by `design_spec.py` with hardcoded fallbacks
  so a parse miss never breaks generation.

### Proposed structure
```
studio/skills/template_analysis/
  SKILL.md                       # instructions + progressive-disclosure index
  reference/
    placeholder_taxonomy.md      # placeholder roles → block types
    block_to_placeholder_map.md  # block contract (§2) → template slots
    confidentiality.md           # peer-name / private-data rules for filled output
  scripts/
    analyze_pptx.py              # port/extend template_analyzer.py → TemplateReport
    analyze_docx.py              # docx sibling (styles, headings, tables)
    bind_blocks.py               # deterministic block→placeholder binding (fuzzy match)
    fill_template.py             # write filled .pptx/.docx via python-pptx / python-docx
```

### LLM usage (minimal, rescue-only) — mirrors `flows.yaml` fuzzy-first / semantic resolver
- **Deterministic first**: `analyze_*` scripts extract structure; `bind_blocks.py`
  maps block contract → placeholders by name/role fuzzy match (like `find_field`).
- **LLM rescue only when** deterministic placeholder binding is ambiguous
  (semantic placeholder naming the fuzzy matcher can't bridge).
- **LLM for recap narrative**: summarize the prior QBR's narrative into the recap
  block — still passed through the **faithfulness verifier** against the current
  fact store so no stale/invented numbers survive.
- Everything else (structure parse, theme, layout choice, number placement,
  fill) stays deterministic.

### Why this fits
The block contract (§2) is the seam: because export content is already decoupled
into typed blocks, "fill an uploaded template" is purely a **binder** mapping
blocks → that template's placeholders — no rework of compute/rules/narrate.

---

## 9. Build sequence (v1)

1. ✅ `studio/` skeleton + `@cut` catalog + scoped registry.
2. ✅ Fact store + `core/analytics` GPR primitives wired through it against a LIVE engine.
3. ✅ `rules.yaml` + rule engine (whitespace, YoY, truncation, rank band) with §6 thresholds.
4. ✅ Renderers + page shell (`studio/page/`) — KPI strip, panels, truncated tables, brand
   charts; CSS in `assets/studio.css`.
5. ✅ Data layer: `studio/data.py` engine resolver (`DB_PATH`/`STUDIO_DB_PATH` → seed
   fallback, LLM-free) + DB-derived filter options. `studio/compute.py` deterministic
   orchestrator (KPIs, breakdown-by-dimension, whitespace) → fact store. `studio/seed.py`
   deterministic seed DB (schema-true to flows.yaml) for dev/CI. Overall page rendered
   from REAL computed facts. ⏳ remaining: live page-switch callbacks inside the main app.
6. 🟡 Narrator — DETERMINISTIC rule-based commentary landed (`studio/narrate/commentary.py`,
   100% faithful by construction, per-page). ⏳ LLM narrator + faithfulness verifier behind
   the same contract.
7. ✅ Deck + export: **`studio/deck/`** is the shared slide contract (`DeckSpec` = ordered
   `SlideSpec`s of typed blocks) driving BOTH the on-screen **PPT-like deck**
   (`studio/page/slide.py` 16:9 slides + scroll-snap stage + filmstrip, `assets/studio_deck.*`)
   AND the **template-driven PPTX export** (`studio/export/ppt.py` → native charts/tables;
   `studio/export/template.py` `TemplateProfile`+`LayoutMap` follow a template's theme and
   grow to complex templates incrementally). Export wired to the deck "Export PPTX" button.
8. Fan out: Country/SWOT, Product, Rank, Peer; then Survey family; then "both" alignment.
   ⏳ live page-switch + filter callbacks in the main app.
9. (Future) Template Analyser skill (§8) — placeholder-fill binder builds directly on the
   `DeckSpec` block contract; KG (v2).

### The deck contract (productised as QBR)
On screen the analysis renders as a navigable slide deck and the SAME `DeckSpec` exports to an
editable `.pptx`. The deck is the QBR. Export follows a supplied template's theme today;
complex-template fidelity grows via `TemplateProfile`/`LayoutMap` with no change to
compute/rules/deck.

### Content/story layer (Phase 1) — facts never go straight to slides
> **⚠️ SUPERSEDED by §10 (2026-06-20).** The two-model chain below
> (`QBRContentSpec → DeckSpec`) is replaced by the four-contract spine
> `EvidencePack → ReportPlan → DeckSpec → RenderPlan`. The existing
> `studio/content/*` code is **evolved into** those contracts, not discarded —
> see §10 for the mapping. The prose here is kept for history.
```
Analytics facts (OverallResult)
  → QBR evidence model   studio/content/evidence.py → QBRContentSpec
  → QBR story planner    studio/content/planner.py  → DeckSpec
  → Studio UI + PPT exporter
```
- **`QBRContentSpec`** (`studio/content/model.py`): thesis, what-changed, material `Finding`s,
  `Action`s (owner/timing/impact), decisions, and explicit `DataGap`s + sources.
- **Material slide selection** from the canonical insurance-QBR agenda (exec → performance →
  premium movement & drivers → portfolio/mix → geo/industry → share & position → whitespace →
  risks → decisions → appendix). Sections the data can't support are recorded as `DataGap`s and
  shown on the **methodology/limitations** slide — never filled with generic commentary.
- **Every content slide is decision-oriented**: `question`, `action_title`, `evidence`,
  `implication`, `recommendation`, `owner`, `due_date`, `confidence`, `sources`.
- **Insurance analysis** (`studio/compute.py`): prior-year comparison, **driver decomposition**
  (`movement_by_dim`), **rank movement**, **share-of-wallet movement**, **concentration** (HHI/
  top-3), **peer aggregate** (confidential), whitespace + indicative feasibility. Gaps (no plan,
  rate–volume–mix, retention/new-business, prior-QBR actions) are surfaced, not faked.
- **SWOT is optional** (block still available); the default flow uses a **decisions slide +
  initiative tracker** instead.

**Consulting-grade slide standard** (every content slide): an **action title** (the takeaway
sentence) + accent rule at top; a **left commentary rail** ("key takeaways", deterministic) +
**right visual** (chart/table); a footer with **logo · confidential/source · page number**.
Slide types: `cover`, `exec` (stat band + what-it-means + priority actions), `insight`
(rail+visual workhorse), `swot` (4 fact-driven quadrants), `initiatives` (ENTER/SCALE/DEFEND
cards). **Report type** selector: Full QBR vs Executive Summary (cover+exec only). SWOT and
initiatives are built deterministically from the fact store (`studio/narrate/commentary.py`).

### Data + dev harness
- Live data: set `DB_PATH` (or `STUDIO_DB_PATH`) to the GPR/Survey SQLite DB. With neither
  set, `studio/seed.py` builds a deterministic seed DB so the page computes real numbers
  through the exact same primitives.
- `python -m studio.demo_app` → http://127.0.0.1:8099 renders the Overall (QBR) page
  computed end-to-end from the engine (no LLM, no login). Not shipped; the real page mounts
  in the main Dash app as a new `active-view`.
```

---

## 10. Revised content architecture (2026-06-20)

> Supersedes the §9 "Content/story layer" two-model chain. Driver: avoid five
> overlapping representations of the same information, audit the data **before**
> designing the ideal QBR, and put **content approval before any template work**.
> The existing `studio/content/*` and `studio/deck/*` code is **evolved into**
> these contracts (mapping in §10.2), not rewritten from zero.

### 10.1 Four-contract spine

```
EvidencePack   validated facts, comparisons, provenance, availability + confidence
   ↓
ReportPlan     storyline, selected claims, implications, decisions, actions
   ↓
DeckSpec       semantic slides & blocks — design-independent (THE approval artifact)
   ↓
RenderPlan     template-bound frames, geometry, concrete PPTX objects
```

- **EvidencePack** — pure data + *what the data can and cannot support*. The Phase-0
  capability probe (§10.3) writes its availability/confidence states here. No narrative.
- **ReportPlan** — the argument: audience, objective, report type, selected claims,
  decisions, actions, prior-QBR continuity. No geometry.
- **DeckSpec** — semantic slides/blocks, independent of visual design. **This is the
  single canonical artifact the human approves and edits** (§10.9); edits round-trip.
- **RenderPlan** — template selection + layout + concrete objects. **Both the on-screen
  preview and the PPTX export consume the same RenderPlan** (§10.10).

### 10.2 Mapping existing code → contracts (evolve, don't rewrite)

| New contract | Built from | Change needed |
|---|---|---|
| **EvidencePack** | `studio/compute.py` + carve the *fact/provenance/gap* parts out of `studio/content/evidence.py` | Add capability-probe output; move `DataGap` here (it's a data-availability fact, not a story choice). Numbers carry stable `fact_id`s. |
| **ReportPlan** | evolve `QBRContentSpec` (`studio/content/model.py`) + `studio/content/planner.py` | Add header fields (§10.6); `Finding` carries `Claim`s (§10.5); add prior-QBR block (§10.8). Drop `materiality: float` single-score in favour of split scoring (§10.4). |
| **DeckSpec** | keep `studio/deck/model.py` + `studio/deck/build.py` | Make it the approval/edit store with round-trip + regeneration semantics (§10.9). |
| **RenderPlan** | formalise `studio/export/template.py` (`TemplateProfile`/`LayoutMap`) | Make `studio/page/slide.py` (preview) and `studio/export/ppt.py` both render *from* RenderPlan, not from DeckSpec independently (§10.10). |

### 10.3 Phase 0 — data capability probe (programmatic, not a static table)

Runs against the **live dataset each generation** and emits availability/confidence into
EvidencePack. Per candidate section: `data_available`, `comparison_available`, `confidence`,
and a `reason` when blocked. A hand-authored matrix rots; the table is the *output*.

```
probe(dataset, agenda) -> {section_id: Capability(available, comparison, confidence, reason)}
```

Sections that probe as blocked are surfaced on the methodology/limitations slide as
`DataGap`s — never filled with generic commentary.

### 10.4 Materiality — split importance from confidence (no multiplicative score)

The single `materiality: float` (product-style) is replaced. A product of five [0,1]
factors collapses toward zero, is uninterpretable, and lets one low factor zero an
otherwise critical finding. Instead:

- **Importance** = weighted sum of `financial_materiality`, `change_severity`,
  `strategic_relevance`, `actionability` (named, tunable weights in `rules.yaml`).
  Above a threshold → main deck; below → appendix.
- **Confidence** is **orthogonal** — it gates *how* a finding is presented
  (assertive / hedged / disclosed-as-gap), **never whether** it appears. A
  high-importance / low-confidence finding is surfaced *as a data gap*, not demoted out.

### 10.5 Claim-level evidence + observation→decision separation

Every material statement is a typed `Claim` traceable to facts:

```
Claim(text=..., fact_ids=[...], confidence="high",
      claim_type="observation|driver|interpretation|recommendation|decision")
```

- The renderer pulls every **number** from EvidencePack by `fact_id`; the LLM only writes
  prose around claims (consistent with the "LLM never emits a number" rule, §2).
- **No `why` without decomposition**: a `driver`/`interpretation` claim is only allowed when
  a supporting decomposition fact exists (e.g. `movement_by_dim`). Concentration or
  correlation must **not** be phrased as causality. Recommendations may be judgment-based,
  but the facts motivating them stay traceable via `fact_ids`.

### 10.6 Report type & audience = selection policy, not separate pipelines

Full QBR / Executive Summary / Recap share EvidencePack **and** most of ReportPlan; they
differ only in **selection & compression policy**. Model as parameters that dispatch policy
tables (dictionary-dispatch), **one pipeline**. ReportPlan header fields:

`audience`, `meeting_objective`, `report_type`, `decision_horizon`, `tone`,
`confidentiality_policy`, `comparison_basis`.

The three report types differ in planning rules: **Full QBR** = full evidence/trends/drivers/
actions/appendix; **Executive Summary** = 5–7 leadership messages + decisions required +
priority actions; **Recap** = prior commitments → progress → exceptions → next steps.

### 10.7 Two-tier QA — content gate before visual gate

**Content QA (before rendering):** metrics reconcile · comparison periods valid · every claim
has evidence · no unsupported causal language · no duplicated insights · titles match visuals ·
recommendations actionable · confidential/peer-name data suppressed · critical data gaps disclosed.
(Extends the existing faithfulness verifier, §2.)

**Visual QA (after rendering):** overflow · font size · alignment · template fidelity · chart
readability · empty placeholders.

### 10.8 Prior-QBR continuity — first-class (replaces mandatory SWOT)

Recurring QBRs persist prior ReportPlans. Each carried commitment tracks: `owner`,
`due_date`, `status`, `expected_impact`, `actual_impact`, `delay_reason`,
`carry_forward_decision`. More valuable than forcing SWOT; SWOT stays optional.

### 10.9 Human approval checkpoint (before template composition)

Before any RenderPlan/template work, the UI shows the **DeckSpec**: proposed storyline,
selected slides, action titles, evidence behind each title, recommendations, and
**excluded findings + reasons**. User can reorder / remove / edit / approve. Define now:
edits round-trip into DeckSpec, and **regeneration with fresh data merges rather than
clobbers** human edits (merge policy TBD before build).

### 10.10 Template compatibility levels (deferred, but designed for)

- **Level A** — template contains reusable slide *examples* → highest fidelity.
- **Level B** — structured layouts/placeholders.
- **Level C** — theme-only.
- **Unsupported** — protected / corrupted / structurally unusable.

The §8 Template Analyser scores an uploaded file into one of these; behaviour is predictable
per level instead of overpromising universal fidelity. RenderPlan is the binder output.

### 10.11 Determinism contract

Non-determinism is allowed **only** in narration. Assert: *same EvidencePack + same
ReportPlan parameters ⇒ byte-stable DeckSpec selection and ordering*. This is what makes the
pipeline testable.

### 10.12 Revised build sequence (thin vertical slice first)

The §9 layer-by-layer order builds all contracts + materiality + claims + QA before anything
renders end-to-end. Reordered to get a demoable deck early and de-risk the contracts against a
real render:

1. Insurance-QBR quality rubric (the QA target, §10.7).
2. Phase-0 capability probe (§10.3) → EvidencePack availability/confidence.
3. **Thin vertical slice**: one `report_type` + one `audience`, minimal
   EvidencePack → DeckSpec → RenderPlan → render. (Tracer bullet, then armour.)
4. Materiality split scoring (§10.4) for selection.
5. Claims + implications + decisions + actions + prior-QBR continuity (§10.5, §10.8).
6. Evolve DeckSpec into the approval/edit store with round-trip (§10.9).
7. Content QA + faithfulness checks (§10.7).
8. Storyline review/edit UI before template work (§10.9).
9. Generic Studio UI + PPT output polish.
10. Template analysis + compatibility scoring (§10.10).
11. RenderPlan via template binding; preview + export consume one RenderPlan (§10.10).
12. Visual / template-fidelity QA.
