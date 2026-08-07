# Carrier Survey slide — design

Add the authored `template/survey_template.pptx` to the QBR deck as a per-country page,
generated only when Setup's DATA BASIS is **Premium + survey**.

## 1. What the template contains

One slide:

| shape | id | what it is |
|---|---|---|
| Title | 2 | `Carrier Survey` |
| Subtitle | 4 | `Country (1)` — rewritten by the existing `fill._label_subs` |
| Table | 49 | 8 rows × 9 cols, every data cell authored as `x.x` |
| Picture | 52 | the banding legend (static art, never touched) |
| Picture | 67 | the ribbon chart — a think-cell **render**, currently 2022–2026 |
| OLE | 7 | `think-cell data - do not delete` |
| Text | 3 | `Comparison with last year` |

Table axes, exactly as authored:

- rows (`Sections`): Underwriting, Client Focus, Policy Administration,
  `Claims – Claims Professionals`, `Claims – Non-Claims Professionals`, Loss Control,
  **Total**. The two Claims rows use an en dash (U+2013), so header matching must normalise
  dashes and whitespace rather than compare raw strings.
- columns (`SurveyPractice`): CE/CM, Claims, Cyber, Energy, FINPRO, Property,
  Marsh Multinational, **Total**

The ribbon is an image, not a fillable chart, and nothing in `template_fill` can refill a
picture today. That is the one genuinely new capability this change needs.

## 2. Placement

`assemble.py` already merges ordered sub-decks, so no slide surgery is required — a survey
sub-deck is planned directly after each country's:

```
overall │ product₁…ₙ │ country₁ ▸ survey₁ │ country₂ ▸ survey₂ │ … │ end
```

- New axis constant `SURVEY = "survey"`, deliberately **not** in `_SCOPE_AXES`: it is not a
  scope choice, it is gated on data basis.
- `plan_subdecks(result, *, scope, data_basis)` appends `SubDeck("survey", …)` inside the
  existing country loop when all three hold:
  1. `data_basis == "premium_survey"`,
  2. the `survey` axis is registered and its `.pptx` is on disk (`_buildable()`),
  3. the country has survey rows.
- `data_basis` threads `generate.py` → `assemble_deck` → `plan_subdecks`. It is already
  carried into the selection and read by nobody; this change is what reads it.
- The sub-deck's values carry `country_name[0] = <country>`, so the existing
  `fill._label_subs` rewrites `Country (1)` with no new code.
- A country with no survey data keeps its 5 slides. A run with `data_basis == "premium"`
  produces today's deck unchanged.

## 3. Modules

Follows the `gwp_page` / `lc_page` pattern — detection is header/geometry driven, never a
slide index — but as a subpackage, because there is more than one responsibility:

```
studio/template_fill/survey/
  page.py     augment() → table-cell + picture bindings;  values() → the fill payload
  facts.py    deterministic survey queries (flow="survey", table Carriers)
  bands.py    pure: delta → band colour
  ribbon.py   pure: RibbonSpec → PNG bytes
```

`maps/survey.json` stays minimal — it registers `survey` → `template/survey_template.pptx`
and nothing else. Every cell is recognised dynamically by `page.augment`, so re-authoring
the template does not invalidate a hand-maintained 56-entry map.

`page.values` and `page.augment` join the existing provider tuples in
`assemble._build_subdeck` and `assemble._augmented_manifest`, which already swallow a
failing provider so a broken survey page can never sink the rest of the deck.

## 4. Two new generic capabilities in `fill.py`

Neither exists today. Both are small, generic, and sit beside `_fill_charts` in
`fill_template`:

- **`_fill_cell_backgrounds(prs, values)`** ← `values["cell_fills"]`, keyed `"slide:shape"`
  → `[{r, c, hex | None}]`. `None` clears to no fill.
- **`_replace_pictures(prs, values)`** ← `values["pictures"]`, keyed `"slide:shape"` → PNG
  bytes. Swaps the image part's blob so the authored frame, crop and z-order survive.

`_replace_pictures` also deletes the `think-cell data - do not delete` OLE shape on any
slide whose picture it replaced. Otherwise a viewer with think-cell installed could
re-render the authored 2022–2026 chart on top of ours.

## 5. The table

Fixed axes: authored headers are kept verbatim. Cells whose Section/Practice is absent from
the data keep the `x.x` placeholder and take no fill.

`facts.py` queries `flow="survey"`, `metric="score"` (AVG) for the subject carrier ×
country, once at the latest year and once at latest − 1:

| what | `group_by` |
|---|---|
| body cells | `(Sections, SurveyPractice)` |
| Total column | `(Sections,)` |
| Total row | `(SurveyPractice,)` |
| corner cell | `()` |

Totals are their own `AVG` over the raw rows, **not** a mean of the displayed cells. That
is what "straight average of the underlying scores" means, and it is why they are separate
queries rather than arithmetic over the grid.

- Reporting year = `max(Survey_Year)` present for that country; prior year = that minus 1.
- Cell text = score to 1 decimal place.
- Cell fill = band of (score − the same cell's prior-year score).
- No prior-year value for a cell ⇒ no fill (the number still prints).

### Scope

The survey slide is scoped by **country + carrier + year only**. The premium-side filters
(`Product_Line`, `Client_Segment`, industry) are ignored: they are a different taxonomy from
`SurveyPractice`, and honouring a `Product_Line` pin would blank most of the page whose
columns *are* the practices.

### Banding

Read pixel-exact off the template's own legend picture (shape 52). Neutral band is
inclusive; every other edge lands in the more extreme band.

| Δ vs prior year | fill |
|---|---|
| Δ ≤ −1 | `#CF3638` |
| −1 < Δ ≤ −0.5 | `#FFBF35` |
| −0.5 < Δ < −0.2 | `#FFF3DC` |
| −0.2 ≤ Δ ≤ 0.2 | no fill |
| 0.2 < Δ < 0.5 | `#ABDC97` |
| 0.5 ≤ Δ < 1 | `#5BBF41` |
| Δ ≥ 1 | `#008542` |

Lives in `bands.py` as one ordered threshold table with a single pure
`band_for(delta) -> str | None`, so a correction is a one-line edit.

## 6. The ribbon

`RibbonSpec` → PNG, rendered with plotly + kaleido at the authored picture's exact aspect
ratio (1162 × 303) at `scale=2`.

- **x axis = Section**, in the table's authored row order, `Total` excluded. This replaces
  the authored year axis.
- Each column is a rank-ordered stack of score boxes, best at top, ranked by the carrier's
  average score in that section for the reporting year and country.
- Carriers = subject + the Setup peer selection, capped at 9 rows (the count the authored
  art fits). The subject is always kept; the cap drops the lowest-scoring peers.
- **No carrier names.** `flows.yaml` sets `peer_names_allowed: false` for the survey flow,
  and the authored art shows scores only.
- Colours, sampled from the authored picture: subject box `#7BBCFC` with band `#BBDDFE`;
  peers `#BCB9B4` with band `#DDDBD9`. The subject's band is drawn last so it reads on top.
- Bands are filled bezier paths between adjacent columns.
- Title: `Peers Ranked by Survey Scores (Section level)` — the authored wording, corrected
  to what the axis now shows.

`ribbon.py` is pure: `RibbonSpec` in, PNG bytes out, no data access. `facts.py` builds the
spec; `page.py` calls the renderer.

## 7. Dependency

Add `kaleido>=1.0.0` to `pyproject.toml`.

Verified on this machine: kaleido 1.3.0 exports a PNG in ~1.7s using the installed Chrome.
kaleido 0.2.1 **hangs** on this Windows box and must not be pinned. kaleido v1 needs a
Chrome/Chromium; where none exists, `plotly_get_chrome` fetches one.

If the renderer is unavailable the page degrades rather than failing: the table still fills
and the authored picture stays in place.

## 8. Seed data

`studio/_seed/studio_seed.db` contains only `GPR` and `Peers`, so the survey flow exists
only in the live DB and there is no local end-to-end path.

Add a deterministic `Carriers` table to `studio/seed.py` matching `flows.yaml`:
`SurveyCountry, Carrier, SurveyPractice, Region, Sections, Attributes, SurveySegment,
Survey_Year, Score, NPS Score` — the existing 12 carriers × 4 countries × the 6 authored
Sections × the 7 authored Practices × 2023–2025, fixed RNG seed, scores in a realistic
5.5–7.5 range with enough year-on-year movement to exercise every band.

## 9. Testing

Unit (pure functions):

- `bands.band_for` at every boundary, including the inclusive neutral band and `None` delta.
- grid assembly from synthetic facts: missing Section/Practice ⇒ placeholder, no fill.
- ribbon spec ordering: best-first, subject always present, cap at 9, subject survives the cap.

Integration (module boundaries):

- `page.augment` finds the table and picture on the real `survey_template.pptx`.
- `page.values` emits `cell_fills` and `pictures` payloads keyed `"slide:shape"`.
- `fill._fill_cell_backgrounds` / `_replace_pictures` against a scratch deck.

End-to-end (the real workflow):

- `data_basis="premium_survey"` → `plan_subdecks` interleaves one survey deck per country;
  `assemble_deck` produces a `.pptx` whose per-country blocks are 6 slides, with real
  numbers in the table, at least one coloured cell, and an image blob differing from the
  authored one.
- **Regression:** `data_basis="premium"` produces today's deck, slide-for-slide.

Failure paths:

- a country with no survey rows → no survey slide, no exception;
- the `Carriers` table absent from the DB → no survey slides at all, deck still exports;
- kaleido unavailable → table fills, authored picture retained;
- `STUDIO_AI=off` → unaffected (this page is fully deterministic; no LLM is involved).

## 10. Setup page

Remove the "Survey pages are not generated yet — this choice is recorded with the deck."
note from `studio/page/authoring/setup.py`. `test_studio_setup_form.py` asserts on the
`data_basis` wiring and needs to stay green.
