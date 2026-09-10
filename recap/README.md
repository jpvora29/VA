# Recap — the business review recap engine

An LLM pipeline that turns historical business review PowerPoint decks into a **structured, auditable insight repository** and writes a concise recap for the next meeting.

This is the engine behind the **Recap** workspace of the ICG Virtual Analyst (`ui/recap/`).
It runs equally well from the command line (`recap/main.py`) — the workspace and the CLI
call the same `recap.run.run_recap_pipeline`.

**Credentials come from the application's `.env`**, through `core.llm.clients`. There are
no Azure settings in this package: a tier name (`balanced`, `fast`, `reason`) is all it
asks for, and `<TIER>_DEPLOYMENT` in the environment decides what that means.

---

## Output

Every run produces:

| Component | Description |
|---|---|
| **Executive Summary** | One-line synthesis of the overall business/client situation |
| **Key Takeaways** | 2–4 bullet points per umbrella category |
| **Action Items** | Prioritised list with owner, deadline, and urgency |

---

## Pipeline Stages

```
PPT → Raw Extraction → Noise Filtering → Semantic Content Units
    → Business Glossary → Metadata Enrichment
    → 4× Umbrella Classifiers (concurrent)
    → Sub-category + Action Item Classifiers
    → Structured Insight Store → Recap Generator
```

| Stage | Module | Description |
|---|---|---|
| 1 | `extraction/extractor.py` | Extracts every slide element, table, chart, image, note |
| 2 | `filtering/noise_filter.py` | Rule-based + LLM noise filtering, fully auditable |
| 3 | `grouping/content_units.py` | Groups related elements into Semantic Content Units (SCUs) |
| 4 | `glossary/glossary.py` | Dynamic company glossary retrieval per SCU |
| 5 | `enrichment/enrichment.py` | LLM metadata enrichment (LOB, KPI, region, direction…) |
| 6–9 | `classification/` | 4 independent Boolean umbrella LLMs + sub-category + action items |
| 13 | `store/insight_store.py` | Persists structured insights; filterable and traceable |
| 14 | `generation/recap_generator.py` | LLM recap with fallback rule-based generation |
| 15 | `generation/pptx_renderer.py` | Renders the recap into `assets/QBR Recap Template.pptx` |

---

## Taxonomy

Each insight is classified against four umbrella categories:

| Umbrella | Description |
|---|---|
| **Performance & Position** | Financial/operational results, KPI attainment, market share |
| **Growth & Opportunities** | New business, pipeline, revenue growth, strategic opportunities |
| **Market & External Conditions** | Macro-economic, regulatory, competitive landscape, industry trends |
| **Relationship & Collaborations** | Partnerships, client engagement, governance, stakeholder updates |

Classification is **multi-label** — one insight can belong to multiple umbrellas simultaneously.

Formal definitions are in `taxonomy/taxonomy_definitions.py` and are injected verbatim into every classifier prompt.

---

## Setup

Dependencies and credentials are the application's, not this package's: install the repo
(`uv sync`) and set the usual `API_KEY` / `ENDPOINT` / `VERSION` / `DEPLOYMENT` in the
repo-root `.env`, exactly as Studio, the Chatbot and MoM need them.

The glossary and the recap template ship in `recap/assets/`, so a fresh checkout runs.

---

## Usage

### From the app

Open the **Recap** tab, drop one or more `.pptx` review decks, check the chips read off the
cover slide, press **Generate recap**, download the `.pptx`.

### Process a single deck from the command line

```bash
python -m recap.main run \
    --file decks/client_q2_2026.pptx \
    --deck-id client_q2_2026 \
    --client "Acme Corp" \
    --date 2026-04-01 \
    --quarter Q2 \
    --year 2026 \
    --glossary glossary.json \
    --output outputs/
```

### Process multiple decks (batch)

```bash
python -m recap.main run-batch \
    --manifest decks/manifest.json \
    --glossary glossary.json \
    --output outputs/
```

**manifest.json format:**
```json
[
  {
    "file_path": "decks/q1_2026.pptx",
    "deck_id":   "client_q1_2026",
    "client_name": "Acme Corp",
    "meeting_date": "2026-01-15",
    "quarter": "Q1",
    "year": 2026
  }
]
```

### Query the insight store

```bash
# All performance insights
python -m recap.main query --store outputs/client_q2_2026_insights.json \
    --umbrella performance_and_position

# High-urgency action items only
python -m recap.main query --store outputs/client_q2_2026_insights.json \
    --action-items-only --urgency high

# Filter by region and minimum confidence
python -m recap.main query --store outputs/client_q2_2026_insights.json \
    --region APAC --min-confidence 0.8
```

### Trace an insight back to its source

```bash
python -m recap.main trace \
    --store outputs/client_q2_2026_insights.json \
    --insight-id INS_client_q2_2026_CU_client_q2_2026_s003_002
```

---

## Glossary File Format

```json
{
  "terms": [
    {
      "term": "Share of Wallet",
      "aliases": ["SoW", "wallet share"],
      "definition": "The percentage of a client's total insurance spend placed through our firm.",
      "category": "metric",
      "lob": ["All"],
      "notes": "Internal definition — differs from generic usage."
    },
    {
      "term": "Client Health Score",
      "aliases": ["CHS"],
      "definition": "A composite score (0–100) measuring relationship strength across six dimensions.",
      "category": "kpi"
    }
  ]
}
```

---

## Configuration

All settings can be overridden via environment variables:

Credentials and deployments are NOT here — see `core/llm/clients.py` (`API_KEY`,
`ENDPOINT`, `VERSION`, `DEPLOYMENT`, and the optional `<TIER>_DEPLOYMENT`). What this
package reads:

| Variable | Default | Description |
|---|---|---|
| `MAX_CONCURRENT_LLM_CALLS` | `10` | Global semaphore on simultaneous API calls |
| `MAX_CONCURRENT_INSIGHT_CLASSIFICATION` | `5` | Per-insight classification concurrency cap |
| `MAX_LLM_RETRIES` | `3` | Retries on rate-limit / API errors |
| `RETRY_BASE_DELAY` | `2.0` | Base seconds for exponential back-off |
| `NOISE_AMBIGUITY_THRESHOLD` | `0.85` | Rule confidence below which the LLM is asked |
| `RECAP_MIN_CONFIDENCE` | `0.0` | Minimum insight confidence for recap inclusion |
| `RECAP_MAX_INSIGHTS` | `60` | Insight cap per recap prompt |
| `RECAP_RUNS_DIR` | `outputs/recap` | Where a run's directory is created |

---

## Provenance

Every recap statement traces back to its source:

```
Recap Statement
  → StructuredInsight (insight_id)
  → SemanticContentUnit (content_unit_id)
  → RawElement(s) (source_element_ids)
  → RawSlide (slide_number)
  → RawDeck (deck_id → original .pptx file)
```

Use `python -m recap.main trace --insight-id <id>` to inspect the full chain.

---

## Project Structure

```
recap/
├── run.py                     # ONE run, top to bottom (what the workspace calls)
├── jobs.py                    # The run in a daemon thread, for the UI to poll
├── progress.py                # The stages, and the rail phases they light
├── metadata.py                # What the cover slide says (client, period)
├── uploads.py                 # Staged decks (core.uploads, bound to this runs dir)
├── main.py                    # CLI entry point
├── config.py                  # Lookup tables, tuning, RunPaths — no credentials
│
├── assets/                    # config.yaml, glossary.json, QBR Recap Template.pptx
├── schemas/                   # Pydantic data models (source of truth)
├── extraction/                # Stage 1: Raw PPT extraction
├── filtering/                 # Stage 2: Noise filtering
├── grouping/                  # Stage 3: Semantic content units
├── glossary/                  # Stage 4: Business glossary
├── enrichment/                # Stage 5: Metadata enrichment LLM
├── classification/            # Stages 6–10: Umbrella + action item classifiers
├── store/                     # Stage 13: Structured insight store
├── generation/                # Stage 14: Recap generator + PPTX renderer
├── pipeline/                  # Stage 12: Async orchestrator (one deck)
├── taxonomy/                  # Formal umbrella + sub-category definitions
├── prompts/                   # All LLM system prompts
└── llm/                       # Async client over core.llm.clients
```

The workspace that drives it lives in `ui/recap/` (page + callbacks) and
`assets/va_recap.css`; tests are `tests/test_recap_pipeline.py` and
`tests/test_recap_workspace.py`.
