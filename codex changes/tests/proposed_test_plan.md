# Proposed Test Plan

These tests are proposed only. They are not active runtime tests until copied or
adapted into the real `tests/` directory.

## Skill Loader Tests

File: `tests/test_skill_loader.py`

Cases:

- loads all markdown skills with PyYAML
- loads all markdown skills with fallback parser
- ignores `README.md`
- respects `flow`
- includes `cross` skills for any flow
- respects `scope`
- respects `always: true`
- trigger matching handles hyphenated phrases
- trigger matching avoids incidental substrings
- priority ordering is descending
- `load_many()` deduplicates `cross` skills by name
- malformed frontmatter is reported or skipped with diagnostics

## Skill Coverage Tests

File: `tests/test_skill_coverage.py`

Cases:

- every flow/scope has at least one baseline skill
- every high-risk metric has examples and test queries
- every `requires` skill exists
- no `conflicts_with` pair loads together for the same query
- every pitch skill has an evidence rule

## Golden Query Evals

File: `tests/evals/golden_queries.yaml`

Suggested cases:

- GPR Share of Wallet by product
- GPR Share of Portfolio by product
- GPR peer benchmark
- GPR top 5 carrier ranking
- Survey score by section
- Survey peer average
- Survey NPS trend
- GIMMI market rate by quarter
- Hybrid premium plus broker perception
- Pitch whitespace evidence
- Chart selection and axis formatting cases from
  `codex changes/tests/chart_output_eval_cases.yaml`

Each case should assert:

- route
- loaded skills
- plan shape
- SQL tables
- forbidden columns absent
- evidence row shape
- response contains required terms
- response excludes confidential peer names

## Pitch Builder Tests

File: `tests/test_pitch_builder_shadow.py`

Cases:

- `_build_question_prompt()` includes carrier, country, year, and theme
- KPI premium field maps consistently
- progress callback listens to the real button id
- `_json_for_prompt()` truncates over-limit payloads
- report validator flags unsupported claims
- peer names are not present in report-ready content

## Chart Output Tests

File: `tests/test_chart_output_quality.py`

Cases:

- Line chart is rejected when x is not time-like.
- Multi-year category breakdown uses `bar`, not `line`.
- Explicit trend over years can use `line`.
- One-year breakdown uses category x, not year x.
- Year axis never displays fractional ticks.
- Numeric year columns are coerced to categorical or integer tick arrays.
- Chart override logs the original chart type and override reason.
- Existing valid line, combo, scatter, and donut charts still render.
