"""The timeline control: YTD / R12M, and the month the period ends in.

The deck works in months — every window :mod:`studio.period` builds starts on the 1st and
ends on a month end — so the author picks a MONTH, from a grid, rather than two billing
days from a pair of calendars that read like a flight search. Three answers, all mapped
onto the date keys the period layer already understands, so nothing downstream changed:

    Latest month     no dates             the book as stored (YTD) / R12M to the latest month
    Ending <month>   date_to = month end  YTD: 1 Jan -> that month, against the same months
                     (+ date_from = 1 Jan  a year earlier. R12M: the twelve months to it.
                      on YTD)
    Custom range     date_from, date_to   the author's own months, against a year earlier

The state is two small dicts held in stores: ``dates`` (``{"from": iso, "to": iso}``, the
answer) and ``view`` (``{"year", "mode", "anchor"}``, what the open grid shows). Every
transition is a pure function here; :mod:`studio.authoring.period_picker` only wires them.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from dash import dcc, html

BASIS_YTD = "calendar"      # the stored value is unchanged: "YTD" is its new NAME only
BASIS_R12M = "r12m"
BASIS_OPTIONS = (
    {"label": "YTD", "value": BASIS_YTD},
    {"label": "R12M", "value": BASIS_R12M},
)

MODE_END = "end"            # clicking a month sets where the period ends
MODE_RANGE = "range"        # first click = start month, second = end month

MONTHS = tuple(calendar.month_abbr)[1:]          # ("Jan", … "Dec")

PRESET_LATEST = "latest"
PRESET_LAST_QUARTER = "last_quarter"
PRESET_LAST_YEAR = "last_year"
PRESETS = (
    (PRESET_LATEST, "Latest"),
    (PRESET_LAST_QUARTER, "Last quarter"),
    (PRESET_LAST_YEAR, "Last year"),
)

Month = Tuple[int, int]     # (year, month)


# ── reading and writing the answer ───────────────────────────────────────────


def _month_of(value: Any) -> Optional[Month]:
    """``(year, month)`` of an ISO date string, else ``None``."""
    text = str(value or "")[:10]
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return day.year, day.month


def _first_day(month: Month) -> str:
    return date(month[0], month[1], 1).isoformat()


def _last_day(month: Month) -> str:
    return date(month[0], month[1], calendar.monthrange(*month)[1]).isoformat()


def _label(month: Month) -> str:
    return f"{MONTHS[month[1] - 1]} {month[0]}"


@dataclass(frozen=True)
class PeriodAnswer:
    """What the author chose, read back off the ``dates`` store."""

    start: Optional[Month] = None
    end: Optional[Month] = None
    custom: bool = False

    @property
    def is_latest(self) -> bool:
        return self.end is None


def read_answer(dates: Optional[Mapping[str, Any]]) -> PeriodAnswer:
    """The ``dates`` store as an answer. A missing or broken store is "latest month"."""
    dates = dates or {}
    return PeriodAnswer(start=_month_of(dates.get("from")), end=_month_of(dates.get("to")),
                        custom=bool(dates.get("custom")))


def ending_dates(month: Month, basis: str) -> dict:
    """The store for "the period ends in ``month``" on ``basis``.

    On YTD the window is 1 January to that month's end — the date-range path in
    :func:`studio.period.window_for`, which compares it with the same months a year
    earlier. On R12M only the end matters: the twelve months are counted back from it.
    """
    start = _first_day((month[0], 1)) if basis != BASIS_R12M else None
    return {"from": start, "to": _last_day(month), "custom": False}


def range_dates(first: Month, second: Month) -> dict:
    """The store for a custom range, whichever order the two months were clicked in."""
    start, end = sorted((first, second))
    return {"from": _first_day(start), "to": _last_day(end), "custom": True}


def rebase(dates: Optional[Mapping[str, Any]], basis: str) -> dict:
    """Keep the author's ending month when YTD / R12M is switched.

    A plain ending month means something different on each basis (1 Jan–Aug vs the twelve
    months to Aug), so its ``from`` is rewritten. A custom range is the author's own
    window and is left alone on YTD; on R12M it becomes "ending in its last month".
    """
    answer = read_answer(dates)
    if answer.is_latest:
        return {"from": None, "to": None, "custom": False}
    if answer.custom and basis != BASIS_R12M:
        return dict(dates or {})
    # R12M is twelve months by definition, so a custom range keeps only where it ends.
    return ending_dates(answer.end, basis)


def date_keys(dates: Optional[Mapping[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """``(date_from, date_to)`` for :func:`studio.authoring.setup.period_selection`."""
    dates = dates or {}
    return dates.get("from") or None, dates.get("to") or None


# ── the presets ──────────────────────────────────────────────────────────────


def preset_month(preset: str, latest: Optional[Month]) -> Optional[Month]:
    """The ending month a preset stands for, against the latest month in the data."""
    if preset == PRESET_LATEST or latest is None:
        return None
    year, month = latest
    if preset == PRESET_LAST_QUARTER:
        quarter_end = (month // 3) * 3          # the last COMPLETE quarter
        return (year, quarter_end) if quarter_end else (year - 1, 12)
    if preset == PRESET_LAST_YEAR:
        return year - 1, 12
    return None


# ── the grid ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GridCell:
    """One month button as painted: its class and whether it can be picked."""

    class_name: str
    disabled: bool


def _in_data(month: Month, latest: Optional[Month], first_year: Optional[int]) -> bool:
    if latest is not None and month > latest:
        return False
    return not (first_year is not None and month[0] < first_year)


def grid_cells(year: int, answer: PeriodAnswer, *, mode: str, anchor: Optional[Month],
               latest: Optional[Month], first_year: Optional[int]) -> List[GridCell]:
    """The twelve month buttons for ``year``.

    ``anchor`` is the first click of a range still waiting for its second. Months past the
    latest billing are disabled — a period cannot end in a month the book has not reached.
    """
    lo, hi = answer.start, answer.end
    if mode == MODE_RANGE and anchor is not None:
        lo, hi = anchor, anchor
    cells = []
    for m in range(1, 13):
        month = (year, m)
        classes = ["qs6-month"]
        if hi is not None and month == hi:
            classes.append("is-end")
            if not (answer.custom or anchor is not None):
                classes.append("is-solo")          # one month, not the end of a band
        if lo is not None and month == lo and (answer.custom or anchor is not None):
            classes.append("is-start")
        if (answer.custom or anchor is not None) and lo and hi and lo < month < hi:
            classes.append("in-range")
        if latest is not None and month == latest:
            classes.append("is-latest")
        ok = _in_data(month, latest, first_year)
        if not ok:
            classes.append("is-off")
        cells.append(GridCell(" ".join(classes), not ok))
    return cells


def grid_year(view: Optional[Mapping[str, Any]], answer: PeriodAnswer,
              latest: Optional[Month]) -> int:
    """Which year the grid opens on: the one it was left on, else the answer's, else latest."""
    view = view or {}
    if view.get("year"):
        return int(view["year"])
    if answer.end is not None:
        return answer.end[0]
    if latest is not None:
        return latest[0]
    return date.today().year


def can_step(year: int, step: int, *, latest: Optional[Month],
             first_year: Optional[int]) -> bool:
    target = year + step
    if latest is not None and target > latest[0]:
        return False
    return not (first_year is not None and target < first_year)


def _range_label(start: Month, end: Month) -> str:
    if start[0] == end[0]:
        return f"{MONTHS[start[1] - 1]} – {_label(end)}"
    return f"{_label(start)} – {_label(end)}"


def trigger_label(answer: PeriodAnswer, basis: str, latest: Optional[Month]) -> str:
    """What the closed control says: "Dec 2025 (latest)", "Aug 2026", "Mar – Aug 2026"."""
    if answer.custom and answer.start and answer.end:
        return _range_label(answer.start, answer.end)
    if answer.end is not None:
        return _label(answer.end)
    return f"{_label(latest)} (latest)" if latest else "Latest month"


def trigger_kicker(answer: PeriodAnswer) -> str:
    """The small word in front of the trigger's value: what the value IS."""
    return "Range" if (answer.custom and answer.start and answer.end) else "Ends"


def summary_line(answer: PeriodAnswer, basis: str, latest: Optional[Month],
                 year_pin: Optional[int] = None) -> str:
    """The short "what is compared" read-out beside the control: "YTD Aug 2026 vs YTD Aug 2025"."""
    if answer.custom and answer.start and answer.end:
        prior = ((answer.start[0] - 1, answer.start[1]), (answer.end[0] - 1, answer.end[1]))
        return (f"{_range_label(answer.start, answer.end)} vs "
                f"{_range_label(*prior)}")
    end = answer.end
    if end is None and latest is not None:
        end = latest
        if year_pin is not None and year_pin < latest[0]:
            end = (year_pin, latest[1] if basis == BASIS_R12M else 12)
    if end is None:
        return "R12M to the latest month" if basis == BASIS_R12M else "YTD — latest year"
    name = "R12M" if basis == BASIS_R12M else "YTD"
    if basis != BASIS_R12M and answer.end is None:
        return f"YTD {end[0]} vs {end[0] - 1}"
    return f"{name} {_label(end)} vs {name} {_label((end[0] - 1, end[1]))}"


# ── the markup ───────────────────────────────────────────────────────────────


def _month_button(index: int) -> html.Button:
    return html.Button(MONTHS[index - 1], id={"type": "qs6-month", "m": index},
                       className="qs6-month", n_clicks=0, type="button")


def _preset_button(key: str, text: str) -> html.Button:
    return html.Button(text, id={"type": "qs6-preset", "key": key},
                       className="qs6-preset", n_clicks=0, type="button")


def _mode_tabs() -> html.Div:
    return html.Div(
        [
            html.Button("Month", id={"type": "qs6-pmode", "mode": MODE_END},
                        className="qs6-pmode is-on", n_clicks=0, type="button",
                        title="The period ends in the month you pick"),
            html.Button("Range", id={"type": "qs6-pmode", "mode": MODE_RANGE},
                        className="qs6-pmode", n_clicks=0, type="button",
                        title="Pick a first and a last month"),
        ],
        className="qs6-pmodes", role="tablist",
    )


def month_popover() -> html.Div:
    """The panel that opens under the trigger. Opened and closed in the browser
    (assets/studio_v6.js) — only a pick goes to the server."""
    return html.Div(
        [
            html.Div(
                [html.Div([html.Span("Reporting period", className="qs6-pop-kicker"),
                           html.Span("", id="qs6-pop-summary", className="qs6-pop-summary")],
                          className="qs6-pop-title"),
                 _mode_tabs()],
                className="qs6-pop-head",
            ),
            html.Div(
                [
                    html.Button(html.I(className="bi bi-chevron-left"), id="qs6-year-prev",
                                className="qs6-year-step", n_clicks=0, type="button",
                                title="Previous year"),
                    html.Span("", id="qs6-year-label", className="qs6-year-label"),
                    html.Button(html.I(className="bi bi-chevron-right"), id="qs6-year-next",
                                className="qs6-year-step", n_clicks=0, type="button",
                                title="Next year"),
                ],
                className="qs6-year-row",
            ),
            html.Div([_month_button(i) for i in range(1, 13)], className="qs6-month-grid"),
            html.Div("", id="qs6-month-hint", className="qs6-month-hint"),
            html.Div([html.Span("Quick picks", className="qs6-presets-k"),
                      *[_preset_button(k, t) for k, t in PRESETS]], className="qs6-presets"),
        ],
        id="qs6-month-pop", className="qs6-month-pop", role="dialog",
        **{"aria-label": "Choose the month the period ends in"},
    )


def timeline_control(basis_value: str = BASIS_YTD) -> html.Div:
    """YTD / R12M, the month trigger with its popover, and the read-out beside them."""
    return html.Div(
        [
            dcc.RadioItems(
                id="studio-period-basis", options=list(BASIS_OPTIONS), value=basis_value,
                persistence=True, persistence_type="local",
                className="qs6-seg sm", inputClassName="qs6-seg-input",
                labelClassName="qs6-seg-label",
            ),
            html.Div(
                [
                    html.Button(
                        [html.I(className="bi bi-calendar3"),
                         html.Span("Ends", id="qs6-month-kicker", className="qs6-trig-k"),
                         html.Span("Latest month", id="qs6-month-text", className="qs6-trig-v"),
                         html.I(className="bi bi-chevron-down qs6-caret")],
                        id="qs6-month-trigger", className="qs6-month-trigger",
                        type="button", **{"aria-haspopup": "dialog"},
                    ),
                    month_popover(),
                ],
                className="qs6-month-wrap",
            ),
            # The answer. Kept across a re-render of Setup (a mode switch rebuilds the form)
            # like every other part of the brief.
            dcc.Store(id="studio-period-dates", storage_type="local",
                      data={"from": None, "to": None, "custom": False}),
            dcc.Store(id="qs6-month-view", data={"year": None, "mode": MODE_END,
                                                 "anchor": None}),
            dcc.Store(id="qs6-period-meta", data={"latest": None, "first_year": None}),
        ],
        className="qs6-timeline",
    )


def available_years(options: Sequence[Any]) -> Optional[int]:
    """The first year the Year filter offers — the grid's lower bound."""
    years = []
    for opt in options or []:
        value = opt.get("value") if isinstance(opt, Mapping) else opt
        if str(value).strip().isdigit():
            years.append(int(value))
    return min(years) if years else None
