"""Which chart a result set gets, decided by rules in code.

A model asked to pick a chart type picks a bar chart, or a line between three
products, often enough that readers stopped trusting the picture. The right
chart follows from the shape of the rows and nothing else:

    question the rows answer        chart
    ------------------------------  ------------------------------------------
    one value                       none (the KPI tile already says it)
    fewer than 3 points             none (the table says it better)
    what drove a change             waterfall (bridge)
    quarter against quarter         grouped bars, one bar per year in a quarter
    change over time, 3+ periods    line, the latest change labelled
    make-up of a whole              donut up to 4 parts, sorted bars past that
    client vs peers                 dot chart, client in the accent colour
    ranking                         sorted horizontal bars, subject highlighted
    anything else                   none

The rules are tried in that order and the first that applies wins, so adding a
rule is adding a row to :data:`RULES`. Each rule also says WHY, in one line the
evidence panel prints under the chart.

Titles are written from the columns, never from the question, so a title cannot
promise something the rows do not contain.

Pure: rows in, a :class:`ChartChoice` out. No model, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Fewer points than this and a chart adds nothing the table does not.
MIN_POINTS = 3
#: A whole split into more parts than this reads better as bars than as slices.
MAX_SLICES = 4
#: A trend with more series than this is a tangle; draw the first measure only.
MAX_TREND_SERIES = 6

_TIME_NAME = re.compile(
    r"(?i)\b(year|quarter|month|period|date|week|fy)\b|_(year|quarter|month)$"
)
_TIME_VALUE = re.compile(
    r"(?i)^((19|20)\d{2}|q[1-4]|(19|20)\d{2}[- ]?q[1-4]|q[1-4][- ](19|20)\d{2})$"
)
_YEAR_NAME = re.compile(r"^(fy)?(19|20)\d{2}$", re.I)
_CHANGE_NAME = re.compile(
    r"(?i)change|delta|contribution|movement|bridge|impact|variance|diff"
)
_SHARE_NAME = re.compile(r"(?i)share|mix|percent|pct|portion|%")
_BENCHMARK_NAME = re.compile(r"(?i)peer|market|average|avg|benchmark|marsh|book|median")
_QUARTER_NAME = re.compile(r"(?i)quarter|\bqtr\b")
_QUARTER_VALUE = re.compile(r"(?i)\bq[1-4]\b")
_RANK_NAME = re.compile(r"(?i)\brank\b|position|_id$|^id$")


@dataclass(frozen=True)
class RowProfile:
    """What a result set is made of, read once so every rule reads the same facts."""

    rows: tuple[dict[str, Any], ...]
    measures: tuple[str, ...]
    labels: tuple[str, ...]
    time_axis: str
    year_columns: tuple[str, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def distinct(self, column: str) -> int:
        return len({str(row.get(column)) for row in self.rows})

    def values(self, column: str) -> list[Any]:
        return [row.get(column) for row in self.rows]

    def unique_on(self, *columns: str) -> bool:
        """Whether these columns identify every row, so nothing gets summed."""
        keys = [tuple(str(row.get(c)) for c in columns) for row in self.rows]
        return len(set(keys)) == len(keys)


@dataclass(frozen=True)
class ChartChoice:
    """The chart a rule chose, or the decision to draw none, and why."""

    rule: str
    reason: str
    chart_type: str = ""
    x: str = ""
    y: tuple[str, ...] = ()
    series: tuple[str, ...] = ()
    highlight: str = ""
    orientation: str = ""
    title: str = ""

    @property
    def has_chart(self) -> bool:
        return bool(self.chart_type)

    def as_chart_data(self) -> dict[str, Any]:
        """The renderer's spec (``ui.chart_functions.generate_chart``)."""
        if not self.has_chart:
            return {}
        data: dict[str, Any] = {
            "chart_type": self.chart_type,
            "x": self.x,
            "y": list(self.y),
            "series": list(self.series),
            "title": self.title,
            "reason": self.reason,
            "rule": self.rule,
            # Decided from the data, like `core.answers.chart_plan`, so the
            # renderer's critic treats a line here as a trend by construction.
            "planned": True,
        }
        if self.highlight:
            data["highlight"] = self.highlight
        if self.orientation:
            data["orientation"] = self.orientation
        return data


@dataclass(frozen=True)
class ChartRule:
    """One row of the table: when it applies, and the chart it builds."""

    name: str
    applies: Callable[[RowProfile], bool]
    build: Callable[[RowProfile, Sequence[str]], ChartChoice]


# --------------------------------------------------------------------------- #
# Reading the rows
# --------------------------------------------------------------------------- #


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return value == value  # NaN is not a number worth plotting
    try:
        float(str(value).replace(",", ""))
        return True
    except ValueError:
        return False


def _as_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _is_time_column(column: str, values: Sequence[Any]) -> bool:
    """A period axis: time-like values, or a time name over labels that are not amounts.

    "Change vs prior year" names a year and holds amounts, so the name alone is
    not enough when the values are numbers that are not years.
    """
    present = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not present:
        return False
    if all(_TIME_VALUE.match(v) for v in present):
        return True
    if all(_is_number(v) for v in present):
        return False
    return bool(_TIME_NAME.search(column))


def profile_rows(rows: Sequence[Mapping[str, Any]]) -> RowProfile:
    """Sort a result set's columns into measures, labels and a time axis."""
    records = tuple(dict(r) for r in rows if isinstance(r, Mapping))
    columns = list(records[0].keys()) if records else []
    time_axis = ""
    measures: list[str] = []
    labels: list[str] = []
    years: list[str] = []
    for column in columns:
        values = [r.get(column) for r in records]
        present = [v for v in values if v is not None and str(v).strip() != ""]
        if not time_axis and _is_time_column(column, present):
            time_axis = column
            continue
        if present and all(_is_number(v) for v in present):
            if _YEAR_NAME.match(str(column)):
                years.append(column)
            if not _RANK_NAME.search(column):
                measures.append(column)
            continue
        labels.append(column)
    return RowProfile(
        rows=records,
        measures=tuple(measures),
        labels=tuple(labels),
        time_axis=time_axis,
        year_columns=tuple(years),
    )


def _pretty(column: str) -> str:
    """ "product_line" -> "Product line"."""
    text = str(column).replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else ""


def _title(measures: Sequence[str], axis: str) -> str:
    named = " vs ".join(_pretty(m) for m in measures[:2])
    return f"{named} by {_pretty(axis).lower()}" if axis else named


def _subject_in(profile: RowProfile, column: str, subjects: Sequence[str]) -> str:
    """The row value naming the subject, spelled as the rows spell it."""
    wanted = {str(s).strip().lower() for s in subjects if str(s).strip()}
    for value in profile.values(column):
        if str(value).strip().lower() in wanted:
            return str(value)
    return ""


# --------------------------------------------------------------------------- #
# The rules: a predicate and a builder each
# --------------------------------------------------------------------------- #


def _points(profile: RowProfile) -> int:
    axis = profile.time_axis or (profile.labels[0] if profile.labels else "")
    if axis:
        return profile.distinct(axis)
    return profile.row_count


def _too_few(profile: RowProfile) -> bool:
    return not profile.measures or _points(profile) < MIN_POINTS


def _no_chart(profile: RowProfile, _subjects: Sequence[str]) -> ChartChoice:
    if profile.row_count == 1 and len(profile.measures) == 1:
        return ChartChoice("kpi", "One value, so it is shown as a figure, not a chart.")
    return ChartChoice(
        "too_few", "Fewer than three points, so the table shows it better than a chart."
    )


def _change_measure(profile: RowProfile) -> str:
    for measure in profile.measures:
        if _CHANGE_NAME.search(measure):
            values = [_as_float(v) for v in profile.values(measure)]
            if min(values) < 0 < max(values):
                return measure
    return ""


def _is_bridge(profile: RowProfile) -> bool:
    return (
        not profile.time_axis
        and bool(profile.labels)
        and bool(_change_measure(profile))
        and profile.unique_on(profile.labels[0])
    )


def _bridge(profile: RowProfile, _subjects: Sequence[str]) -> ChartChoice:
    measure = _change_measure(profile)
    axis = profile.labels[0]
    return ChartChoice(
        "bridge",
        "Waterfall, because the question is what drove the change: each bar adds "
        "to or takes away from the total.",
        chart_type="waterfall",
        x=axis,
        y=(measure,),
        title=f"What drove the {_pretty(measure).lower()}, by {_pretty(axis).lower()}",
    )


def _trend_series(profile: RowProfile) -> str:
    for label in profile.labels:
        if profile.distinct(label) <= MAX_TREND_SERIES and profile.unique_on(
            profile.time_axis, label
        ):
            return label
    return ""


def _is_trend(profile: RowProfile) -> bool:
    if not profile.time_axis or profile.distinct(profile.time_axis) < MIN_POINTS:
        return False
    return profile.unique_on(profile.time_axis) or bool(_trend_series(profile))


def _is_quarterly(profile: RowProfile) -> bool:
    """Quarters on the axis: a comparison of periods, which reads as bars.

    A line between Q1 and Q4 asserts a continuous path through the year; the
    question is how each quarter compares, with the prior year beside it.
    """
    return _is_trend(profile) and bool(_QUARTER_NAME.search(profile.time_axis) or _quarter_values(profile))


def _quarter_values(profile: RowProfile) -> bool:
    values = [str(v).strip() for v in profile.values(profile.time_axis)]
    return bool(values) and all(_QUARTER_VALUE.search(v) for v in values)


def _quarterly(profile: RowProfile, _subjects: Sequence[str]) -> ChartChoice:
    axis = profile.time_axis
    years = profile.year_columns
    series = () if profile.unique_on(axis) else (_trend_series(profile),)
    y = years if len(years) >= 2 and not series else profile.measures[:1]
    reason = (
        "Grouped bars, because the question compares quarters: each quarter's "
        "bars sit side by side, prior year beside this year."
        if len(y) > 1 or series
        else "Bars, because the question compares quarters, not a continuous path."
    )
    return ChartChoice(
        "quarterly",
        reason,
        chart_type="bar",
        x=axis,
        y=tuple(y),
        series=series,
        title=_title(tuple(dict.fromkeys((y[0], y[-1]))), axis),
    )


def _trend(profile: RowProfile, _subjects: Sequence[str]) -> ChartChoice:
    axis = profile.time_axis
    series = () if profile.unique_on(axis) else (_trend_series(profile),)
    if not series and len(profile.year_columns) >= 2:
        y = profile.year_columns
    elif series:
        y = profile.measures[:1]
    else:
        y = profile.measures[:2]
    reason = "Line, because the question is about change over time"
    reason += "; the latest change is labelled." if len(y) == 1 and not series else "."
    return ChartChoice(
        "trend",
        reason,
        chart_type="line",
        x=axis,
        y=tuple(y),
        series=series,
        title=_title(tuple(dict.fromkeys((y[0], y[-1]))), axis),
    )


def _share_measure(profile: RowProfile) -> str:
    for measure in profile.measures:
        if not _SHARE_NAME.search(measure):
            continue
        values = [_as_float(v) for v in profile.values(measure)]
        if min(values) < 0:
            continue
        total = sum(values)
        if 90 <= total <= 110 or 0.9 <= total <= 1.1:
            return measure
    return ""


def _is_mix(profile: RowProfile) -> bool:
    return (
        bool(profile.labels)
        and bool(_share_measure(profile))
        and profile.unique_on(profile.labels[0])
    )


def _mix(profile: RowProfile, subjects: Sequence[str]) -> ChartChoice:
    measure = _share_measure(profile)
    axis = profile.labels[0]
    title = _title((measure,), axis)
    if profile.distinct(axis) <= MAX_SLICES:
        return ChartChoice(
            "mix",
            "Donut, because the parts make up one whole and there are few enough "
            "to read as slices.",
            chart_type="donut",
            x=axis,
            y=(measure,),
            title=title,
        )
    return ChartChoice(
        "mix",
        "Sorted bars, because more than four parts of a whole are easier to "
        "compare as bars than as slices.",
        chart_type="bar",
        x=axis,
        y=(measure,),
        orientation="h",
        highlight=_subject_in(profile, axis, subjects),
        title=title,
    )


def _benchmark_pair(profile: RowProfile) -> tuple[str, str]:
    """(client measure, benchmark measure) when the rows carry exactly that pair."""
    bench = [m for m in profile.measures if _BENCHMARK_NAME.search(m)]
    own = [m for m in profile.measures if not _BENCHMARK_NAME.search(m)]
    if len(bench) == 1 and own:
        return own[0], bench[0]
    return "", ""


def _is_versus_peers(profile: RowProfile) -> bool:
    return (
        bool(profile.labels)
        and all(_benchmark_pair(profile))
        and profile.unique_on(profile.labels[0])
    )


def _versus_peers(profile: RowProfile, _subjects: Sequence[str]) -> ChartChoice:
    own, bench = _benchmark_pair(profile)
    axis = profile.labels[0]
    return ChartChoice(
        "versus_peers",
        "Dot chart, because the question is how the client compares with peers: "
        "the gap between the two dots is the answer.",
        chart_type="dot",
        x=axis,
        y=(own, bench),
        title=_title((own, bench), axis),
    )


def _is_ranking(profile: RowProfile) -> bool:
    return bool(profile.labels) and profile.unique_on(profile.labels[0])


def _ranking(profile: RowProfile, subjects: Sequence[str]) -> ChartChoice:
    axis = profile.labels[0]
    measure = profile.measures[0]
    highlight = _subject_in(profile, axis, subjects)
    reason = "Sorted bars, because a ranking reads top to bottom, largest first."
    if highlight:
        reason += f" {highlight} is highlighted."
    return ChartChoice(
        "ranking",
        reason,
        chart_type="bar",
        x=axis,
        y=(measure,),
        orientation="h",
        highlight=highlight,
        title=_title((measure,), axis),
    )


#: The table. Tried in order; the first rule that applies decides.
RULES: tuple[ChartRule, ...] = (
    ChartRule("too_few", _too_few, _no_chart),
    ChartRule("bridge", _is_bridge, _bridge),
    ChartRule("quarterly", _is_quarterly, _quarterly),
    ChartRule("trend", _is_trend, _trend),
    ChartRule("mix", _is_mix, _mix),
    ChartRule("versus_peers", _is_versus_peers, _versus_peers),
    ChartRule("ranking", _is_ranking, _ranking),
)

_NO_RULE = ChartChoice(
    "none", "No chart fits these rows, so they are shown as a table."
)


def choose_chart(
    rows: Sequence[Mapping[str, Any]], *, subjects: Sequence[str] = ()
) -> ChartChoice:
    """The chart for one result set, by the first rule in :data:`RULES` that applies.

    ``subjects`` are the names the answer is about (a carrier, a line); the first
    one found in the rows is drawn in the accent colour.
    """
    profile = profile_rows(rows)
    for rule in RULES:
        if rule.applies(profile):
            return rule.build(profile, tuple(subjects))
    return _NO_RULE


def mix_chart_type(parts: int) -> str:
    """The make-up rule on its own, for the planned charts: slices up to four."""
    return "donut" if parts <= MAX_SLICES else "bar"
