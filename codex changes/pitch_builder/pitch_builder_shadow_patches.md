# Pitch Builder Shadow Patches

These are proposed patches only. They are not applied to the runtime.

## 1. Enforce Filters In Every Question

Problem:

`_build_question_prompt()` currently returns the raw question, so selected
carrier/country/year may not be enforced for derived or manual questions.

Draft replacement:

```python
@staticmethod
def _build_question_prompt(theme_key: str, filters: dict[str, Any], question: str) -> str:
    theme_label = PitchBuilderWorkflow.THEME_LABELS.get(theme_key, theme_key or "Pitch")
    carrier = filters.get("carrier") or "the selected carrier"
    country = filters.get("country") or "the selected country"
    year = filters.get("year") or "the selected year"

    return (
        f"Theme: {theme_label}. "
        f"For carrier {carrier} in {country} for year {year}, answer this "
        f"SQL-backed insurance analytics question: {question.strip()} "
        "Apply these filters exactly where the relevant table contains matching "
        "columns. If a table cannot support one of the filters, state the evidence "
        "gap instead of inventing facts. Return a concise answer suitable for an "
        "executive pitch report."
    )
```

## 2. Align KPI Premium Field

Problem:

`PitchTopKPIs` uses `total_curr_premium`, while the document builder reads
`total_premium`.

Recommended policy:

- Use `total_curr_premium` everywhere.
- Keep a temporary compatibility read for `total_premium`.

Draft doc-builder compatibility:

```python
premium = top_kpis.get("total_curr_premium") or top_kpis.get("total_premium")
kpis = TopKPIs(
    total_premium=premium,
    yoy=top_kpis.get("yoy"),
    gpr_rank=top_kpis.get("gpr_rank"),
    rank_delta=top_kpis.get("rank_delta"),
    survey_score=top_kpis.get("survey_score"),
)
```

## 3. Re-enable Prompt Size Limits

Problem:

`_json_for_prompt(value, limit=12000)` currently returns the full JSON string.

Draft replacement:

```python
@staticmethod
def _json_for_prompt(value: Any, limit: int = 12000) -> str:
    text = json.dumps(value, indent=2, default=str)
    if len(text) <= limit:
        return text
    return text[: limit - 120].rstrip() + "\n... [truncated for prompt size]"
```

Better long-term approach:

- Summarize SQL rows into compact evidence records.
- Keep full rows in state by evidence id.
- Send only the top rows and summary stats to report-writing prompts.

## 4. Fix Progress Callback Id

Problem:

The real button id is `pitch-generate-report-btn`, while the progress callback
listens to `pitch-generated-report-btn`.

Draft fix:

```python
@callback(
    Output("pitch-progress-interval", "disabled", allow_duplicate=True),
    Output("pitch-progress-fill", "style", allow_duplicate=True),
    Output("pitch-progress-label", "children", allow_duplicate=True),
    Input("pitch-generate-report-btn", "n_clicks"),
    Input("pitch-progress-interval", "n_intervals"),
    prevent_initial_call=True,
)
```

## 5. Add Report Claim Validation

Draft validation function:

```python
def validate_report_claims(summary: str, extracted_insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_text = json.dumps(extracted_insights, default=str).lower()
    claims = split_material_claims(summary)
    results = []
    for claim in claims:
        status = "supported" if key_numbers_in_text(claim, evidence_text) else "review"
        results.append({"claim": claim, "status": status})
    return results
```

This should start advisory-only, then later block unsupported KPI and peer claims.

