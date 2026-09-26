"""Callbacks for Setup's month picker (:mod:`studio.page.authoring.period_picker`).

Two callbacks, one each way, so they cannot form a loop:

    a click           ->  the answer + the grid's view   (``pick_period``)
    answer + view     ->  the grid as painted            (``paint_period``)

Opening and closing the panel happens in the browser (assets/studio_v6.js); nothing
here waits on it.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from dash import ALL, Input, Output, State, ctx, no_update

from studio.page.authoring import period_picker as PP


def _latest(meta: Optional[Mapping[str, Any]]):
    latest = (meta or {}).get("latest")
    return (int(latest[0]), int(latest[1])) if latest else None


def next_state(trigger: Any, *, dates: Optional[Mapping[str, Any]],
               view: Optional[Mapping[str, Any]], basis: str,
               meta: Optional[Mapping[str, Any]]):
    """``(dates, view, basis)`` after one click. ``no_update`` for any that did not change.

    A finished custom range also sets the basis to YTD: R12M is twelve months by
    definition and would silently ignore the range's first month.

    Pure apart from the sentinel, so every transition is testable without a browser.
    """
    view = dict(view or {})
    latest = _latest(meta)
    answer = PP.read_answer(dates)
    year = PP.grid_year(view, answer, latest)
    mode = view.get("mode") or PP.MODE_END

    if trigger == "studio-period-basis":
        return PP.rebase(dates, basis), no_update, no_update
    if trigger in ("qs6-year-prev", "qs6-year-next"):
        step = -1 if trigger == "qs6-year-prev" else 1
        if not PP.can_step(year, step, latest=latest, first_year=(meta or {}).get("first_year")):
            return no_update, no_update, no_update
        return no_update, {**view, "year": year + step}, no_update
    if not isinstance(trigger, Mapping):
        return no_update, no_update, no_update

    kind = trigger.get("type")
    if kind == "qs6-pmode":
        return (no_update, {**view, "mode": trigger.get("mode"), "anchor": None, "year": year},
                no_update)
    if kind == "qs6-preset":
        month = PP.preset_month(str(trigger.get("key")), latest)
        new = PP.ending_dates(month, basis) if month else {"from": None, "to": None,
                                                            "custom": False}
        return new, {**view, "mode": PP.MODE_END, "anchor": None,
                     "year": month[0] if month else None}, no_update
    if kind == "qs6-month":
        month = (year, int(trigger.get("m")))
        if mode == PP.MODE_RANGE:
            anchor = view.get("anchor")
            if not anchor:
                return no_update, {**view, "anchor": list(month), "year": year}, no_update
            return (PP.range_dates(tuple(anchor), month), {**view, "anchor": None, "year": year},
                    PP.BASIS_YTD if basis == PP.BASIS_R12M else no_update)
        return PP.ending_dates(month, basis), {**view, "anchor": None, "year": year}, no_update
    return no_update, no_update, no_update


def paint(dates, view, basis, meta):
    """Everything the open (or closed) picker shows for the current state."""
    view = view or {}
    latest = _latest(meta)
    first_year = (meta or {}).get("first_year")
    answer = PP.read_answer(dates)
    year = PP.grid_year(view, answer, latest)
    mode = view.get("mode") or PP.MODE_END
    anchor = tuple(view["anchor"]) if view.get("anchor") else None
    cells = PP.grid_cells(year, answer, mode=mode, anchor=anchor, latest=latest,
                          first_year=first_year)
    if mode == PP.MODE_RANGE:
        hint = "Now pick the last month." if anchor else "Pick the first month."
    else:
        hint = ("YTD runs January to the month you pick." if basis != PP.BASIS_R12M
                else "R12M is the 12 months to the month you pick.")
    return (
        [c.class_name for c in cells],
        [c.disabled for c in cells],
        str(year),
        not PP.can_step(year, -1, latest=latest, first_year=first_year),
        not PP.can_step(year, 1, latest=latest, first_year=first_year),
        PP.trigger_label(answer, basis, latest),
        hint,
        ["qs6-pmode" + (" is-on" if m == mode else "") for m in (PP.MODE_END, PP.MODE_RANGE)],
        "qs6-month-trigger" + ("" if answer.is_latest else " is-set"),
        PP.trigger_kicker(answer),
        PP.summary_line(answer, basis, latest),
    )


def register_period_picker(app) -> None:
    @app.callback(
        Output("studio-period-dates", "data"),
        Output("qs6-month-view", "data"),
        Output("studio-period-basis", "value"),
        Input({"type": "qs6-month", "m": ALL}, "n_clicks"),
        Input({"type": "qs6-preset", "key": ALL}, "n_clicks"),
        Input({"type": "qs6-pmode", "mode": ALL}, "n_clicks"),
        Input("qs6-year-prev", "n_clicks"),
        Input("qs6-year-next", "n_clicks"),
        Input("studio-period-basis", "value"),
        State("studio-period-dates", "data"),
        State("qs6-month-view", "data"),
        State("qs6-period-meta", "data"),
        prevent_initial_call=True,
    )
    def pick_period(_m, _p, _mode, _prev, _next, basis, dates, view, meta):
        """One click on the picker, read into the answer and the grid's view."""
        trigger = ctx.triggered_id
        # A re-mounted button reports n_clicks=0; that is not a click.
        if trigger != "studio-period-basis" and not (ctx.triggered and ctx.triggered[0].get("value")):
            return no_update, no_update, no_update
        return next_state(trigger, dates=dates, view=view, basis=basis, meta=meta)

    @app.callback(
        Output({"type": "qs6-month", "m": ALL}, "className"),
        Output({"type": "qs6-month", "m": ALL}, "disabled"),
        Output("qs6-year-label", "children"),
        Output("qs6-year-prev", "disabled"),
        Output("qs6-year-next", "disabled"),
        Output("qs6-month-text", "children"),
        Output("qs6-month-hint", "children"),
        Output({"type": "qs6-pmode", "mode": ALL}, "className"),
        Output("qs6-month-trigger", "className"),
        Output("qs6-month-kicker", "children"),
        Output("qs6-pop-summary", "children"),
        Input("studio-period-dates", "data"),
        Input("qs6-month-view", "data"),
        Input("studio-period-basis", "value"),
        Input("qs6-period-meta", "data"),
    )
    def paint_period(dates, view, basis, meta):
        """Repaint the grid, the year, and the trigger's own label."""
        return paint(dates, view, basis, meta)
