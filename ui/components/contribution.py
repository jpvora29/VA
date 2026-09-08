"""What drove the movement, drawn as a signed bar per slice.

The point of the chart is the SIGN. A ranked table of movements makes the reader
work out which slices pushed the total down and which pulled it back up; bars
either side of a centre line say it at a glance, and the one that crosses furthest
is the story.

Percentages of the move can exceed 100 and can go negative — see
:mod:`core.answers.contribution`. They are printed as computed, because a slice
that fell further than the whole is exactly the finding worth showing.

Pure presentation; the arithmetic is in core.
"""
from __future__ import annotations

from typing import Any, Dict, List

from dash import html

from core.boardroom.money import format_money

# Widest a bar gets, as a share of its half of the track.
_MAX_BAR_PCT = 96.0

# Slices shown before the tail is folded into one row. Beyond this the list stops
# being a finding and becomes a data dump.
_MAX_DRIVERS = 8


def _pct(value: Any) -> str:
    try:
        return f"{float(value):+.0f}%"
    except (TypeError, ValueError):
        return "—"


def _signed_money(value: Any) -> str:
    """A movement with its sign OUTSIDE the currency: -£3.1m, not £-3.1m.

    `format_money` puts the symbol first and lets the number carry the sign,
    which reads as a negative currency rather than a fall.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if number < 0 else "+" if number > 0 else ""
    return f"{sign}{format_money(abs(number))}"


def _driver_row(driver: Dict[str, Any], widest: float):
    delta = float(driver.get("delta") or 0.0)
    width = min(_MAX_BAR_PCT, abs(delta) / widest * _MAX_BAR_PCT) if widest else 0.0
    positive = delta >= 0
    bar = html.Div(
        html.Div(
            className=f"contrib-bar-fill {'up' if positive else 'down'}",
            style={"width": f"{width:.1f}%", ("left" if positive else "right"): "50%"},
        ),
        className="contrib-bar-track",
        title=(
            f"{driver.get('name')}: {format_money(driver.get('prior'))} → "
            f"{format_money(driver.get('current'))}"
        ),
    )
    return html.Div(
        [
            html.Span(str(driver.get("name") or ""), className="contrib-name"),
            bar,
            html.Span(
                _signed_money(delta),
                className=f"contrib-delta {'up' if positive else 'down'}",
            ),
            html.Span(_pct(driver.get("share_pct")), className="contrib-share"),
        ],
        className="contrib-row",
    )


def contribution_panel(payload: Dict[str, Any] | None):
    """The decomposition, or the honest note saying why there isn't one."""
    payload = payload or {}
    drivers: List[Dict[str, Any]] = list(payload.get("drivers") or [])
    note = str(payload.get("note") or "").strip()

    if not drivers:
        if not note:
            return None
        return html.Div(
            [html.I(className="bi bi-info-circle"), html.Span(note)],
            className="message contrib-panel is-empty",
        )

    shown = drivers[:_MAX_DRIVERS]
    widest = max((abs(float(d.get("delta") or 0.0)) for d in shown), default=0.0)
    move = payload.get("total_move")
    measure = str(payload.get("measure") or "the measure").replace("_", " ")
    dimension = str(payload.get("dimension") or "").replace("_", " ")

    header = html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-diagram-3 contrib-icon"),
                    html.Span("What drove the movement", className="contrib-title"),
                ],
                className="contrib-heading",
            ),
            html.Div(
                f"{measure} by {dimension} · {payload.get('prior_period')} → "
                f"{payload.get('current_period')}",
                className="contrib-basis",
            ),
        ],
        className="contrib-header",
    )

    total = html.Div(
        [
            html.Span(format_money(payload.get("prior_total")), className="contrib-total-from"),
            html.I(className="bi bi-arrow-right"),
            html.Span(format_money(payload.get("current_total")), className="contrib-total-to"),
            html.Span(
                _signed_money(move),
                className="contrib-total-move " + ("up" if (move or 0) >= 0 else "down"),
            ),
        ],
        className="contrib-total",
    )

    rows = [_driver_row(d, widest) for d in shown]
    if len(drivers) > _MAX_DRIVERS:
        rest = len(drivers) - _MAX_DRIVERS
        rows.append(
            html.Div(
                f"+{rest} smaller slice{'s' if rest > 1 else ''} not shown",
                className="contrib-more",
            )
        )

    return html.Div(
        [
            header,
            total,
            html.Div(rows, className="contrib-rows"),
            html.Div(
                [
                    html.I(className="bi bi-calculator"),
                    html.Span(
                        "Computed from the rows behind the answer above — share of "
                        "move can pass 100% when one slice is offset by another."
                    ),
                ],
                className="contrib-foot",
            ),
        ],
        className="message contrib-panel",
    )
