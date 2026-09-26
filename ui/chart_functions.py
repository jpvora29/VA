"""Chart rendering engine for Virtual Analyst.

`generate_chart(df, spec)` turns a `ChartOutput` (the spec the chart LLM emits)
plus the SQL rows into a polished Plotly figure. It is the single rendering path
for BOTH the deterministic survey/GPR subgraph chart nodes and the analyst
agent's chart-picker.

Design goals
------------
* **Robust on complex queries.** The LLM's column picks are never trusted blindly.
  `_sanitize_spec` reconciles every referenced column against the actual DataFrame
  (case / underscore-insensitive), coerces measures to numeric, aggregates
  duplicate rows, caps high-cardinality series, and degrades gracefully instead
  of raising. A bad spec yields `(None, message)`, never an exception.
* **Rich chart vocabulary.** bar (grouped/stacked), line, scatter, pie, donut,
  waterfall, and combo (bars + a secondary-axis line) — each a registered builder.
* **Beautiful, consistent theme.** One `_apply_theme` gives every chart the same
  clean, Claude-like look (brand colourway, soft gridlines, unified hover).
"""
from __future__ import annotations

import re

from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go

from ui.color_pallet import ColorPalette
from core.charts.critic import ChartSpecCritic, is_year_values as _is_year_axis
from core.observability import log_event
from logger import get_logger

logger = get_logger(__name__)

# ── Tunables ────────────────────────────────────────────────────────────────
MAX_SERIES = 12          # distinct legend entries before we bucket the tail
MAX_PIE_SLICES = 8       # pie/donut readability ceiling
MAX_TITLE_LEN = 64       # one-line title budget before truncation
MAX_TICK_LEN = 16        # category label length before we slant the axis
_AGGS = {"sum", "mean", "count", "median", "min", "max"}

# The ONE deterministic spec-repair pass. It runs before sanitization, against
# the full result frame, and decides chart type, axes and legend — see
# `core.charts.critic`. This module draws what it is given.
_CRITIC = ChartSpecCritic()

# ── Registry ──────────────────────────────────────────────────────────────────
_TRACE_REGISTRY: Dict[str, Callable] = {}


def chart_type(name: str):
    """Register a trace-builder under a chart-type name."""

    def decorator(fn: Callable):
        _TRACE_REGISTRY[name] = fn

        @wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ── Normalized spec ───────────────────────────────────────────────────────────


@dataclass
class _Spec:
    """The chart spec AFTER reconciliation against the DataFrame.

    Every column name here is guaranteed to exist in the (prepared) DataFrame.
    """

    chart_type: str
    x: str
    y: List[str]
    series: List[str] = field(default_factory=list)
    bar_mode: List[str] = field(default_factory=list)
    secondary_y: List[str] = field(default_factory=list)
    waterfall_measures: List[str] = field(default_factory=list)
    is_legend: bool = True
    y_agg: str = "none"
    sort: str = "none"
    title: str = ""
    intent: str = ""  # original user query, stamped by core.agents.common.chart_spec
    # Explicit axis titles. A chart whose series ARE the comparison — one column
    # per year — has a y-axis reading "2024, 2025", which names the series rather
    # than the measure and tells the reader nothing. A spec that knows its
    # measure says so; every other chart keeps deriving the label from columns.
    x_title: str = ""
    y_title: str = ""
    #: Drawn as horizontal bars: a long ranking of named categories reads down a
    #: page, not across it (see `_wants_horizontal`). Decided after sanitizing.
    horizontal: bool = False


def _as_dict(spec: Any) -> Dict[str, Any]:
    """Accept a ChartOutput pydantic model, a plain dict, or a legacy object."""
    if spec is None:
        return {}
    # The analyst/chart nodes are contracted to one spec, but a list can slip
    # through (e.g. the LLM emitting multiple charts in one field). Unwrap to the
    # first usable element rather than scraping it to {} and degrading to scalar.
    if isinstance(spec, (list, tuple)):
        spec = next((s for s in spec if s), None)
        if spec is None:
            return {}
    if isinstance(spec, dict):
        return dict(spec)
    # pydantic v1/v2 model
    for attr in ("model_dump", "dict"):
        fn = getattr(spec, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                pass
    # Fall back to a best-effort attribute scrape.
    return {
        k: getattr(spec, k)
        for k in (
            "chart_type", "x", "y", "series", "bar_mode", "secondary_y",
            "waterfall_measures", "is_legend", "y_agg", "sort", "title",
        )
        if hasattr(spec, k)
    }


#: What an unlabelled slice is called on an axis. Naming it keeps its premium
#: in the chart; dropping the row would quietly change the total the chart shows.
UNLABELLED = "Not specified"


def label_unlabelled(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """`column`'s blanks given a visible name, for a non-numeric axis.

    Numeric axes are left alone: "Not specified" is not a year, and a missing
    number on a numeric axis has no position to be drawn at.
    """
    if column not in df.columns or pd.api.types.is_numeric_dtype(df[column]):
        return df
    blank = df[column].isna() | (df[column].astype(str).str.strip() == "")
    if not blank.any():
        return df
    df = df.copy()
    df.loc[blank, column] = UNLABELLED
    return df


def _pretty(name: str) -> str:
    """Human label for a column/title: underscores → spaces, gentle title-casing
    that preserves acronyms (FINPRO, NPS, YoY)."""
    text = str(name).replace("_", " ").strip()
    return " ".join(w if (w.isupper() or any(c.isdigit() for c in w)) else w.capitalize()
                     for w in text.split())


# ── Sanitization ────────────────────────────────────────────────────────────


def _norm_key(s: str) -> str:
    return str(s).strip().lower().replace("_", " ").replace("-", " ")


def _resolver(df: pd.DataFrame) -> Callable[[Optional[str]], Optional[str]]:
    """Return a function mapping a loosely-spelled column to the real df column."""
    lookup = {_norm_key(c): c for c in df.columns}

    def resolve(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        if name in df.columns:
            return name
        return lookup.get(_norm_key(name))

    return resolve


def _is_numeric(df: pd.DataFrame, col: str) -> bool:
    return pd.api.types.is_numeric_dtype(df[col])


def _no_chart_reason(df: pd.DataFrame) -> str:
    """Why this result has no chart, stated about THIS result.

    A single value has no chart and saying so is useful. Anything wider does have
    a shape, so the honest line is that none was drawn — and the panel shows the
    rows, which is the evidence either way.
    """
    if df.shape == (1, 1):
        return "Chart can not be generated as the data is scalar."
    return "Underlying data"


def _sanitize_spec(
    df: pd.DataFrame, raw: Dict[str, Any]
) -> Tuple[Optional[_Spec], pd.DataFrame, str]:
    """Reconcile the raw spec against `df`. Returns (spec, prepared_df, message).

    `spec is None` means "do not draw" — `message` explains why (e.g. scalar).
    Never raises.
    """
    if df is None or df.empty:
        return None, df, "No data to chart."

    # "No chart type" means no chart was designed for this result — which is only
    # ever ABOUT the data when the data really is a single value. Saying "the data
    # is scalar" over a full result set was a lie the reader could see through, so
    # the message now describes the frame in front of us.
    chart = str(raw.get("chart_type") or "none").strip().lower()
    if chart == "none":
        return None, df, _no_chart_reason(df)

    resolve = _resolver(df)

    def resolve_list(values: Any) -> List[str]:
        out: List[str] = []
        for v in values or []:
            col = resolve(v)
            if col and col not in out:
                out.append(col)
        return out

    # ── Resolve measures (y) ──────────────────────────────────────────────
    y = resolve_list(raw.get("y"))
    # Coerce candidate measures to numeric; keep only those with real numbers.
    df = df.copy()
    numeric_cols = [c for c in df.columns if _is_numeric(df, c)]
    if not y:
        # Fall back to the numeric columns the LLM didn't name — but never a
        # year-like column (2023 is an axis label, not a measure).
        y = [c for c in numeric_cols if not _is_year_axis(df[c], c)] or list(numeric_cols)
    cleaned_y: List[str] = []
    for col in y:
        if not _is_numeric(df, col):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[col].notna().any():
            cleaned_y.append(col)
    y = cleaned_y
    if not y:
        return None, df, "No numeric measure available to plot."

    # ── Resolve x ─────────────────────────────────────────────────────────
    x = resolve(raw.get("x"))
    if chart == "scatter":
        # Scatter needs a numeric x; fall back to the first numeric not in y.
        if x is None or not _is_numeric(df, x):
            spare = [c for c in df.columns if _is_numeric(df, c) and c not in y]
            x = spare[0] if spare else (y[0] if len(y) > 1 else None)
    if x is None:
        # Prefer a non-measure (categorical / time) column for the axis.
        cat = [c for c in df.columns if c not in y]
        x = cat[0] if cat else df.columns[0]

    # ── Resolve series (exclude x and y) ──────────────────────────────────
    series = [c for c in resolve_list(raw.get("series")) if c != x and c not in y]

    # ── Combo: split bars (y) vs secondary-axis lines ─────────────────────
    secondary_y = [c for c in resolve_list(raw.get("secondary_y")) if c in df.columns]
    for c in secondary_y:  # ensure numeric
        if not _is_numeric(df, c):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    secondary_y = [c for c in secondary_y if df[c].notna().any()]
    if chart == "combo":
        secondary_y = [c for c in secondary_y if c not in y] or (
            [y.pop()] if len(y) >= 2 else []
        )
        if not secondary_y:
            chart = "bar"  # nothing to put on the second axis → plain bars

    spec = _Spec(
        chart_type=chart,
        x=x,
        y=y,
        series=series,
        bar_mode=[str(b).strip().lower() for b in (raw.get("bar_mode") or [])],
        secondary_y=secondary_y,
        waterfall_measures=[str(m).strip().lower() for m in (raw.get("waterfall_measures") or [])],
        is_legend=bool(raw.get("is_legend", True)),
        y_agg=str(raw.get("y_agg") or "none").strip().lower(),
        sort=str(raw.get("sort") or "none").strip().lower(),
        title=str(raw.get("title") or ""),
        intent=str(raw.get("intent") or ""),
        x_title=str(raw.get("x_title") or ""),
        y_title=str(raw.get("y_title") or ""),
    )

    df = _prepare_frame(df, spec)
    return spec, df, "Successful"


def _prepare_frame(df: pd.DataFrame, spec: _Spec) -> pd.DataFrame:
    """Aggregate duplicates, cap series cardinality, and sort — in that order."""
    keep = [c for c in ([spec.x] + spec.series + spec.y + spec.secondary_y) if c]
    keep = list(dict.fromkeys(keep))  # de-dup, preserve order
    df = df[keep].copy()

    measures = spec.y + spec.secondary_y
    group_cols = [c for c in ([spec.x] + spec.series) if c]

    # Aggregate when multiple rows share the same x/series key.
    if group_cols and df.duplicated(subset=group_cols).any():
        if spec.y_agg not in _AGGS:
            raise ValueError("Chart dimensions do not uniquely identify rows; choose a more detailed axis or calculate the intended aggregation first.")
        if spec.y_agg == "sum" and any(re.search(r"score|nps|rank|share|pct|percent|rate|%", c, re.I) for c in measures):
            raise ValueError("Scores, ranks and percentages cannot be summed across chart rows.")
        agg = spec.y_agg
        df = df.groupby(group_cols, dropna=False, as_index=False)[measures].agg(agg)

    # Cap high-cardinality series: keep the top (MAX_SERIES-1) by total measure,
    # bucket the rest as "Other", so the legend stays readable.
    for s in spec.series:
        if df[s].nunique(dropna=False) > MAX_SERIES:
            if spec.y_agg not in _AGGS or any(re.search(r"score|nps|rank|share|pct|percent|rate|%", c, re.I) for c in measures):
                raise ValueError("Too many series to chart without changing the meaning of the measures. Narrow the scope.")
            ranked = (
                df.groupby(s, dropna=False)[spec.y[0]].sum().sort_values(ascending=False)
            )
            top = set(ranked.head(MAX_SERIES - 1).index)
            df[s] = df[s].where(df[s].isin(top), other="Other")
            df = df.groupby(
                [c for c in ([spec.x] + spec.series) if c], dropna=False, as_index=False
            )[measures].agg(spec.y_agg if spec.y_agg in _AGGS else "sum")

    # Sort the x axis by the first measure when asked.
    if spec.sort in ("asc", "desc") and spec.x in df.columns:
        # A null in the axis column is real data — a slice the warehouse did not
        # label — so it is NAMED rather than dropped. It also has to be named
        # before the sort: `groupby(dropna=False)` puts NaN in the index, which
        # becomes a null category, and pandas rejects those outright
        # ("Categorical categories cannot be null"). One unlabelled row was
        # taking the whole chart down.
        df = label_unlabelled(df, spec.x)
        order = (
            df.groupby(spec.x, dropna=False)[spec.y[0]].sum()
            .sort_values(ascending=spec.sort == "asc").index
        )
        categories = [value for value in order if pd.notna(value)]
        if categories:
            df[spec.x] = pd.Categorical(df[spec.x], categories=categories, ordered=True)
            df = df.sort_values(spec.x)

    return df.reset_index(drop=True)


# ── Axis ticks ────────────────────────────────────────────────────────────────
#
# What a chart's TYPE and axes should be is decided once, by `ChartSpecCritic`,
# before this module sees the spec — it classifies every column by role and
# repairs the model's picks there. This module used to run a second, overlapping
# guard of its own after column reconciliation, which meant two rule sets, two
# sets of override reasons, and six private heuristics imported across the
# boundary to keep the two judging columns identically.
#
# What is left here is the one correction that is genuinely about DRAWING rather
# than about the spec: a numeric year axis has to become discrete category ticks,
# or plotly renders 2024.2 between the bars. It changes the frame, not the spec.


def _prepare_axis_ticks(
    df: pd.DataFrame, spec: _Spec
) -> Tuple[pd.DataFrame, List[str]]:
    """Discrete, ascending year ticks. Returns (df, reasons)."""
    reasons: List[str] = []
    if spec.chart_type in ("bar", "line", "combo") and spec.x in df and _is_year_axis(
        df[spec.x], spec.x
    ):
        years = pd.to_numeric(df[spec.x], errors="coerce")
        if years.notna().any():
            df = df.copy()
            df[spec.x] = years.astype("Int64").astype(str)
            order = sorted(
                {int(v) for v in years.dropna()},
            )
            categories = [str(y) for y in order]
            if categories:
                df[spec.x] = pd.Categorical(
                    df[spec.x], categories=categories, ordered=True
                )
            df = df.sort_values(spec.x).reset_index(drop=True)
            reasons.append("year→categorical")

    return df, reasons


def _clean_title(spec: _Spec) -> str:
    """One-line, length-capped title. Synthesize a concise one if missing/too long."""
    title = (spec.title or "").strip().replace("\n", " ")
    if not title or len(title) > MAX_TITLE_LEN:
        measure = ", ".join(_pretty(c) for c in (spec.y + spec.secondary_y)[:2])
        dim = _pretty(spec.x) if spec.x else ""
        synthesized = f"{measure} by {dim}" if measure and dim else measure or title
        if synthesized:
            title = synthesized
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 1].rsplit(" ", 1)[0] + "…"
    return title


def _series_key(df: pd.DataFrame, series: List[str]) -> Optional[pd.Series]:
    """Composite legend label across one or more series columns ("A | B")."""
    if not series:
        return None
    parts = [df[s].astype(str) for s in series]
    key = parts[0]
    for p in parts[1:]:
        key = key.str.cat(p, sep=" | ")
    return key


# ── Builders ──────────────────────────────────────────────────────────────────


@chart_type("bar")
def _build_bar(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    stacked = "stack" in spec.bar_mode
    key = _series_key(df, spec.series)
    if spec.horizontal and key is None and len(spec.y) == 1:
        ordered = df.sort_values(spec.y[0], ascending=True)
        fig.add_trace(
            go.Bar(
                y=ordered[spec.x].astype(str), x=ordered[spec.y[0]], orientation="h",
                name=_pretty(spec.y[0]), marker_color=CURRENT_COLOR,
            )
        )
        fig.update_layout(barmode="group")
        return
    if key is not None:
        names = _ordered_unique(key)
        colors = semantic_colors([str(v) for v in names])
        for i, val in enumerate(names):
            sub = df[key == val]
            fig.add_trace(
                go.Bar(
                    x=sub[spec.x], y=sub[spec.y[0]], name=_pretty(val),
                    marker_color=color_map.setdefault(val, colors[i]),
                )
            )
    else:
        colors = semantic_colors(list(spec.y))
        for i, ycol in enumerate(spec.y):
            fig.add_trace(
                go.Bar(
                    x=df[spec.x], y=df[ycol], name=_pretty(ycol),
                    marker_color=colors[i],
                )
            )
    fig.update_layout(barmode="stack" if stacked else "group")


@chart_type("line")
def _build_line(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    key = _series_key(df, spec.series)
    if key is not None:
        names = _ordered_unique(key)
        colors = semantic_colors([str(v) for v in names])
        for i, val in enumerate(names):
            sub = df[key == val]
            fig.add_trace(
                go.Scatter(
                    x=sub[spec.x], y=sub[spec.y[0]], mode="lines+markers",
                    name=_pretty(val),
                    line=dict(color=color_map.setdefault(val, colors[i]), width=2.5,
                              shape="spline", smoothing=0.4),
                    marker=dict(size=7, line=dict(color="white", width=1.5)),
                )
            )
    else:
        colors = semantic_colors(list(spec.y))
        for i, ycol in enumerate(spec.y):
            fig.add_trace(
                go.Scatter(
                    x=df[spec.x], y=df[ycol], mode="lines+markers", name=_pretty(ycol),
                    line=dict(color=colors[i], width=2.5, shape="spline", smoothing=0.4),
                    marker=dict(size=7, line=dict(color="white", width=1.5)),
                    # A single measure over time reads better with the area under
                    # it faintly filled: the eye follows a shape, not a thread.
                    fill="tozeroy" if len(spec.y) == 1 else None,
                    fillcolor="rgba(11, 75, 255, 0.07)" if len(spec.y) == 1 else None,
                )
            )


@chart_type("scatter")
def _build_scatter(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    ycol = spec.y[0]
    key = _series_key(df, spec.series)
    if key is not None:
        for i, val in enumerate(_ordered_unique(key)):
            sub = df[key == val]
            fig.add_trace(
                go.Scatter(
                    x=sub[spec.x], y=sub[ycol], mode="markers", name=_pretty(val),
                    marker=dict(size=10, color=color_map.setdefault(val, ColorPalette.color_for(i))),
                )
            )
    else:
        fig.add_trace(
            go.Scatter(
                x=df[spec.x], y=df[ycol], mode="markers",
                marker=dict(size=10, color=ColorPalette.color_for(0)), showlegend=False,
            )
        )
    fig.update_layout(xaxis=dict(type="linear"))


@chart_type("pie")
def _build_pie(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    _pie(fig, df, spec, hole=0.0)


@chart_type("donut")
def _build_donut(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    _pie(fig, df, spec, hole=0.55)


def _pie(fig: go.Figure, df: pd.DataFrame, spec: _Spec, *, hole: float) -> None:
    ycol = spec.y[0]
    grouped = df.groupby(spec.x, dropna=False, as_index=False)[ycol].sum()
    grouped = grouped.sort_values(ycol, ascending=False)
    # Collapse the long tail so the donut stays legible.
    if len(grouped) > MAX_PIE_SLICES:
        head = grouped.head(MAX_PIE_SLICES - 1)
        other = pd.DataFrame({spec.x: ["Other"], ycol: [grouped[ycol].iloc[MAX_PIE_SLICES - 1:].sum()]})
        grouped = pd.concat([head, other], ignore_index=True)
    labels = [_pretty(v) for v in grouped[spec.x]]
    fig.add_trace(
        go.Pie(
            labels=labels, values=grouped[ycol], hole=hole, sort=False,
            marker=dict(colors=ColorPalette.sequential(len(grouped)),
                        line=dict(color="white", width=1.5)),
            textinfo="label+percent", textposition="outside",
        )
    )
    if hole > 0:
        total = grouped[ycol].sum()
        fig.add_annotation(
            text=f"<b>{_format_number(total)}</b><br>{_pretty(ycol)}",
            x=0.5, y=0.5, showarrow=False, font=dict(size=15, color="#001538"),
        )


@chart_type("waterfall")
def _build_waterfall(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    ycol = spec.y[0]
    grouped = df.groupby(spec.x, dropna=False, as_index=False)[ycol].sum()
    labels = [_pretty(v) for v in grouped[spec.x]]
    values = list(grouped[ycol])
    n = len(values)
    measures = spec.waterfall_measures[:n]
    if len(measures) < n:
        measures += ["relative"] * (n - len(measures))
    measures = [m if m in ("relative", "total", "absolute") else "relative" for m in measures]
    unit = measure_unit(spec)
    text = [format_value(v, unit, signed=True) for v in values]
    # If the spec gave no explicit total, close the series with the NET of the
    # movements. Its value is plotly's to compute (a `total` bar ignores its y),
    # but its LABEL is ours — it used to print the placeholder 0 as "0.00".
    if "total" not in measures and "absolute" not in measures:
        net = sum(_number_or(v, 0.0) for v in values)
        labels.append("Net change")
        values.append(0)
        measures.append("total")
        text.append(format_value(net, unit, signed=True))
    fig.add_trace(
        go.Waterfall(
            x=labels, y=values, measure=measures,
            connector=dict(line=dict(color="#C7CFDB", width=1, dash="dot")),
            increasing=dict(marker=dict(color=GOOD_COLOR)),
            decreasing=dict(marker=dict(color=BAD_COLOR)),
            totals=dict(marker=dict(color=CURRENT_COLOR)),
            text=text, textposition="outside", cliponaxis=False,
            textfont=dict(size=11, color=_INK),
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)


@chart_type("combo")
def _build_combo(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    # Bars (primary axis) for the absolute measures in y.
    for i, ycol in enumerate(spec.y):
        fig.add_trace(
            go.Bar(x=df[spec.x], y=df[ycol], name=_pretty(ycol),
                   marker_color=ColorPalette.color_for(i))
        )
    # Lines (secondary axis) for the rate/percentage measures.
    for j, ycol in enumerate(spec.secondary_y):
        fig.add_trace(
            go.Scatter(
                x=df[spec.x], y=df[ycol], name=_pretty(ycol), mode="lines+markers",
                yaxis="y2",
                line=dict(color=ColorPalette.yellow[0] if j == 0 else ColorPalette.color_for(j + len(spec.y)), width=3),
                marker=dict(size=7),
            )
        )
    fig.update_layout(
        barmode="group",
        yaxis2=dict(
            title=", ".join(_pretty(c) for c in spec.secondary_y),
            overlaying="y", side="right", showgrid=False, zeroline=False,
        ),
    )


def _ordered_unique(s: pd.Series) -> List[Any]:
    seen: set = set()
    out: List[Any] = []
    for v in s:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _format_number(v: float) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.1f}{suffix}"
    return f"{v:,.0f}" if abs(v) >= 1 else f"{v:.2f}"


# ── Units: what a chart's numbers ARE ─────────────────────────────────────────
#
# A premium axis reading "300" and a share axis reading "41" look identical, and
# the reader has to find the title to learn one is dollars and the other percent.
# The unit is read once from the spec's measure names and axis title, and every
# label, tick and tooltip on the chart states it.

_PCT_RX = re.compile(r"%|\bpct\b|percent|share|\brate\b|\byoy\b|growth\s*%|margin", re.I)
_MONEY_RX = re.compile(r"premium|\bgwp\b|amount|revenue|spend|wallet\s*size|change vs prior|\$", re.I)
_SCORE_RX = re.compile(r"score|nps|index|rating|rank", re.I)


def measure_unit(spec: "_Spec") -> str:
    """"pct", "money" or "" for the chart's primary measure. Pure."""
    names = " ".join([spec.y_title or "", *[str(c) for c in spec.y]])
    if _SCORE_RX.search(names):
        return ""
    if _PCT_RX.search(names):
        return "pct"
    if _MONEY_RX.search(names):
        return "money"
    return ""


def format_value(v: Any, unit: str = "", *, signed: bool = False) -> str:
    """One number the way the chart states it: "$1.2M", "+$60", "41.0%"."""
    try:
        number = float(v)
    except (TypeError, ValueError):
        return str(v)
    sign = ""
    if number < 0:
        sign = "-"
    elif signed and number > 0:
        sign = "+"
    size = abs(number)
    if unit == "pct":
        return f"{sign}{size:.1f}%"
    body = _format_number(size)
    return f"{sign}${body}" if unit == "money" else f"{sign}{body}"


# ── Colour meaning ────────────────────────────────────────────────────────────
#
# Colour carries meaning before a label is read: the period being reported is
# the strong brand blue and earlier periods step back into muted blue-greys; a
# benchmark (the Marsh book, the market, the peer average) is muted beside the
# subject it frames. Anything else takes the categorical brand order.

CURRENT_COLOR = "#0B4BFF"
PRIOR_COLORS = ("#9FB3CF", "#C5D3E6", "#DCE5F1")
BENCHMARK_COLOR = "#B7C6DB"
GOOD_COLOR = "#1F9D55"
BAD_COLOR = "#D64545"
_YEAR_RX = re.compile(r"^(19|20)\d{2}$")
_BENCHMARK_RX = re.compile(r"marsh|market|peer|book|average|benchmark|total", re.I)


def semantic_colors(names: List[str]) -> List[str]:
    """One colour per series name, by what the series IS. Pure."""
    names = [str(n).strip() for n in names]
    if len(names) == 1:
        return [CURRENT_COLOR]
    if len(names) >= 2 and all(_YEAR_RX.match(n) for n in names):
        order = sorted(names)
        latest = order[-1]
        priors = [n for n in reversed(order) if n != latest]
        shade = {n: PRIOR_COLORS[min(i, len(PRIOR_COLORS) - 1)] for i, n in enumerate(priors)}
        shade[latest] = CURRENT_COLOR
        return [shade[n] for n in names]
    if len(names) == 2:
        bench = [bool(_BENCHMARK_RX.search(n)) for n in names]
        if bench.count(True) == 1:
            return [BENCHMARK_COLOR if b else CURRENT_COLOR for b in bench]
    return [ColorPalette.color_for(i) for i in range(len(names))]


def _wants_horizontal(df: pd.DataFrame, spec: "_Spec") -> bool:
    """A single-measure ranking of many (or long-named) categories reads DOWN.

    Vertical bars with slanted labels are the default look of a chart nobody
    designed. Time is never turned on its side — periods read left to right.
    """
    if spec.chart_type != "bar" or spec.series or len(spec.y) != 1:
        return False
    if spec.x not in df.columns or _is_numeric(df, spec.x) or _is_year_axis(df[spec.x], spec.x):
        return False
    if re.search(r"quarter|month|year|period|date|week", spec.x, re.I):
        return False
    labels = df[spec.x].astype(str)
    count = labels.nunique()
    return count >= 7 or (count >= 3 and labels.map(len).max() > MAX_TICK_LEN)


# ── Theme ─────────────────────────────────────────────────────────────────────

_FONT_FAMILY = "Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
_INK = "#1B222F"
_TITLE_INK = "#001538"
_GRID = "#EEF2F7"
_AXIS_LINE = "#D1E0EC"
# Darker than the grid: the zero line is a reference, not another gridline.
_ZERO_LINE = "#9AA9BF"
# Tick labels sit a step back from the body text: they are reference, not
# content, and at full ink they compete with the bars for attention.
_TICK_INK = "#5A6B82"


def _apply_theme(fig: go.Figure, spec: _Spec, df: pd.DataFrame) -> None:
    """Apply the shared, BI-dashboard visual style to any figure."""
    is_polar = spec.chart_type in ("pie", "donut")
    multi = (
        spec.is_legend
        and spec.chart_type not in ("pie", "donut", "waterfall")
        and (bool(spec.series) or len(spec.y) + len(spec.secondary_y) > 1)
    )

    # Title and legend both live in the top margin. The old fixed t=72 made them
    # collide whenever the legend wrapped; reserve the margin from the ACTUAL
    # legend entry count instead (≈4 entries per row), and let the title manage
    # its own band with automargin.
    n_legend = (
        sum(1 for t in fig.data if t.type != "pie" and getattr(t, "showlegend", None) is not False)
        if multi
        else 0
    )
    legend_rows = min(3, -(-n_legend // 4)) if n_legend else 0
    top_margin = 56 + 22 * legend_rows

    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=_clean_title(spec),
            x=0.02, xanchor="left",
            y=1.0, yanchor="top", yref="container",
            pad=dict(t=12),
            automargin=True,
            font=dict(size=14.5, color=_TITLE_INK, family=_FONT_FAMILY,
                      weight=600),
        ),
        font=dict(family=_FONT_FAMILY, size=12.5, color=_INK),
        paper_bgcolor="white",
        plot_bgcolor="white",
        # The y-axis carries `automargin`, so a fixed 64px left margin was
        # padding already-reserved space — the plot sat in the middle of the card
        # with a gutter down the left. Let the axis ask for what it needs.
        margin=dict(l=8, r=48 if spec.chart_type == "combo" else 24, t=top_margin, b=48),
        colorway=ColorPalette.get_colors(),
        # Wider gaps: bars that nearly touch read as a single mass. The grouped
        # pair stays tight so the two years read as one comparison.
        bargap=_bar_gap(df, spec),
        bargroupgap=0.08,
        showlegend=multi,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
            font=dict(size=11), title=None,
            # A legend sitting directly on the plot edge reads as a label of the
            # topmost bar. Half a line of air separates it from the data.
            itemsizing="constant", itemwidth=30,
        ),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family=_FONT_FAMILY,
                        bordercolor=_AXIS_LINE, namelength=-1),
        # A uniform gap between the tallest bar and the plot top, so a chart with
        # outside value labels does not clip them and one without does not float.
        uniformtext=dict(minsize=9, mode="hide"),
    )
    # Rounded bar corners (Plotly ≥5.18 / 6.x).
    if spec.chart_type in ("bar", "combo"):
        try:
            fig.update_layout(barcornerradius=6)
        except Exception:  # noqa: BLE001 - older plotly: harmless to skip
            pass

    if spec.horizontal:
        _style_horizontal(fig, spec, df)
        return

    if not is_polar:
        # Slant long category labels so they stay on ONE line instead of letting
        # Plotly wrap them across two; numeric/short axes stay horizontal.
        tickangle = 0
        if spec.x in df.columns and not _is_numeric(df, spec.x):
            longest = df[spec.x].astype(str).map(len).max() if len(df) else 0
            many = df[spec.x].nunique(dropna=True) > 6
            if longest and (longest > MAX_TICK_LEN or many):
                tickangle = -30
        fig.update_xaxes(
            title=dict(text=spec.x_title or _pretty(spec.x),
                       font=dict(size=12, color="#5A6B82")),
            showgrid=False, showline=True, linecolor=_AXIS_LINE, linewidth=1,
            ticks="", tickfont=dict(size=11, color=_TICK_INK),
            tickangle=tickangle, automargin=True,
        )
        ytitle = spec.y_title or ", ".join(_pretty(c) for c in spec.y)
        # A chart whose bars cross zero needs the zero line drawn, or a decline
        # and a small gain look like the same thing pointing different ways.
        # On an all-positive chart the baseline IS the axis and a second rule
        # there is clutter, so it is drawn only when the data actually spans
        # both signs — which is exactly the quarterly-change case.
        crosses_zero = _spans_zero(df, spec.y)
        show_zero_line = _needs_zero_line(df, spec.y)
        fig.update_yaxes(
            title=dict(text=ytitle, font=dict(size=12, color="#5A6B82")),
            showgrid=True, gridcolor=_GRID, gridwidth=1, griddash="dot",
            zeroline=show_zero_line, zerolinecolor=_ZERO_LINE, zerolinewidth=1.5,
            showline=False, ticks="", tickfont=dict(size=11, color=_TICK_INK),
            automargin=True,
        )
        # Large amounts get SI-abbreviated ticks (1.2M, 60K) like any BI tool —
        # never six-digit tick labels.
        try:
            max_y = max(
                (pd.to_numeric(df[c], errors="coerce").abs().max() or 0)
                for c in spec.y
                if c in df.columns
            )
        except ValueError:
            max_y = 0
        if max_y and max_y >= 10_000:
            fig.update_yaxes(tickformat="~s")
        unit = measure_unit(spec)
        if unit == "money":
            fig.update_yaxes(tickprefix="$")
        elif unit == "pct":
            fig.update_yaxes(ticksuffix="%")
        if spec.chart_type in ("bar", "line", "combo"):
            _unit_hover(fig, unit)

        # Direct value labels on small single-series bars (the Tableau look).
        if (
            spec.chart_type == "bar"
            and len(fig.data) == 1
            and spec.x in df.columns
            and df[spec.x].nunique(dropna=True) <= 8
        ):
            bar = fig.data[0]
            bar.text = [format_value(v, measure_unit(spec)) for v in bar.y]
            bar.textposition = "outside"
            bar.cliponaxis = False
            bar.textfont = dict(size=10.5, color=_INK)
            # Colour a signed single series by direction. One brand-blue bar for
            # a -135 and another for a +90 makes the reader decode the axis to
            # see which way each went; green and red say it before they read a
            # single number. Only for a MIXED series — colouring an all-negative
            # chart red adds no information and reads as alarm.
            if crosses_zero:
                # `bar.y` is a numpy array here, so `bar.y or []` raises
                # "truth value of an array is ambiguous" — an explicit None
                # check is the only safe emptiness test on a trace value.
                values = [] if bar.y is None else list(bar.y)
                bar.marker.color = [
                    ColorPalette.negative if _number_or(v, 0.0) < 0 else ColorPalette.positive
                    for v in values
                ]

        if spec.chart_type not in ("scatter",):
            fig.update_layout(hovermode="x unified")



def _bar_gap(df: pd.DataFrame, spec: "_Spec") -> float:
    """Gap between bar groups, by how many there are.

    With one or two categories a fixed gap draws two slabs that fill the card —
    the quarterly chart with a single comparable quarter looked like a wall.
    """
    try:
        count = int(df[spec.x].nunique()) if spec.x in df.columns else 0
    except Exception:  # noqa: BLE001
        count = 0
    if count and count <= 2:
        return 0.62
    if count and count <= 4:
        return 0.45
    return 0.34


def _unit_hover(fig: go.Figure, unit: str) -> None:
    """Tooltips that state the unit: "$1.24M", "41.0%"."""
    body = {"money": "$%{y:,.3~s}", "pct": "%{y:.1f}%"}.get(unit, "%{y:,.3~s}")
    for trace in fig.data:
        if trace.type in ("bar", "scatter") and getattr(trace, "orientation", None) != "h":
            trace.hovertemplate = f"{body}<extra>%{{fullData.name}}</extra>"


def _style_horizontal(fig: go.Figure, spec: "_Spec", df: pd.DataFrame) -> None:
    """Axes for a horizontal ranking: names down the left, values along the bars."""
    unit = measure_unit(spec)
    bar = fig.data[0]
    values = [] if bar.x is None else list(bar.x)
    bar.text = [format_value(v, unit) for v in values]
    bar.textposition = "outside"
    bar.cliponaxis = False
    bar.textfont = dict(size=10.5, color=_INK)
    body = {"money": "$%{x:,.3~s}", "pct": "%{x:.1f}%"}.get(unit, "%{x:,.3~s}")
    bar.hovertemplate = f"<b>%{{y}}</b><br>{body}<extra></extra>"
    count = len(values)
    fig.update_layout(height=max(260, 34 * count + 90), bargap=0.32, hovermode="closest",
                      margin=dict(l=8, r=56, t=56, b=36))
    fig.update_yaxes(title=None, showgrid=False, showline=False, ticks="",
                     tickfont=dict(size=11.5, color=_INK), automargin=True)
    fig.update_xaxes(title=dict(text=spec.y_title or _pretty(spec.y[0]),
                                font=dict(size=12, color="#5A6B82")),
                     showgrid=True, gridcolor=_GRID, griddash="dot", zeroline=False,
                     tickfont=dict(size=11, color=_TICK_INK), automargin=True,
                     tickprefix="$" if unit == "money" else "",
                     ticksuffix="%" if unit == "pct" else "",
                     tickformat="~s" if unit != "pct" else None)


def _number_or(value, default: float) -> float:
    """A cell as a float, or `default` when it is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _signs(df, columns) -> tuple:
    """``(any negative, any positive)`` across the plotted columns.

    Read off the DATA rather than the chart type, so a premium chart and a
    year-on-year change chart are styled differently without the caller having
    to say which it is.
    """
    saw_negative = saw_positive = False
    for column in columns or ():
        if column not in getattr(df, "columns", ()):
            continue
        series = pd.to_numeric(df[column], errors="coerce").dropna()
        if len(series):
            saw_negative = saw_negative or bool((series < 0).any())
            saw_positive = saw_positive or bool((series > 0).any())
    return saw_negative, saw_positive


def _needs_zero_line(df, columns) -> bool:
    """Whether the baseline has to be drawn.

    Any negative value is enough: once a bar hangs below the baseline, the
    baseline is no longer the bottom of the plot and the reader cannot see where
    zero is. This is deliberately NOT the same test as the colouring one — a
    chart of 0, -5, -110, -135 needs the line and does not need two colours.
    """
    return _signs(df, columns)[0]


def _spans_zero(df, columns) -> bool:
    """Whether the values run in BOTH directions, so direction is worth colouring."""
    negative, positive = _signs(df, columns)
    return negative and positive


# ───── PUBLIC API ───────────────────────────────────────────────────────────


def generate_chart(
    df: pd.DataFrame, chart_outputs: Any
) -> Tuple[Optional[go.Figure], str]:
    """Build a styled Plotly figure from SQL rows + a ChartOutput spec.

    Returns `(figure, "Successful")` on success, or `(None, message)` when the
    data is not chartable. Never raises — any internal failure is logged and
    surfaced as a graceful message so the UI can fall back cleanly.
    """
    try:
        raw = _as_dict(chart_outputs)
        if not raw:
            return None, ""

        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame(df or [])

        # Pre-render critic: repair field roles / orientation / type against the
        # FULL result frame (the sanitizer below drops unreferenced columns).
        raw, repairs = _CRITIC.review(raw, df)
        if repairs:
            log_event(
                logger,
                "chart_critic_repairs",
                node="chart_renderer",
                reasons=repairs,
            )

        spec, prepared, message = _sanitize_spec(df, raw)
        if spec is None:
            return None, message

        prepared, overrides = _prepare_axis_ticks(prepared, spec)
        spec.horizontal = _wants_horizontal(prepared, spec)
        if overrides:
            log_event(
                logger,
                "chart_axis_prepared",
                node="chart_renderer",
                chart_type=spec.chart_type,
                reasons=overrides,
            )

        builder = _TRACE_REGISTRY.get(spec.chart_type)
        if builder is None:
            logger.warning("Unsupported chart type %r; falling back to bar.", spec.chart_type)
            spec.chart_type = "bar"
            builder = _TRACE_REGISTRY["bar"]

        fig = go.Figure()
        builder(fig, prepared, spec, {})
        _apply_theme(fig, spec, prepared)
        return fig, "Successful"
    except Exception:  # noqa: BLE001 - charting must never crash a turn
        logger.exception("Error creating the chart")
        return None, "Problem creating the chart"
