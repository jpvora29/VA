# Chart Output Improvement Plan

## Current Problems

- The chart prompt rules over-prefer `line` whenever `Year` is present.
- The renderer lets numeric year columns behave like continuous axes, so Plotly
  can show fractional ticks such as `2024.2`.
- The LLM chart node is allowed to make the final chart decision without enough
  deterministic correction.
- There is no explicit distinction between:
  - temporal trend
  - multi-year category comparison
  - one-year categorical breakdown
  - amount plus rate combo

## Desired Behavior

- Use `line` only for real time progression.
- Use `bar` for category comparison, even when a year column is present.
- Treat `Year` as categorical/integer ticks unless the chart is a true trend.
- Never display fractional years.
- Add a deterministic chart-spec validator that can override bad LLM specs.

## Proposed Deterministic Chart Guard

Add a chart guard before rendering, after `_sanitize_spec()` resolves columns:

```python
YEAR_COLUMNS = {"Year", "Survey_Year", "Policy_Year", "Billing_Year"}
TREND_TERMS = {
    "trend", "over time", "movement", "changed", "change", "yoy",
    "year over year", "month-on-month", "mom", "quarter", "rolling",
    "trajectory", "increase", "decrease", "decline", "growth"
}

def is_year_like(col: str) -> bool:
    normalized = col.strip().lower()
    return normalized == "year" or normalized.endswith("_year") or col in YEAR_COLUMNS

def is_time_like(col: str) -> bool:
    n = col.strip().lower()
    return (
        is_year_like(col)
        or "date" in n
        or "month" in n
        or "quarter" in n
        or "period" in n
    )

def wants_trend(user_query: str, spec_title: str = "") -> bool:
    text = f"{user_query} {spec_title}".lower()
    return any(term in text for term in TREND_TERMS)

def should_line(df: pd.DataFrame, spec: _Spec, user_query: str) -> bool:
    if spec.chart_type != "line":
        return False
    if not is_time_like(spec.x):
        return False
    if df[spec.x].nunique(dropna=True) < 2:
        return False
    if not wants_trend(user_query, spec.title):
        # Years alone are not enough. Multi-year comparison can still be bars.
        return False
    return True
```

Then:

```python
if spec.chart_type == "line" and not should_line(prepared, spec, user_query):
    spec.chart_type = "bar"
```

To support this cleanly, pass `user_query` to `generate_chart()` or include
`intent` in the chart spec.

## Year Tick Fix

In `_apply_theme()` after x-axis updates:

```python
def _is_year_axis(series: pd.Series, name: str) -> bool:
    if name.lower() == "year" or name.lower().endswith("_year"):
        return True
    values = pd.to_numeric(series.dropna(), errors="coerce")
    return (
        len(values) > 0
        and values.notna().all()
        and values.between(1900, 2100).all()
        and (values % 1 == 0).all()
    )

if spec.chart_type in ("bar", "line", "combo") and _is_year_axis(df[spec.x], spec.x):
    years = sorted({int(v) for v in pd.to_numeric(df[spec.x], errors="coerce").dropna()})
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=[str(y) for y in years],
        tickmode="array",
        tickvals=[str(y) for y in years],
        ticktext=[str(y) for y in years],
    )
```

Alternative: convert the prepared frame's year column to string before building
the trace for bar/line/combo:

```python
if _is_year_axis(df[spec.x], spec.x):
    df[spec.x] = pd.to_numeric(df[spec.x], errors="coerce").astype("Int64").astype(str)
```

This is usually the safer Plotly fix because it prevents continuous numeric-axis
inference at trace construction time.

## Prompt Fixes

Update chart skills and legacy chart rules:

- Replace "more than one year -> prefer line" with "more than one year + trend
  intent -> line".
- Add "year comparison by product/carrier/segment -> bar".
- Add examples where `Year` exists but chart type is `bar`.
- Add explicit "no fractional year ticks" rule.

## Recommended Implementation Order

1. Add tests for current failing chart cases.
2. Add deterministic year-axis normalization in renderer.
3. Add deterministic `line` -> `bar` override.
4. Update chart skills and legacy chart prompt rules.
5. Add chart diagnostics logging: original LLM spec, normalized spec, override reason.

