# QBR Studio commentary implementation

Implemented in the local checkout, 11 September 2026. This covers the `studio/template_fill` path used by QBR Studio authoring and export, including Portfolio Solutions and Trading commentary. It is not a live model quality certification.

## What changed

- **Select the finding before writing.** A section receives eligible, citable findings and explicit questions. A positive result cannot become a challenge just to fill the column. Unsupported future risks receive an evidence limitation.
- **Preserve meaning in the evidence.** Carrier and Marsh movements retain their direction. Prior premiums, named product/geography scope, prior segment shares and underlying segment premiums accompany the comparisons. Small movers below the existing 1% carrier-premium floor are excluded from AI evidence too.
- **Compare equivalent quarters.** Quarterly observations use the same quarter a year earlier, with three observed months on each side and a calendar-end check. Missing months are not zero-filled. A very small, zero or negative prior base suppresses the quarterly percentage headline; absolute premiums remain available. Annual YoY versus quarterly QoQ no longer creates an acceleration claim.
- **Describe the benchmark actually computed.** Studio's placement benchmark uses the largest up-to-five carriers in scope; the subject is eligible. It is an average per carrier, not combined share or the separately configured peer group. The actual population count is carried to the writer. A premium equivalent is a scenario at a constant Marsh denominator, not winnable premium or a forecast.
- **Write independent, readable points.** One finding per bullet, usually one or two sentences. Name the entity, metric and comparison. Clear metric openings and repeated carrier names are allowed. One supported finding is sufficient; extra bullets and forced consequence clauses are no longer required.
- **Verify every claim.** Qualitative claims and proposed actions need citations too. Unknown citations, unsupported numbers, simple reversed movements, ambiguous comparison phrases and overlong bullets are rejected. The semantic reviewer checks section fit, meaning, unsupported causality and domain terminology. Missing or misaligned review responses cannot approve text.
- **Repair without reintroducing repetition.** Repairs see accepted findings; repeated recognized claims are checked against earlier accepted fields and partial cache hits. A bullet's verdict stays attached to its own section even when identical text appears elsewhere.
- **Improve rule-based previews.** Segment comparisons name whose share changed, preserve Marsh growth direction, and use current/prior shares. Preview prose no longer invents demand or renewal explanations, describes negative growth as growth, or manufactures a challenge from a positive result. Explicit carrier names survive formatting.

## Runtime behavior

The default is now `COMMENTARY_MODE=ai_required`. If a requested commentary field cannot be authored and verified after repair, the export stops with the reasons. This avoids a stakeholder deck silently receiving fallback prose.

`COMMENTARY_MODE=auto` explicitly permits a deterministic fallback. `COMMENTARY_MODE=off`, or the overriding `STUDIO_AI=off`, provides a deterministic preview without model calls. These modes do not represent verified AI commentary. Every AI mode writes directly from evidence rather than imitating a finished rule draft.

The cache version changed. Scope, movement direction and glossary content are included in cache identity; old commentary should not survive unchanged merely because its numeric magnitudes match.

## Review set and local live check

`studio/template_fill/commentary_examples.py` contains 16 synthetic cases covering share/premium divergence, Services share loss, Environmental benchmark gaps, absence, small quarterly bases, seasonality, contribution, benchmark population and insufficient evidence. Each has reference wording, a misleading counterexample, and the reason it should be rejected. These are review cases, not a hard-coded script for production commentary.

From the repository root, with the project's Python environment:

```powershell
python tools/evaluate_icg_commentary.py
```

The command writes `outputs/icg-commentary-review/review.md` and `results.json`. Offline success checks reference numbers, citations and readability; it does not assess the AI's writing or its semantic judgment.

On the machine where the application's AI configuration already works, enable Studio AI and run:

```powershell
python tools/evaluate_icg_commentary.py --live --repeats 3 --output outputs/icg-commentary-live
```

No credential values need to be shared. The command uses the application's existing configuration, authors and verifies commentary through the production writer, and checks whether the semantic reviewer rejects the misleading examples. It fails if authorship is unavailable, verification fails, or a misleading example is approved. Three repeats exercise variation; stakeholder review remains necessary for tone and usefulness.

For that review, each bullet should answer: **Whose metric? What changed or differs? Compared with what? Does the evidence justify the interpretation and the proposed next step?** A point that needs translation, invents an operational cause, or merely repeats another point does not meet the standard.

## Validation and limits

Final local result: **572 tests passed in 197.99 seconds**. The report is `outputs/icg-commentary-review/regression.xml`. The run included the commentary, segment, privacy, ICG definition, template-feedback and Studio AI-agent tests. The 16-case offline reference evaluation also passed; its output is in `outputs/icg-commentary-review/results.json`. Syntax checks passed for all 29 changed Python files, and `git diff --check` reported no whitespace errors with Windows line endings accounted for.

The regression suite covers evidence, numerical and semantic-verification failures, section selection, batching, repair, caching, repetition, segment calculations, definitions, privacy, template filling and file export. Model responses in export tests are controlled fixtures; they validate integration rather than AI prose quality.

The test process used `.venv-codex/Scripts/python.exe`, with the existing `.venv/Lib/site-packages` appended as a fallback for dependencies absent from that runtime. AI was disabled except in tests that supply controlled model fixtures. Test temporary directories were created under `outputs`, avoiding the inaccessible default temporary directory.

PowerPoint export tests use the repository's existing `STUDIO_PPT_MERGE_ENGINE=opc` path for local CI and reopen the generated files with `python-pptx`. Native Windows PowerPoint automation was unavailable in this session, so these checks do not establish rendering fidelity for production vendor templates. The production merge default was not changed.

The local checkout has no usable live model configuration, and the user cannot provide credentials. Live generation, repeated live semantic evaluation and stakeholder sign-off therefore remain unverified. The implementation cannot promise an absolute best outcome without that final check.

Three observed monthly records establish a comparable quarterly window, not full warehouse completeness. The existing annual totals retain their source period definition. Appetite, capacity, retention, pricing, profitability and operational causes still require additional evidence; premium and placement shares alone do not measure them. Deterministic duplicate and direction checks are deliberately limited; the semantic reviewer remains essential.
