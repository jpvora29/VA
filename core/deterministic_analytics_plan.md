# Deterministic Analytics — Phased Implementation Plan

> **Status:** proposed (2026-06-16). Supersedes the ad-hoc "LLM emits the number"
> path for well-defined metrics. Aligns with the reliability roadmap (query
> contract / engine cutover) and the ContextEngine direction.

## The principle

> **The LLM never produces a number that exists in the data. It selects which
> calculation to run, labels it, and narrates it. Every number is computed by a
> deterministic primitive over rows and handed to the model.**

This single rule is the through-line of every phase. Where today a dspy field says
"intensity 0-100" or "gap_score 0-100" ([core/schemas/boardroom.py:159](schemas/boardroom.py),
[:185](schemas/boardroom.py)), the model invents a scalar. We replace invented
scalars with computed facts (premium, share-of-portfolio %, rank, YoY %).

## Why this is more reliable than LLM-SQL-from-scratch

The high-value metrics already have **exact, written definitions** — `gpr-share-of-portfolio`,
`gpr-ranking`, `gpr-sow-definition`, `gpr-peer-average`, `YoY Growth` in
[core/data/valid_values.py:124](data/valid_values.py). Asking the model to re-derive
that SQL every turn re-runs a known recipe and occasionally gets it wrong. Encoding
each recipe once, as a tested pure function, removes that entire class of variance —
and lets us attach the computed table to the UI as "supporting data" for free.

**Non-goal / explicit caveat:** we are NOT building a swarm of LLM agents
(whitespace-analyzer agent, rank-calculator agent…). A rank is `RANK() OVER (...)`,
not a reasoning task. Primitives are **functions** in a dispatch registry,
orchestrated by the existing single planner. The open-ended LLM-SQL path stays as a
fallback for questions the library does not cover.

## Expected impact (speed & reliability)

**Reliability — large, structural improvement (the main reason to do this):**

- The variance class is *removed*, not reduced — a pure function returns the same
  value every run, so invented numbers (`intensity`, `gap_score`) become impossible
  rather than merely less likely.
- Every primitive has a hand-verified golden test → "fix and lock" instead of
  "tune the prompt and hope."
- The "latest year" bug becomes structurally impossible (computed + injected, never
  chosen).

**Speed — faster and more *predictable* on the covered path; neutral on fallback:**

| Step | Today | Covered metric (new) |
|---|---|---|
| Planner | LLM call | LLM call (same) |
| SQL generation | **LLM call** | **deleted** — structured args → parametrized SQL template |
| SQL fixer retry | **0–N LLM retries** (tail latency) | **deleted** — a template can't be malformed |
| Number computation | in the LLM's head | pure Python / SQLite, ~µs |
| Repeat / boardroom re-runs | re-runs the LLM | **cacheable** — `(primitive, args)` key |

The biggest practical win is **killing the SQL-fixer retry loop** (worst-case tail
latency today) and enabling **fact caching** across widgets/turns.

**Honest caveats:**

1. The open-ended **fallback path is not faster** — novel questions still hit
   LLM-SQL. But the covered metrics are the highest-volume, highest-pain queries.
2. Boardroom still makes per-widget LLM calls for **labels** ([`_fill_widgets`](agents/boardroom.py)).
   Numbers stop being generated so each call shrinks, but it's still N calls. An
   optional **Phase 4.5** could collapse them into one labeling pass now that numbers
   are pre-computed.

Bottom line: the headline gain is **predictability** — today both p99 latency and
correctness are random; this makes both deterministic, which matters more for a
board-facing tool than raw average speed.

---

## Architecture overview

```
user query
   │
   ▼
[planner]  ── selects primitive(s) + filters (LLM: intent → recipe)
   │
   ▼
[analytics orchestrator]  ── dispatch dict: name → pure function
   │                          (NO LLM in the number path)
   │   ── tier 1: ATOMIC primitives (own ONE metric, no cross-knowledge) ──
   ├─ resolve_timeframe(...)        → "2024"
   ├─ compute_rank(...)             → AnalyticsFact(rank=3, of=18)
   ├─ compute_share_of_portfolio    → AnalyticsFact(pct=12.4)   # appetite
   ├─ compute_share_of_wallet       → AnalyticsFact(pct=...)
   ├─ compute_peer_average(...)     → AnalyticsFact(...)
   ├─ compute_market_presence(...)  → AnalyticsFact(...)        # Marsh/market premium
   ├─ compute_yoy(...)              → AnalyticsFact(pct=+8.1)
   │   ── tier 2: COMPOSITE analyzers (compose tier 1 via the registry) ──
   ├─ find_whitespace(...)          → [WhitespaceRow, ...]  (ranked, top-N)
   │      └─ calls compute_market_presence / compute_peer_average for context;
   │         OWNS only the gap rule (carrier≈0 AND others present), nothing else
   └─ (fallback) llm_sql(...)       → rows
   │
   ▼
computed facts (typed) ───► [narration / widgets]  (LLM: labels & prose only)
                                   │
                                   ▼
                            grounding eval (claims ⊆ computed facts)
```

### Core contracts (settle these first — Phase 0)

```python
# core/analytics/types.py
@dataclass(frozen=True)
class AnalyticsFact:
    """One computed scalar plus the provenance needed to ground & display it."""
    name: str                     # "share_of_portfolio", "rank", "yoy", ...
    value: float | int
    unit: str                     # "%", "USD", "rank", "count"
    rendered: str                 # business-ready label, e.g. "12.4%", "#3 of 18"
    dims: dict[str, str]          # the cut this fact is for, e.g. {"product": "Cyber", "year": "2024"}
    support: list[dict]           # the exact rows the number was computed from (→ UI)
    formula: str                  # human-readable definition used (audit/eval)

# core/analytics/types.py
@dataclass(frozen=True)
class PrimitiveArgs:
    """What to compute and over which cuts — dimension- and flow-agnostic.

    The primitive never hard-codes dimension names. `group_by` and `filters` are
    open lists/maps validated against the flow's `valid_values`, so the SAME
    `compute_rank` ranks carriers by premium across Product_Line OR by score across
    SurveyPractice — the caller supplies the columns, the primitive supplies the math.
    """
    flow: str                     # "gpr" | "survey" — selects column roles + valid_values
    metric: str                   # "premium" | "score" | "nps" | ...  (the measure column)
    group_by: list[str]           # ANY valid dim(s): product, cover_line, business_line,
                                  #   industry/SIC, segment …  OR survey: practice,
                                  #   section, attribute, segment …
    filters: dict[str, Any]       # ANY valid filter: timeframe, country, carrier, peers,
                                  #   a specific product/industry, practice/attribute …
    subject: str | None = None    # the carrier/entity in focus, when relevant
    peers: list[str] | None = None

# core/analytics/registry.py
PRIMITIVES: dict[str, AnalyticsPrimitive]   # name -> callable, DI-friendly
```

Every primitive is `Callable[[FactFrame, PrimitiveArgs], AnalyticsFact | list[AnalyticsFact]]`,
pure, and unit-tested against golden inputs. `FactFrame` is a thin normalized view
over the result rows already in state (`_collect_row_sets` in
[core/agents/boardroom.py:154](agents/boardroom.py)) — no new data layer.

**Dimension-agnostic by construction.** No primitive names a dimension internally.
`group_by` and `filters` are open and resolved against the flow's `valid_values`
([core/data/valid_values.py](data/valid_values.py)) / fuzzy matchers
([GetValidData](data/valid_values.py)) for grounding. So "rank by premium across
Cover_Line filtered to Cyber + Canada + a peer set" and "rank by score across
Attribute filtered to a Practice" are the *same* `compute_rank` call with different
args. Adding a new cut (e.g. SIC_Major_Class) needs zero primitive changes.

### Two tiers — single responsibility, composition over duplication

- **Tier 1 — atomic primitives** own exactly ONE metric and know nothing about any
  other. `compute_rank` knows ranking; `compute_share_of_portfolio` knows appetite;
  `compute_peer_average` knows peers; `compute_market_presence` knows Marsh/market
  premium. None of them reaches into another's domain.
- **Tier 2 — composite analyzers** answer a question that *needs* several metrics, by
  **calling tier-1 primitives through the registry** (dependency-injected), never by
  re-deriving their math.

> **`find_whitespace` is tier 2 and must NOT contain peer / Marsh / market / SoW /
> appetite logic.** It receives those facts from `compute_market_presence`,
> `compute_peer_average`, etc., and owns *only* the gap rule — "carrier premium ≈ 0
> while market/peer presence is material." Swapping how peer or market presence is
> computed must require zero changes to `find_whitespace`.

Composites declare their dependencies explicitly so the registry can inject them:

```python
# core/analytics/types.py
@dataclass(frozen=True)
class CompositePrimitive:
    name: str
    depends_on: tuple[str, ...]          # tier-1 names pulled from the registry
    combine: Callable[..., list[AnalyticsFact]]   # owns ONLY the composing rule
```

### One library, both flows — GPR **and** Survey

The analytical schema is already flow-agnostic ([analytical.py:1](schemas/analytical.py)
— "Both flows now share"); the primitive library follows suit. There is **one
registry**. A primitive's math is flow-agnostic; the *flow* only supplies which
columns are the measure vs dimensions, and the `valid_values` to ground filters.

| Concept | GPR (premium) | Survey (perception) |
|---|---|---|
| Measure (`metric`) | `Premium` (SUM) | `Score` (AVG, 1-9), `NPS` |
| Dimensions (`group_by`) | Product_Line, Business_Line, Cover_Line, SIC class, Client_Segment, Country, Region | SurveyPractice, Section, Attribute, SurveySegment, Region |
| Filters | timeframe, country, carrier, peers, a product/industry | timeframe, country, carrier, peers, a practice/attribute/section |
| Subject vs peers | carrier vs peer set | carrier vs peer set (peer = **average only**, never individual — [rules/survey.py:78](rules/survey.py)) |
| Aggregation rule | SUM premium | **AVG** score ([rules/survey.py:121](rules/survey.py)) |

So `compute_rank`, `compute_peer_average`, `compute_yoy` are shared — `flow` +
`metric` + `group_by` select the behavior. Where a metric is flow-specific, it
registers under a flow-scoped name but obeys the same contract:

- **GPR-only tier 1:** `compute_share_of_portfolio` (appetite), `compute_share_of_wallet`,
  `compute_market_presence` (Marsh/market premium).
- **Survey-only tier 1:** `compute_nps`, `compute_attribute_breakdown` (avg score per
  Section/Attribute).
- **Composites, one per flow's "gap" question, same structure:**
  - GPR `find_whitespace` — premium absence (carrier ≈ 0, market/peer present).
  - Survey `find_service_gaps` — perception shortfall (carrier score ≪ peer average
    on a Section/Attribute). Composes `compute_peer_average` + `compute_attribute_breakdown`;
    owns ONLY the shortfall rule. **No premium/Marsh/SoW logic.**

Every primitive that takes cuts takes them via `PrimitiveArgs.group_by` /
`.filters`, so both flows get the full arbitrary-dimension freedom above.

---

## Phase 0 — Foundations (interface-settling)

**Goal:** land the primitive contract, registry, and test harness with ONE trivial
primitive, so every later phase plugs in without re-litigating the interface.

- **New:** `core/analytics/__init__.py`, `core/analytics/types.py` (`AnalyticsFact`,
  `FactFrame`, `PrimitiveArgs`), `core/analytics/registry.py` (dispatch dict + DI
  accessor), `core/analytics/frame.py` (rows → `FactFrame`, column-role detection
  reusing the `_*_COLS` regexes already in [agents/boardroom.py](agents/boardroom.py)).
- **First primitive:** `count_distinct_periods` (used by both the timeframe phase and
  timeline gating) — proves the contract end-to-end.
- **Tests:** `tests/analytics/test_registry.py`, `tests/analytics/test_frame.py`.
  Golden-input fixtures (small row lists) live in `tests/analytics/fixtures/`.
- **Acceptance:** registry resolvable via DI; one primitive green; zero behavior
  change to the live app (nothing wired in yet).

## Phase 1 — Deterministic timeframe resolution (TRACER BULLET)

**Goal:** fix "it doesn't pick the latest year" everywhere, and prove the
"compute, don't ask" pattern on the smallest real slice.

**Root cause:** latest-year is currently an LLM judgment; the skill is only advice
the planner may ignore. `valid_year_quarter` (last element = most recent) is passed
into the planner ([analytical.py:113](schemas/analytical.py)) but not enforced.

- **New primitive:** `resolve_timeframe(frame, routing_context) -> str`. Reads
  `valid_year_quarter` (built in [core/context/bundle.py:115](context/bundle.py)) +
  `routing_context.timeframe_hint`; returns a concrete period. No LLM.
- **Wire-in:** call it in the context/bundle assembly so `routing_context.timeframe`
  carries a *resolved* value before the planner runs
  ([core/agents/common/planner.py:59](agents/common/planner.py)). The planner then
  inherits a fact instead of choosing. SQL builder defaults to it when the plan
  omits a timeframe ([agents/common/sql_agent.py](agents/common/sql_agent.py)).
- **Tests:** `tests/analytics/test_resolve_timeframe.py` (single-year, multi-year,
  relative-hint, empty); a planner/integration test asserting latest year is used
  when the query says "latest"/omits a year.
- **Acceptance:** "latest year" queries deterministically resolve; golden traces
  still parity-green ([tests/golden/](../tests/golden/)).

## Phase 2 — Core analytical primitives

**Goal:** encode the known recipes as tested functions. No app wiring yet — build
and golden-test the library so Phase 3 can dispatch to trustworthy functions.

Each ships with a docstring quoting its definition source and a golden test.

**Tier 1 — atomic (own one metric, no cross-domain knowledge):**

**Shared (both flows — `flow`+`metric`+`group_by` select behavior):**

| Primitive | Definition source | Output |
|---|---|---|
| `compute_rank` | `gpr-ranking` / `survey` ranking ([rules/survey.py:116](rules/survey.py)) | `#k of N` (+ `rank_delta` vs prior period) |
| `compute_peer_average` | `gpr-peer-average` / `survey-peer-average` (avg only) | absolute + delta vs subject |
| `compute_yoy` | `YoY Growth` def ([valid_values.py:124](data/valid_values.py)) | signed `%` |
| `compute_breakdown` | — | measure per `group_by` cut (premium-by-cut / score-by-attribute) |
| `count_distinct_years` / `count_distinct_quarters` | — | int (timeline gating) |

**GPR-only tier 1 (premium domain):**

| Primitive | Definition source | Output |
|---|---|---|
| `compute_share_of_portfolio` | `gpr-share-of-portfolio` | `%` of carrier's own book (appetite) |
| `compute_share_of_wallet` | `gpr-sow-definition` | `%` Marsh-placed share |
| `compute_market_presence` | `gpr-marsh-market` | Marsh/market premium for a cut |

**Survey-only tier 1 (perception domain):**

| Primitive | Definition source | Output |
|---|---|---|
| `compute_nps` | `NPS_Group` def ([valid_values.py:123](data/valid_values.py)) | NPS + promoter/passive/detractor split |
| `compute_attribute_breakdown` | `survey-response-analysis` | avg `Score` per Section/Attribute |

**Tier 2 — composite (compose tier 1 via the registry; own only the combining rule):**

| Analyzer | Flow | Composes | Owns | Output |
|---|---|---|---|---|
| `find_whitespace` | GPR | `compute_market_presence`, `compute_peer_average` | ONLY the gap rule: carrier ≈ 0 AND market/peer presence material | ranked top-N `WhitespaceRow` |
| `find_service_gaps` | Survey | `compute_attribute_breakdown`, `compute_peer_average` | ONLY the shortfall rule: carrier score ≪ peer avg on a cut | ranked top-N `GapRow` |

All `group_by` / `filters` flow through `PrimitiveArgs`, so every primitive accepts
arbitrary cuts (GPR: product/cover/business line, SIC, segment, country; Survey:
practice/section/attribute/segment) and arbitrary filters (timeframe, country,
carrier, peers, a specific product/industry/practice).

- **Tier-1 tests:** one `tests/analytics/test_<primitive>.py` per function with a
  hand-checked golden expectation — including a GPR **and** a Survey fixture for the
  shared primitives (proves flow-agnosticism).
- **Tier-2 tests:** `test_find_whitespace.py` / `test_find_service_gaps.py` inject
  **stub** tier-1 primitives and assert the gap/shortfall-ranking logic in isolation
  — proving each composite carries no domain math of its own.
- **Acceptance:** 100% green; each fact returns `support` + `formula`; composites
  pass with dependencies fully stubbed; shared primitives pass both flow fixtures.

## Phase 3 — Planner integration + orchestration

> **Status: landed (2026-08-24), as TOOL CALLING.** The primitives are published to
> the model as callable tools rather than described in a prompt, which is the same
> idea with a tighter contract: the argument schemas are generated from
> `flows.yaml`, so `group_by` / `metric` are closed enums and an invented column is
> not expressible. See `core/analytics/tools/` (catalog → grounding → scope → rows),
> `core/agents/common/analytics_tools.py` (selection strategies + the graph node),
> and the `*_analytics_tools` nodes in the GPR/Survey subgraphs. The chat turn now
> runs: normalizer → planner → **analytics tools** → (LLM-SQL only if uncovered).
> Flag: `ANALYTICS_TOOLS` = `on` (default) | `plan` (no extra LLM call) | `off`.
>
> The analyst solver got the same treatment as one extra tool beside `run_sql`
> (`core/agents/analyst/analytics_tool.py::compute_metric`), so the deep path stops
> re-deriving covered recipes too. It is additive — `run_sql` is untouched and still
> owns everything the library does not cover — and it honours a pinned custom peer
> set the same way the prompt directive does.
>
> Two rules were added on top of the plan, both about not half-answering:
> a selection with ANY rejected call falls back whole rather than computing part of
> the question, and a filter value the registry cannot match to stored data blocks
> the tool path instead of widening the query.

**Goal:** planner selects primitives; orchestrator computes; LLM-SQL becomes fallback.

- Extend `AnalyticalPlan` ([schemas/analytical.py:27](schemas/analytical.py)) with an
  optional `primitives: list[PrimitiveCall]` (name + args). Planner prompt: "if the
  metric is one of {registry names}, emit a primitive call; else describe SQL."
- **New:** `core/analytics/orchestrator.py` — runs the plan's primitive calls via
  the registry, collects `AnalyticsFact`s into state. Unknown/زero primitives →
  fall through to existing LLM-SQL path unchanged.
- **Tests:** `tests/analytics/test_orchestrator.py`; planner tests asserting
  known-metric queries (rank/SoP/SoW/YoY) route to primitives, open-ended ones
  fall back.
- **Acceptance:** known-metric queries produce identical numbers across repeated
  runs (determinism test: run N times, assert equal); fallback path unchanged.

## Phase 3.5 — Compound analysis: the lens→primitive bridge

**The problem this solves.** A single-metric ask ("Zurich's SoP in Canada") maps to
one primitive. But real briefs are compound — *"do a performance analysis for Zurich
in Singapore: SWOT, YoY, whitespace, …"*. That is not one query; it is a **scope
crossed with several analytical moves**. The existing `LensLibrary` + `plan_analysis`
([core/analysis/planner.py](analysis/planner.py)) already selects/orders those moves
(`temporal_trend`, `peer_benchmark`, `whitespace`, …) — today as prompt fragments that
guide the LLM to write SQL. The bridge makes each lens **also declare the primitives it
needs**, so a selected lens deterministically expands into a primitive bundle.

**Flow for a compound request:**

```
scope (deterministic + routing): subject=Zurich→Carrier_Group, country=Singapore, year=latest
        │  → shared PrimitiveArgs.filters applied to EVERY call
plan_analysis (LLM, existing): pick + order lenses  ── good use of the LLM
        │
each lens → its primitive bundle (NEW: lens frontmatter `primitives:`)
        │   temporal_trend       → compute_yoy(group_by=[Product_Line])
        │   dimensional_breakdown → compute_breakdown + compute_share_of_portfolio
        │   peer_benchmark        → compute_rank + compute_peer_average
        │   market_context        → compute_market_presence
        │   whitespace            → find_whitespace([Product_Line, SIC_Major_Class])
        ▼
orchestrator runs the bundles (parallel, cached) → typed EVIDENCE set of AnalyticsFacts
        ▼
synthesis (LLM): narrative + SWOT — over the FACTS only, invents no numbers
        ▼
grounding eval (Phase 5): every number in prose ⊆ evidence
```

**SWOT (and any framed report) is a synthesis frame, not new numbers.** It organises
facts already computed into quadrants — the LLM writes the prose, each bullet cites a
fact:

| Quadrant | Derived from facts |
|---|---|
| Strengths | `rank` #1–2, high `share_of_portfolio`, positive `yoy`, above `peer_average` |
| Weaknesses | low `rank`, negative `yoy`, below `peer_average` |
| Opportunities | `find_whitespace` hits, high-growth `market_presence` |
| Threats | peer `yoy` > carrier `yoy`, declining segments |

**Concrete first wiring — `primitives:` in lens frontmatter.** Add an optional block
read by `plan_analysis`/the orchestrator; absent ⇒ the lens stays prompt-only (today's
behaviour), so this is additive and parity-safe. Example for
[core/analysis/lenses/whitespace.md](analysis/lenses/whitespace.md):

```markdown
---
name: whitespace
description: Find slices where the Marsh book is strong/growing but the carrier is absent or thin.
applies_when: a carrier's product/industry/segment footprint is discussed and gaps vs the market are useful.
requires: [GPR]
primitives:
  - call: find_whitespace
    group_by: [Product_Line, SIC_Major_Class]   # cuts; filters are inherited from scope
  - call: compute_market_presence               # context the gap is measured against
    group_by: [SIC_Major_Class]
---
(unchanged lens body — interpretation guidance for the synthesis step)
```

**Deliverables:**
- Parse `primitives:` in the lens loader ([analysis/planner.py](analysis/planner.py));
  `Lens` gains a typed `primitives: list[PrimitiveCall]` (empty when absent).
- Orchestrator step `run_for_plan(analysis_plan, scope)` — for each selected lens, run
  its bundle with the shared scope filters, dedup by `(primitive, args)` cache key,
  collect into one `EvidenceSet`.
- Synthesis reads the `EvidenceSet`; SWOT/narrative are facts-only.

**Why this is better for compound reports** (the original boardroom failure mode):
cross-section consistency (the YoY in "Weaknesses" *is* the YoY section's fact, no
drift); compute-once caching (`peer_average` shared across rank + peer section + SWOT);
determinism independent of the model's stamina across a long multi-section generation;
graceful partial coverage (an exotic aside falls back to LLM-SQL without sinking the
backbone).

**Acceptance:** a lens with a `primitives:` block yields its facts deterministically for
a scoped compound query; lenses without the block behave exactly as today.

## Phase 4 — Boardroom widget number cutover

**Goal:** kill invented scalars; widgets render computed facts; LLM only labels.

- **Schema changes** ([core/schemas/boardroom.py](schemas/boardroom.py)):
  - `MapCell.intensity (0-100)` → `premium: float` (+ `share_pct`); color scale
    derived from the real value range, not a model guess. ([:159](schemas/boardroom.py))
  - `Opportunity.gap_score (0-100)` → `marsh_share_of_portfolio_pct: float` +
    `rank: int` + `peer_premium: float`. ([:185](schemas/boardroom.py))
  - `Battlecard.product_gaps` → **deterministic top-3** whitespace rows from
    `find_whitespace`, not "0-3 lines" of free text. ([:98](schemas/boardroom.py))
  - `PositioningPoint.premium_strength/broker_perception` → computed percentiles
    over the real peer set. ([:197](schemas/boardroom.py))
- **Survey widget cutover (flow-parity)** — survey boardroom turns get the same
  treatment, fed by the survey primitives:
  - **Service-Gap widget** (sibling of Opportunity Radar) — top-3 from
    `find_service_gaps`: each row carries `carrier_score`, `peer_score`, and
    `shortfall` (real score points), not an invented 0-100. Suppress when no cut
    clears the shortfall threshold.
  - **Attribute/Section heatmap** (sibling of the opportunity map) — `MapCell` value
    is the real `AVG(Score)` per Section × Attribute (or × Practice), color scaled to
    the 1-9 range; no model-guessed intensity.
  - **Positioning** — survey axes use computed percentiles over the real peer set on
    `Score`/`NPS`, same as the premium version.
  - Widget gating keys off survey signals (≥2 Practices/Sections/Attributes, ≥2
    Survey_Years) via the same deterministic detector.
- **Timeline gating** — replace the loose `distinct periods >= 2`
  ([agents/boardroom.py:258](agents/boardroom.py)) with:
  - `distinct_years >= 2` → timeline keyed by **year**;
  - `distinct_years == 1 && distinct_quarters >= 2` → keyed by **quarter**;
  - else **suppress**.
  - Enforce "same cuts": fixed cut-set, one event per `(period × cut)` so every
    period shows the comparable slice (easy comparison).
- **Fill flow** — `_fill_widgets` ([agents/boardroom.py:292](agents/boardroom.py))
  passes **computed facts** (not just `commentary`) into each fill call; the LLM
  writes `title`/`note`/`recommendation` only. Numbers come pre-filled.
- **Tests:** `tests/test_boardroom_rows.py` extended — assert widget numbers equal
  primitive outputs, timeline gating matrix (1yr/1q, 1yr/4q, 3yr), product_gaps ≤ 3
  and ranked.
- **Acceptance:** no widget field accepts a free 0-100 from the model; numbers
  reproducible run-to-run.

## Phase 5 — Narration grounding eval (backstop)

**Goal:** since numbers now come from primitives, the eval shrinks to "every number
in prose matches a computed fact."

- **New:** `core/analytics/grounding.py` — extract numerics from insight/commentary
  text, assert each ⊆ `AnalyticsFact` values (within tolerance). Flag/strip
  ungrounded claims. Reuses the `validation-report-claim-grounding` skill stub.
- **Wire-in:** insight writer ([core/agents/analyst/insight_writer.py](agents/analyst/insight_writer.py))
  and boardroom core call.
- **Tests:** `tests/analytics/test_grounding.py` (grounded passes; invented number
  flagged).
- **Acceptance:** a deliberately hallucinated number in narration is caught.

## Phase 6 — Supporting data in the UI

**Goal:** surface `AnalyticsFact.support` (the rows behind each number) under
widgets/insights, so the user can audit any figure.

- Thread `support` through the boardroom digest → builder
  ([ui/boardroom/builder.py](../ui/boardroom/builder.py)) as an expandable
  "evidence" table per widget.
- **Acceptance:** each computed widget number has a click-through to its rows.

---

## Sequencing & rationale

1. **Phase 0 → 1 first.** Phase 1 is the tracer bullet: smallest real slice, fixes
   the most-felt bug ("latest year"), and validates the contract before we invest in
   Phase 2's library breadth.
2. **Phase 2 before 3.** Settle/test every primitive in isolation before wiring the
   planner to them — so integration debugging is never "is it the math or the wiring?".
3. **Phase 4 is the visible payoff** (business-readable radar/map/timeline). It
   depends on 2's primitives existing.
4. **Phases 5–6 are hardening/UX** — valuable but not blocking the reliability win.

## Risks & mitigations

- **Definition drift** — primitive math must match the skills. *Mitigation:* each
  primitive docstring cites its source; golden tests are hand-verified.
- **Fallback ambiguity** — planner mis-routes a known metric to LLM-SQL. *Mitigation:*
  registry-name allowlist in the planner prompt + integration tests per metric.
- **Parity regressions** — *Mitigation:* golden traces stay green every phase; no
  phase ships red.
- **Schema migration (Phase 4)** — changing widget fields touches PPT export and
  editor. *Mitigation:* update [ui/boardroom/ppt_export.py](../ui/boardroom/ppt_export.py)
  and `editor.py` in the same PR; widget tests cover both.

---

## Appendix A — Calculation pattern (worked examples over the SQLite DB)

Data lives in SQLite via SQLAlchemy ([config/db_config.py:5](../config/db_config.py)):
tables `GPR`, `Carriers` (survey), `Peers`. Each primitive **templatizes a SQL recipe
you already trust** (see [core/rules/gpr.py:383](rules/gpr.py)) instead of having the
LLM rewrite it per turn.

### The one pattern

> **Aggregation is pushed down to SQLite** (SUM / AVG / RANK / window functions —
> set-based, fast, exact). **Python only parametrizes the query and wraps the result
> into a typed `AnalyticsFact`.** Composites do *no* SQL — they orchestrate tier-1
> facts in Python.

Args are structured, so the query is a **safe parametrized template**: column names
checked against an allowlist (no injection, no hallucinated columns); values bound as
parameters.

```python
from sqlalchemy import text
import pandas as pd
from config.db_config import engine          # existing SQLite engine

SCHEMA = {                                    # allowlist per flow (from valid_values.py)
    "gpr":    set(GetValidData.definitions_gpr),
    "survey": set(GetValidData.definitions),
}

def _safe(flow, col):
    if col not in SCHEMA[flow]:
        raise ValueError(f"unknown column {col!r}")   # rejects anything not a real column
    return col

def _where(flow, filters, params):
    clauses = []
    for col, val in filters.items():
        _safe(flow, col); key = f"f_{col}"
        # GPR rule: wrap text comparisons in LOWER(); numbers compared directly
        clauses.append(f"LOWER({col}) = LOWER(:{key})" if isinstance(val, str) else f"{col} = :{key}")
        params[key] = val
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""
```

### A.1 `compute_share_of_portfolio` — GPR (your exact Appetite recipe)

Query *"Share of Portfolio for Zurich across Product_Line, Canada, latest year"* →
`PrimitiveArgs(flow="gpr", metric="premium", group_by=["Product_Line"],
filters={"Carrier_Group":"Zurich","Country":"Canada","Year":2024})`

```python
def compute_share_of_portfolio(args, db=engine) -> list[AnalyticsFact]:
    params = {}
    where = _where(args.flow, args.filters, params)
    cuts  = ", ".join(_safe(args.flow, c) for c in args.group_by)
    sql = f"""
        SELECT Carrier_Group, {cuts},
               SUM(Premium) AS carrier_premium,
               ROUND(100.0 * SUM(Premium)
                     / NULLIF(SUM(SUM(Premium)) OVER (PARTITION BY Carrier_Group), 0), 1) AS sop_pct
        FROM GPR{where}
        GROUP BY Carrier_Group, {cuts}
        ORDER BY sop_pct DESC
    """                                   # ← identical to rules/gpr.py:383, just parametrized
    rows = pd.read_sql(text(sql), db, params=params).to_dict("records")
    return [AnalyticsFact(
        name="share_of_portfolio", value=r["sop_pct"], unit="%",
        rendered=f'{r["sop_pct"]:.1f}%',
        dims={"carrier": r["Carrier_Group"], **{c: r[c] for c in args.group_by}},
        support=[r],                                  # rows behind the number → UI
        formula="SUM(Premium) per cut ÷ carrier total Premium × 100",
    ) for r in rows]
```

### A.2 `compute_rank` — the SAME function for both flows

`flow` selects table / measure / aggregation; everything else is args:

```python
FLOW = {
    "gpr":    {"table": "GPR",      "agg": "SUM", "measure": "Premium", "entity": "Carrier_Group"},
    "survey": {"table": "Carriers", "agg": "AVG", "measure": "Score",   "entity": "Carrier"},  # AVG per survey rule
}

def compute_rank(args, db=engine) -> list[AnalyticsFact]:
    f = FLOW[args.flow]; params = {}
    where = _where(args.flow, args.filters, params)
    cuts  = ", ".join(_safe(args.flow, c) for c in args.group_by)
    sql = f"""
        WITH agg AS (
            SELECT {f['entity']} AS entity, {cuts},
                   {f['agg']}({f['measure']}) AS measure
            FROM {f['table']}{where}
            GROUP BY {f['entity']}, {cuts}
        )
        SELECT *, RANK() OVER (PARTITION BY {cuts} ORDER BY measure DESC) AS rank,
                  COUNT(*) OVER (PARTITION BY {cuts}) AS of_n
        FROM agg
    """
    rows = pd.read_sql(text(sql), db, params=params).to_dict("records")
    return [AnalyticsFact(name="rank", value=r["rank"], unit="rank",
                          rendered=f'#{r["rank"]} of {r["of_n"]}',
                          dims={"entity": r["entity"]}, support=[r],
                          formula=f"RANK() over {f['agg']}({f['measure']}) desc") for r in rows]
```

- GPR: ranks carriers by `SUM(Premium)` across `Product_Line`.
- Survey: `flow="survey", group_by=["Attribute"]` → ranks by `AVG(Score)` across `Attribute`.

### A.3 `find_whitespace` — GPR composite, **no SQL of its own**

Calls tier-1 primitives via the registry; owns ONLY the gap rule:

```python
NEAR_ZERO, MATERIAL = 1_000, 50_000

def find_whitespace(args, registry, top_n=3) -> list[WhitespaceRow]:
    market  = {f.dims_key: f.value for f in registry["market_presence"](args)}  # Marsh premium per cut
    carrier = {f.dims_key: f.value for f in registry["breakdown"](args)}        # carrier premium per cut
    gaps = [
        WhitespaceRow(cut=cut, carrier_premium=carrier.get(cut, 0), market_premium=mkt)
        for cut, mkt in market.items()
        if carrier.get(cut, 0) <= NEAR_ZERO and mkt > MATERIAL          # ← the ONLY logic it owns
    ]
    gaps.sort(key=lambda g: g.market_premium, reverse=True)
    return gaps[:top_n]                                                 # deterministic top-3
```

### A.4 `find_service_gaps` — Survey composite (sibling of whitespace)

Same shape, perception domain: carrier `AVG(Score)` materially **below peer average**
on a Section/Attribute. Composes `compute_attribute_breakdown` (carrier score per cut)
+ `compute_peer_average` (peer avg per cut, **average only — never individual**, per
[rules/survey.py:78](rules/survey.py)). Owns ONLY the shortfall rule — no premium /
Marsh / SoW logic.

```python
SHORTFALL = 0.5   # score points below peer average to count as a gap

def find_service_gaps(args, registry, top_n=3) -> list[GapRow]:
    carrier = {f.dims_key: f.value for f in registry["attribute_breakdown"](args)}  # AVG(Score) per cut
    peer    = {f.dims_key: f.value for f in registry["peer_average"](args)}         # peer AVG(Score) per cut
    gaps = [
        GapRow(cut=cut, carrier_score=c, peer_score=peer[cut], shortfall=round(peer[cut] - c, 2))
        for cut, c in carrier.items()
        if cut in peer and (peer[cut] - c) >= SHORTFALL                 # ← the ONLY logic it owns
    ]
    gaps.sort(key=lambda g: g.shortfall, reverse=True)
    return gaps[:top_n]                                                 # deterministic top-3
```

The two tier-1 primitives it composes are ordinary parametrized queries over
`Carriers` (the SQL already exists — carrier-vs-peer-average per `SurveyPractice`/
`Attribute` in [rules/survey.py:184](rules/survey.py)). `find_service_gaps` itself
stays pure-Python and is unit-tested with both dependencies stubbed.

### Why this is fast and reliable

- **SQLite does the set-based math** (`SUM`/`AVG`/`RANK`/window) — faster and exact vs
  an LLM "computing in its head."
- **No SQL-generation LLM call, no fixer retries** — a template can't be malformed.
- **Same engine you already use** — no new infra.
- **Deterministic → cacheable**: `(primitive, args)` is a perfect cache key.
