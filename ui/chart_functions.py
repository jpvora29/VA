from dataclasses import dataclass
from functools import wraps
from typing import Callable

import plotly_express as px
import plotly.graph_objects as go
import pandas as pd

from ui.color_pallet import ColorPalette
from logger import get_logger

# ── Registry ──────────────────────────────────────────────────────────────────

_TRACE_REGISTRY: dict[str, Callable] = {}


def chart_type(name: str):
    """Decorator that registers a trace-builder under a chart type name."""

    def decorator(fn: Callable):
        _TRACE_REGISTRY[name] = fn

        @wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    return decorator


#  ── Logger ──────────────────────────────────────────────────────────────────────

logger = get_logger(__name__)

#  ── helper ─────────────────────────────────────────────────────────────────────


def _generate_color_mapping(unique_values, palette):
    """
    Create a mapping from unique series values to colors from the palette.
    If there are more unique values than colors, colors will cycle.
    """
    color_map = {}
    palette_len = len(palette)
    for i, val in enumerate(sorted(unique_values)):
        color_map[val] = palette[i % palette_len]
    return color_map


def _clean_val(val: str) -> str:
    return val.replace("_", " ").title()


@dataclass
class ChartData:
    x_col: str
    y_cols: list[str]
    series: list[str]
    barmodes: list[str]
    chart_type: str
    title: str

    @staticmethod
    def _clean_val(val: str) -> str:
        return val.replace("_", " ").title()

    @staticmethod
    def _clean_list_val(values: list[str]) -> list[str]:
        return [val.replace("_", " ").title() for val in values]


# ── Registered trace builders ─────────────────────────────────────────────────


@chart_type("bar")
def _build_bar(fig, df, cd, colors, color_map):
    add_traces(df, 0, [], fig=fig, cd=cd, color_map=color_map)
    if "stack" in cd.barmodes:
        fig.update_layout(barmode="stack")
    else:
        fig.update_layout(barmode="group")


@chart_type("line")
def _build_line(fig, df, cd, colors, color_map):
    add_traces_line(df, 0, [], fig=fig, cd=cd, color_map=color_map)


@chart_type("scatter")
def _build_scatter(fig, df, cd, colors, color_map):
    add_traces_scatter(df, 0, [], fig=fig, cd=cd, color_map=color_map)
    fig.update_layout(xaxis=dict(type="linear"))


@chart_type("pie")
def _build_pie(fig, df, cd, colors, color_map):
    add_traces_pie(df, 0, [], fig=fig, cd=cd, color_map=color_map)


# ── Core helpers (unchanged logic, just accept fig/cd as params) ──────────────


def add_traces(df_subset, series_idx, prev_keys, *, fig, cd, color_map):
    def combined_key(values):
        return " | ".join(str(v) for v in values)

    if series_idx >= len(cd.series):
        for y_col in cd.y_cols:
            fig.add_trace(
                go.Bar(
                    x=df_subset[cd.x_col],
                    y=df_subset[y_col],
                    name=combined_key(prev_keys),
                    offsetgroup=combined_key(prev_keys),
                    base=0,
                    marker_color=(
                        color_map.get(prev_keys[-1], None) if prev_keys else None
                    ),
                )
            )
        return

    current_series = cd.series[series_idx]
    current_barmode = (
        cd.barmodes[series_idx] if series_idx < len(cd.barmodes) else "group"
    )
    unique_vals = df_subset[current_series].unique()

    if current_barmode == "stack":
        base_accumulator = {x_val: 0 for x_val in df_subset[cd.x_col].unique()}
        for val in unique_vals:
            df_filtered = df_subset[df_subset[current_series] == val]
            y_sums = df_filtered.groupby(cd.x_col)[cd.y_cols[0]].sum()
            fig.add_trace(
                go.Bar(
                    x=y_sums.index,
                    y=y_sums.values,
                    name=combined_key(prev_keys + [val]),
                    offsetgroup=combined_key(prev_keys),
                    base=[base_accumulator[x_val] for x_val in y_sums.index],
                    marker_color=color_map.get(val, None),
                )
            )
            for x_val, y_val in zip(y_sums.index, y_sums.values):
                base_accumulator[x_val] += y_val
    else:  # group
        for val in unique_vals:
            df_filtered = df_subset[df_subset[current_series] == val]
            add_traces(
                df_filtered,
                series_idx + 1,
                prev_keys + [val],
                fig=fig,
                cd=cd,
                color_map=color_map,
            )


def add_traces_line(df_subset, series_idx, prev_keys, *, fig, cd, color_map):
    def combined_key(values):
        return " | ".join(str(v) for v in values)

    if series_idx >= len(cd.series):
        for y_col in cd.y_cols:
            fig.add_trace(
                go.Scatter(
                    x=df_subset[cd.x_col],
                    y=df_subset[y_col],
                    mode="lines+markers",
                    name=combined_key(prev_keys) + f" ({y_col})",
                    line=(
                        dict(color=color_map.get(prev_keys[-1], None))
                        if prev_keys
                        else None
                    ),
                )
            )
        return

    current_series = cd.series[series_idx]
    unique_vals = df_subset[current_series].unique()
    for val in unique_vals:
        df_filtered = df_subset[df_subset[current_series] == val]
        add_traces_line(
            df_filtered,
            series_idx + 1,
            prev_keys + [val],
            fig=fig,
            cd=cd,
            color_map=color_map,
        )


def add_traces_scatter(df_subset, series_idx, prev_keys, *, fig, cd, color_map):
    def combined_key(values):
        return " | ".join(str(v) for v in values)

    if series_idx >= len(cd.series):
        for y_col in cd.y_cols:
            fig.add_trace(
                go.Scatter(
                    x=df_subset[cd.x_col],
                    y=df_subset[y_col],
                    mode="markers",
                    name=combined_key(prev_keys) + f" ({y_col})",
                    marker=(
                        dict(color=color_map.get(prev_keys[-1], None))
                        if prev_keys
                        else None
                    ),
                    showlegend=True,
                )
            )
        return

    current_series = cd.series[series_idx]
    unique_vals = df_subset[current_series].unique()
    for val in unique_vals:
        df_filtered = df_subset[df_subset[current_series] == val]
        add_traces_scatter(
            df_filtered,
            series_idx + 1,
            prev_keys + [val],
            fig=fig,
            cd=cd,
            color_map=color_map,
        )


def add_traces_pie(df_subset, series_idx, prev_keys, *, fig, cd, color_map):
    def combined_key(values):
        return " | ".join(str(v) for v in values)

    if series_idx >= len(cd.series):
        for y_col in cd.y_cols:
            fig.add_trace(
                go.Pie(
                    labels=df_subset[cd.x_col],
                    values=df_subset[y_col],
                    name=combined_key(prev_keys) + f" ({y_col})",
                    marker=dict(
                        colors=[color_map.get(k, None) for k in df_subset[cd.x_col]]
                    ),
                    textinfo="label+percent",
                    hole=0,
                )
            )
        return

    current_series = cd.series[series_idx]
    unique_vals = df_subset[current_series].unique()
    for val in unique_vals:
        df_filtered = df_subset[df_subset[current_series] == val]
        add_traces_pie(
            df_filtered,
            series_idx + 1,
            prev_keys + [val],
            fig=fig,
            cd=cd,
            color_map=color_map,
        )


# ───── PUBLIC API ───────────────────────────────────────────────────────────────────


def generate_chart(
    df: pd.DataFrame, chart_outputs: dict[str, str]
) -> tuple[go.Figure | None, str]:

    cd: ChartData = chart_outputs
    fig = go.Figure()
    colors = ColorPalette.get_colors

    x_axis_data_type = dict(type="category")
    if cd.chart_type == "none":
        return None, "Chart can not be generated as the data is scalar."

    if (cd.y_cols != cd.series) and (len(cd.y_cols) + len(cd.series) + 1 > 3):
        return (
            None,
            "Since the question has more than 3 catergories, the chart can not be displayed due to its low readability",
        )

    try:
        cd.x_col = ChartData._clean_val(cd.x_col)
        cd.y_cols = ChartData._clean_list_val(cd.y_cols)
        cd.series = ChartData._clean_list_val(cd.series)
        cd.title = ChartData._clean_val(cd.title)

        df.columns = [i.replace("_", " ").title() for i in df.columns]

        # Create a global color mapping for all unique series values across all series levels
        # Flatten all unique values from all series columns
        builder = _TRACE_REGISTRY.get(cd.chart_type)
        if builder is None:
            logger.exception(f"Unsupported chart type: {cd.chart_type!r}")

        # Re-use same builders; they handle the series_idx >= len(cd.series) base case
        builder(fig, df, cd, colors, color_map={})

        fig.update_layout(
            title=dict(
                text=cd.title,
                x=0.5,
                xanchor="center",
                font=dict(size=14, family="Arial Black", color="black"),
            ),
            margin=dict(l=60, r=40, t=60, b=60),
            xaxis_title=cd.x_col,
            yaxis_title=", ".join(cd.y_cols),
            legend_title=" | ".join(cd.series) if cd.series else None,
            xaxis=x_axis_data_type,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                x=1.02,
                xanchor="left",
                font=dict(size=10),
                itemsizing="constant",
                itemwidth=30,
                # maxheight=0.1,
            ),
            template="plotly_white",
        )
        return fig, "Successful"
    except Exception as E:
        logger.exception("Error is creating the chart")
        return None, "Problem creating the chart"
