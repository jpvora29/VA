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

from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go

from ui.color_pallet import ColorPalette
from logger import get_logger

logger = get_logger(__name__)

# ── Tunables ────────────────────────────────────────────────────────────────
MAX_SERIES = 12          # distinct legend entries before we bucket the tail
MAX_PIE_SLICES = 8       # pie/donut readability ceiling
_AGGS = {"sum", "mean", "count", "median", "min", "max"}

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


def _as_dict(spec: Any) -> Dict[str, Any]:
    """Accept a ChartOutput pydantic model, a plain dict, or a legacy object."""
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


def _sanitize_spec(
    df: pd.DataFrame, raw: Dict[str, Any]
) -> Tuple[Optional[_Spec], pd.DataFrame, str]:
    """Reconcile the raw spec against `df`. Returns (spec, prepared_df, message).

    `spec is None` means "do not draw" — `message` explains why (e.g. scalar).
    Never raises.
    """
    chart = str(raw.get("chart_type") or "none").strip().lower()
    if chart == "none":
        return None, df, "Chart can not be generated as the data is scalar."
    if df is None or df.empty:
        return None, df, "No data to chart."

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
        # Fall back to every numeric column the LLM didn't name.
        y = [c for c in numeric_cols]
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
        agg = spec.y_agg if spec.y_agg in _AGGS else "sum"
        df = df.groupby(group_cols, dropna=False, as_index=False)[measures].agg(agg)

    # Cap high-cardinality series: keep the top (MAX_SERIES-1) by total measure,
    # bucket the rest as "Other", so the legend stays readable.
    for s in spec.series:
        if df[s].nunique(dropna=False) > MAX_SERIES:
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
        order = (
            df.groupby(spec.x, dropna=False)[spec.y[0]].sum()
            .sort_values(ascending=spec.sort == "asc").index
        )
        df[spec.x] = pd.Categorical(df[spec.x], categories=list(order), ordered=True)
        df = df.sort_values(spec.x)

    return df.reset_index(drop=True)


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
    if key is not None:
        for i, val in enumerate(_ordered_unique(key)):
            sub = df[key == val]
            fig.add_trace(
                go.Bar(
                    x=sub[spec.x], y=sub[spec.y[0]], name=_pretty(val),
                    marker_color=color_map.setdefault(val, ColorPalette.color_for(i)),
                )
            )
    else:
        for i, ycol in enumerate(spec.y):
            fig.add_trace(
                go.Bar(
                    x=df[spec.x], y=df[ycol], name=_pretty(ycol),
                    marker_color=ColorPalette.color_for(i),
                )
            )
    fig.update_layout(barmode="stack" if stacked else "group")


@chart_type("line")
def _build_line(fig: go.Figure, df: pd.DataFrame, spec: _Spec, color_map: Dict) -> None:
    key = _series_key(df, spec.series)
    if key is not None:
        for i, val in enumerate(_ordered_unique(key)):
            sub = df[key == val]
            fig.add_trace(
                go.Scatter(
                    x=sub[spec.x], y=sub[spec.y[0]], mode="lines+markers",
                    name=_pretty(val),
                    line=dict(color=color_map.setdefault(val, ColorPalette.color_for(i)), width=2.5),
                    marker=dict(size=6),
                )
            )
    else:
        for i, ycol in enumerate(spec.y):
            fig.add_trace(
                go.Scatter(
                    x=df[spec.x], y=df[ycol], mode="lines+markers", name=_pretty(ycol),
                    line=dict(color=ColorPalette.color_for(i), width=2.5),
                    marker=dict(size=6),
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
    # If the spec gave no explicit total, append a closing total bar.
    if "total" not in measures and "absolute" not in measures:
        labels.append("Total")
        values.append(0)
        measures.append("total")
    fig.add_trace(
        go.Waterfall(
            x=labels, y=values, measure=measures,
            connector=dict(line=dict(color="#C7CFDB", width=1)),
            increasing=dict(marker=dict(color=ColorPalette.positive)),
            decreasing=dict(marker=dict(color=ColorPalette.negative)),
            totals=dict(marker=dict(color=ColorPalette.total)),
            text=[_format_number(v) for v in values], textposition="outside",
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


# ── Theme ─────────────────────────────────────────────────────────────────────

_FONT_FAMILY = "Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
_INK = "#1B222F"
_TITLE_INK = "#001538"
_GRID = "#EEF2F7"
_AXIS_LINE = "#D1E0EC"


def _apply_theme(fig: go.Figure, spec: _Spec, df: pd.DataFrame) -> None:
    """Apply the shared, Claude-like visual style to any figure."""
    is_polar = spec.chart_type in ("pie", "donut")
    multi = (
        spec.is_legend
        and spec.chart_type not in ("pie", "donut", "waterfall")
        and (bool(spec.series) or len(spec.y) + len(spec.secondary_y) > 1)
    )

    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=_pretty(spec.title) if spec.title else "",
            x=0.02, xanchor="left", y=0.96,
            font=dict(size=17, color=_TITLE_INK, family=_FONT_FAMILY),
        ),
        font=dict(family=_FONT_FAMILY, size=13, color=_INK),
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=64, r=48 if spec.chart_type == "combo" else 32, t=72, b=64),
        colorway=ColorPalette.get_colors(),
        bargap=0.28,
        bargroupgap=0.08,
        showlegend=multi,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11), title=None,
        ),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family=_FONT_FAMILY,
                        bordercolor=_AXIS_LINE),
    )
    # Rounded bar corners (Plotly ≥5.18 / 6.x).
    if spec.chart_type in ("bar", "combo"):
        try:
            fig.update_layout(barcornerradius=6)
        except Exception:  # noqa: BLE001 - older plotly: harmless to skip
            pass

    if not is_polar:
        fig.update_xaxes(
            title=dict(text=_pretty(spec.x), font=dict(size=12, color="#5A6B82")),
            showgrid=False, showline=True, linecolor=_AXIS_LINE, linewidth=1,
            ticks="outside", tickcolor=_AXIS_LINE, tickfont=dict(size=11),
            automargin=True,
        )
        ytitle = ", ".join(_pretty(c) for c in spec.y)
        fig.update_yaxes(
            title=dict(text=ytitle, font=dict(size=12, color="#5A6B82")),
            showgrid=True, gridcolor=_GRID, gridwidth=1, zeroline=False,
            showline=False, tickfont=dict(size=11), automargin=True,
        )
        if spec.chart_type not in ("scatter",):
            fig.update_layout(hovermode="x unified")


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

        spec, prepared, message = _sanitize_spec(df, raw)
        if spec is None:
            return None, message

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
