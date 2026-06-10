"""Deterministic chart-spec critic — the pre-render quality gate.

The chart LLM picks chart_type / x / y / series, and it is wrong often enough
that prompt fixes alone don't hold: practices end up as a 15-entry legend while
year sits on the x-axis, identifier columns become series, scatter gets a year
axis (2023.2 ticks), pies get 20 slices. ``ChartSpecCritic.review`` classifies
every DataFrame column by ROLE (temporal / measure-amount / measure-rate /
dimension / identifier / constant) and repairs the raw spec BEFORE the renderer
sanitizes it. Every repair is recorded so the override is observable.

Design rules (mirrors `codex changes/CONTEXTENGINE_FILE_IMPLEMENTATION_PLAN.md`
step 8, df-driven where the registry has no say):

* y carries measures only — junk fields among the measures are dropped, but a
  spec whose ONLY y is a non-measure is left alone so the renderer can reject
  it (a deliberate-garbage spec should fail loudly, not be "fixed" silently).
* The LEGEND gets the smaller dimension, the X-AXIS the larger one. "Premium by
  practice across years" reads as practices on x with 2-3 year colours — never
  a 15-practice legend. Ties go to the temporal column on x; explicit trends
  always put time on x.
* Constants, identifiers and single-valued series are never legends.
* Temporal x on a scatter becomes a line (kills fractional year ticks at the
  source); pies above the slice budget become bars; ranked single-series bars
  sort descending like any BI tool would.

`ui.chart_functions.generate_chart` runs this first, then its existing
sanitize / normalize safety net — the critic narrows, the net catches.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

# ── Shared role vocabulary (chart_functions imports these — keep one source) ──

TREND_TERMS = {
    "trend", "over time", "movement", "moved", "changed", "change", "yoy",
    "year over year", "year-over-year", "month over month", "month-on-month",
    "mom", "qoq", "quarter over quarter", "rolling", "trajectory", "evolution",
    "growth over", "increase", "increasing", "decrease", "decreasing", "decline",
    "declining", "progression", "historical",
}

RATE_HINTS = (
    "sow", "share of wallet", "wallet share", "appetite", "share of portfolio",
    "portfolio share", "growth", "yoy", "%", "pct", "percent", "rate", "ratio",
    "margin", "score", "nps", "share", "penetration", "win rate",
)

MAX_LEGEND_ENTRIES = 8   # a legend larger than this is unreadable
MAX_PIE_SLICES = 8


def norm_key(s: str) -> str:
    return str(s).strip().lower().replace("_", " ").replace("-", " ")


def is_year_like_name(col: str) -> bool:
    n = str(col).strip().lower()
    return n == "year" or n.endswith("_year") or n.endswith(" year")


def is_time_like_name(col: str) -> bool:
    n = str(col).strip().lower()
    return is_year_like_name(col) or any(
        t in n for t in ("date", "month", "quarter", "period", "week")
    )


def is_year_values(series: pd.Series, name: str) -> bool:
    """True when a column should be treated as discrete year ticks."""
    if is_year_like_name(name):
        return True
    values = pd.to_numeric(series.dropna(), errors="coerce")
    return (
        len(values) > 0
        and values.notna().all()
        and values.between(1900, 2100).all()
        and (values % 1 == 0).all()
    )


def looks_like_rate(df: pd.DataFrame, col: str) -> bool:
    """A bounded ratio/percentage/score measure — belongs on a combo line, never
    on the same axis as an absolute amount."""
    if any(h in norm_key(col) for h in RATE_HINTS):
        return True
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return False
    hi = s.abs().max()
    return hi <= 1.0 or (s.between(-100, 100).all() and hi <= 100.0)


def wants_trend(intent: str, title: str) -> bool:
    text = f"{intent} {title}".lower()
    return any(term in text for term in TREND_TERMS)


# ── Column role classification ────────────────────────────────────────────────

#: kinds: temporal | measure_amount | measure_rate | dimension | identifier | constant
@dataclass(frozen=True)
class ColumnRole:
    name: str
    kind: str
    cardinality: int

    @property
    def is_measure(self) -> bool:
        return self.kind in ("measure_amount", "measure_rate")

    @property
    def is_dimension_like(self) -> bool:
        return self.kind in ("dimension", "temporal")


_ID_NAME_SUFFIXES = ("_id", " id", "_uuid", "_key", "_code")


def classify_columns(df: pd.DataFrame) -> Dict[str, ColumnRole]:
    """Role per column, judged from the data itself (registry-free fallback)."""
    roles: Dict[str, ColumnRole] = {}
    n_rows = len(df)
    for col in df.columns:
        s = df[col]
        card = s.nunique(dropna=True)
        name_l = str(col).strip().lower()

        if n_rows > 1 and card <= 1:
            kind = "constant"
        elif pd.api.types.is_datetime64_any_dtype(s):
            kind = "temporal"
        elif is_time_like_name(col):
            kind = "temporal"
        elif pd.api.types.is_numeric_dtype(s) and is_year_values(s, col):
            kind = "temporal"
        elif any(name_l.endswith(suf) for suf in _ID_NAME_SUFFIXES):
            kind = "identifier"
        elif pd.api.types.is_numeric_dtype(s):
            kind = "measure_rate" if looks_like_rate(df, col) else "measure_amount"
        elif n_rows >= 8 and card == n_rows:
            kind = "identifier"  # one distinct value per row — a label, not a grouping
        else:
            kind = "dimension"
        roles[col] = ColumnRole(name=col, kind=kind, cardinality=int(card))
    return roles


# ── The critic ────────────────────────────────────────────────────────────────


def _make_resolver(df: pd.DataFrame) -> Callable[[Optional[str]], Optional[str]]:
    lookup = {norm_key(c): c for c in df.columns}

    def resolve(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        if name in df.columns:
            return name
        return lookup.get(norm_key(name))

    return resolve


class ChartSpecCritic:
    """Review a raw ChartOutput dict against the full result DataFrame.

    `review` returns ``(repaired_spec_dict, reasons)``; the input dict is not
    mutated. It runs BEFORE `_sanitize_spec`, so it sees every column the SQL
    returned (the sanitizer later drops the unreferenced ones).
    """

    def review(
        self, raw: Dict[str, Any], df: pd.DataFrame
    ) -> Tuple[Dict[str, Any], List[str]]:
        spec = dict(raw or {})
        reasons: List[str] = []
        if df is None or df.empty or not spec:
            return spec, reasons
        chart = str(spec.get("chart_type") or "none").strip().lower()
        if chart == "none":
            return spec, reasons

        roles = classify_columns(df)
        resolve = _make_resolver(df)
        intent = str(spec.get("intent") or "")
        title = str(spec.get("title") or "")
        trendy = wants_trend(intent, title)

        def role_of(col: Optional[str]) -> Optional[ColumnRole]:
            return roles.get(col) if col else None

        # ── y: drop junk among the measures (never invent a y from nothing —
        # a spec whose only y is non-numeric should fail in the renderer). ──
        y = [c for c in (resolve(v) for v in spec.get("y") or []) if c]
        y = list(dict.fromkeys(y))
        y_measures = [c for c in y if roles[c].is_measure]
        if y_measures and len(y_measures) < len(y):
            dropped = [c for c in y if c not in y_measures]
            y = y_measures
            reasons.append(f"y-junk-dropped({','.join(dropped)})")
        if not y:
            # Empty y: fill from real measures (amounts before rates). Without
            # this, the renderer's own fallback sweeps EVERY numeric column in —
            # including a numeric Year — and draws nonsense combos.
            measures = [r.name for r in roles.values() if r.kind == "measure_amount"]
            measures += [r.name for r in roles.values() if r.kind == "measure_rate"]
            if measures:
                y = measures[:2]
                reasons.append(f"y-filled-from-measures({','.join(y)})")
        if y:
            spec["y"] = y

        # ── x: must be a real, non-constant, non-identifier column not in y. ──
        x = resolve(spec.get("x"))
        x_role = role_of(x)
        x_bad = (
            x is None
            or (x in y and chart != "scatter")
            or (x_role and x_role.kind in ("constant", "identifier"))
        )
        if x_bad and chart != "scatter":
            candidates = sorted(
                (r for r in roles.values()
                 if r.is_dimension_like and r.name not in y and r.cardinality >= 2),
                key=lambda r: (r.kind != "dimension", r.cardinality),
            )
            if candidates:
                x = candidates[0].name
                spec["x"] = x
                x_role = roles[x]
                reasons.append(f"x-replaced({x})")

        # ── series: reject constants, identifiers, measures, x itself, and
        # single-valued legends (a one-entry legend is noise). ──
        series = [c for c in (resolve(v) for v in spec.get("series") or []) if c]
        series = list(dict.fromkeys(series))
        kept: List[str] = []
        for c in series:
            r = roles[c]
            if c == x or c in y:
                reasons.append(f"series-dropped({c}:duplicates-axis)")
            elif r.kind in ("constant", "identifier"):
                reasons.append(f"series-dropped({c}:{r.kind})")
            elif r.is_measure:
                reasons.append(f"series-dropped({c}:measure)")
            elif r.cardinality <= 1:
                reasons.append(f"series-dropped({c}:redundant-legend)")
            else:
                kept.append(c)
        series = kept

        # ── Missing series detection: x repeats and exactly one small unused
        # dimension explains the duplicates → it was meant to be the legend. ──
        if (
            not series
            and x in df.columns
            and chart in ("bar", "line", "combo")
            and str(spec.get("y_agg") or "none").lower() == "none"
            and df.duplicated(subset=[x]).any()
        ):
            explainers = [
                r for r in roles.values()
                if r.is_dimension_like and r.name != x and r.name not in y
                and 2 <= r.cardinality <= MAX_LEGEND_ENTRIES
                and df.groupby([x, r.name], dropna=False).ngroups
                > df[x].nunique(dropna=True)
            ]
            if len(explainers) == 1:
                series = [explainers[0].name]
                reasons.append(f"series-from-duplicates({explainers[0].name})")

        # ── Orientation: the legend gets the SMALLER dimension. ──
        if x and series and chart in ("bar", "line", "combo"):
            s0 = series[0]
            cx = roles[x].cardinality
            cs = roles[s0].cardinality
            x_is_time = roles[x].kind == "temporal"
            s_is_time = roles[s0].kind == "temporal"
            if (trendy or chart == "line") and s_is_time and not x_is_time:
                # A trend must have time on x, whatever the cardinalities.
                series[0], x = x, s0
                spec["x"], spec["series"] = x, series
                reasons.append("trend→time-on-x")
            elif cs > cx and not (trendy or chart == "line"):
                # e.g. 15 practices in the legend vs 3 years on x → swap.
                series[0], x = x, s0
                spec["x"], spec["series"] = x, series
                reasons.append(f"legend↔x (smaller dim to legend: {series[0]})")
            elif cs == cx and s_is_time and not x_is_time and not trendy:
                series[0], x = x, s0
                spec["x"], spec["series"] = x, series
                reasons.append("tie→time-on-x")
        spec["series"] = series

        # ── Chart-type repairs. ──
        x_role = role_of(x)
        if chart == "scatter" and x_role is not None and x_role.kind == "temporal":
            chart = "line"
            reasons.append("scatter+time-x→line")
        if chart in ("pie", "donut"):
            slices = roles[x].cardinality if x in roles else 0
            if series or len(y) > 1 or slices > MAX_PIE_SLICES:
                chart = "bar"
                reasons.append("pie→bar (too many slices/series)")
        if chart != str(spec.get("chart_type") or "").strip().lower():
            spec["chart_type"] = chart

        # ── Ranked bars: a single-series categorical bar sorts descending. ──
        if (
            chart == "bar"
            and not series
            and len(y) == 1
            and x_role is not None
            and x_role.kind == "dimension"
            and str(spec.get("sort") or "none").lower() == "none"
            and x_role.cardinality > 2
        ):
            spec["sort"] = "desc"
            reasons.append("ranked-bars(desc)")

        return spec, reasons
