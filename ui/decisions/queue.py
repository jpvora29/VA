"""The decision queue: the week ribbon, the banded agenda, and one decision row.

The Kanban answers "what state is everything in". It does not answer the
question a review meeting actually opens with — "what is due, and what is late"
— because a column sorted by status puts an overdue decision and one due next
month side by side. This module renders the same records as a dated queue: a
week ribbon for context, bands for overdue / this week / next week, and rows
that state owner, status, priority and urgency in words.

Pure presentation. Decision dicts and a ``today`` in, Dash components out; every
date sentence comes from :mod:`ui.decisions.agenda` so the row, the band heading
and the brief can never disagree about what "overdue" means.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from dash import html

from ui.decisions import agenda as ag
from ui.decisions import model

# The row's column template, named once so the header and the rows cannot drift.
_COLUMNS = ("Decision", "Owner", "Status", "Priority", "Due date")


def week_ribbon_shell() -> html.Div:
    """The ribbon's controls, mounted once with the page.

    Only the label, the day cells and the Today button's disabled state are
    repainted. The step buttons are static because a callback Input must exist in
    the layout before it can fire — painting the buttons that drive the callback
    would make the first click on them a no-op.
    """
    return html.Div(
        [
            html.Button(
                html.I(className="bi bi-chevron-left"),
                id="decision-week-prev",
                n_clicks=0,
                className="decision-week-step",
                title="Previous week",
            ),
            html.Div(
                [
                    html.Span(id="decision-week-label", className="decision-week-label"),
                    html.Button(
                        "Today",
                        id="decision-week-today",
                        n_clicks=0,
                        className="decision-week-today",
                        disabled=True,
                        title="Back to the current week",
                    ),
                ],
                className="decision-week-title",
            ),
            html.Div(id="decision-week-days", className="decision-week-days"),
            html.Button(
                html.I(className="bi bi-chevron-right"),
                id="decision-week-next",
                n_clicks=0,
                className="decision-week-step",
                title="Next week",
            ),
        ],
        className="decision-week",
    )


def week_days(week: ag.Week) -> list[html.Div]:
    """Seven day cells, each marking how many decisions fall on it.

    Context, not a filter: the ribbon says which week the bands below are named
    for, and marks the days something falls on. Clicking a day is deliberately
    not a selection — a one-day view of a decision queue is a calendar, and this
    board is not one.
    """
    return [_day_cell(day) for day in week.days]


def _day_cell(day: ag.Day) -> html.Div:
    return html.Div(
        [
            html.Span(day.weekday, className="decision-day-name"),
            html.Span(str(day.number), className="decision-day-number"),
            html.Span("Today" if day.is_today else "", className="decision-day-today"),
            html.Span(
                "" if not day.due_count else "•",
                className="decision-day-dot",
                title=f"{day.due_count} due" if day.due_count else None,
            ),
        ],
        className="decision-day" + (" decision-day-now" if day.is_today else ""),
    )


def column_header() -> html.Div:
    return html.Div(
        [html.Span(name, className="decision-qh-cell") for name in _COLUMNS]
        + [html.Span("", className="decision-qh-cell decision-qh-chevron")],
        className="decision-queue-header",
    )


def agenda_body(
    decisions: Sequence[dict[str, Any]], today: date, week: ag.Week, selected: str | None
) -> html.Div:
    """The queue banded by due date, each band sorted soonest-first."""
    groups = ag.agenda_groups(decisions, today, week)
    if not groups:
        return empty_queue()
    children: list[Any] = [column_header()]
    for group in groups:
        children.append(_band(group))
        children.extend(
            decision_row(d, today, selected) for d in ag.sort_by_due(group.items)
        )
    return html.Div(children, className="decision-queue")


def list_body(
    decisions: Sequence[dict[str, Any]], today: date, selected: str | None
) -> html.Div:
    """The same rows as one flat queue, in whatever order the sort control set."""
    if not decisions:
        return empty_queue()
    return html.Div(
        [column_header()] + [decision_row(d, today, selected) for d in decisions],
        className="decision-queue",
    )


def _band(group: ag.AgendaGroup) -> html.Div:
    return html.Div(
        [
            html.I(className=_BAND_ICONS.get(group.key, "bi bi-circle")),
            html.Span(group.label, className="decision-band-label"),
            html.Span("·", className="decision-band-sep"),
            html.Span(str(group.count), className="decision-band-count"),
        ],
        className=f"decision-band decision-band-{model.due_class(group.tone)}",
    )


_BAND_ICONS = {
    ag.OVERDUE: "bi bi-exclamation-circle-fill",
    "week": "bi bi-clock-fill",
    "next": "bi bi-arrow-right-circle",
    ag.LATER: "bi bi-three-dots",
    ag.NONE: "bi bi-dash-circle",
}


def decision_row(d: dict[str, Any], today: date, selected: str | None) -> html.Button:
    """One decision as a row: title, statement, owner, status, priority, urgency.

    The whole row is the button, because the reader's target is the decision and
    not a link inside it. Selecting paints the brief beside the queue rather than
    navigating away, so the queue never loses its place mid-review.
    """
    due = ag.due_state(d.get("due_date"), today)
    meta = model.status_meta(d["status"])
    classes = ["decision-row", f"decision-row-{model.due_class(due.tone)}"]
    if d["id"] == selected:
        classes.append("decision-row-selected")
    return html.Button(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-pin-angle-fill decision-row-pin")
                            if d.get("pinned")
                            else None,
                            html.Span(d["title"]),
                        ],
                        className="decision-row-title",
                    ),
                    html.Div(_excerpt(d.get("statement")), className="decision-row-statement"),
                ],
                className="decision-row-main",
            ),
            html.Div(owner_chip(d.get("owner")), className="decision-row-owner"),
            html.Div(
                html.Span(meta.label, className=f"decision-pill decision-pill-{meta.color}"),
                className="decision-row-status",
            ),
            html.Div(
                html.Span(
                    model.priority_label(d["priority"]),
                    className=f"decision-prio decision-prio-{model.priority_class(d['priority'])}",
                ),
                className="decision-row-priority",
            ),
            html.Div(due_block(due), className="decision-row-due"),
            html.I(className="bi bi-chevron-right decision-row-chevron"),
        ],
        id={"type": "decision-row", "id": d["id"]},
        n_clicks=0,
        className=" ".join(classes),
    )


def due_block(due: ag.DueState) -> list[Any]:
    """The date, and under it what the date means today."""
    return [
        html.Span(due.date_text, className="decision-due-date"),
        html.Span(due.label, className=f"decision-due-note decision-due-{model.due_class(due.tone)}")
        if due.label and due.tone != ag.NONE
        else None,
    ]


def owner_chip(owner: str | None) -> list[Any]:
    name = (owner or "").strip()
    if not name:
        return [html.Span("Unassigned", className="decision-owner-none")]
    return [html.I(className="bi bi-person"), html.Span(name)]


def empty_queue() -> html.Div:
    return html.Div(
        [
            html.I(className="bi bi-clipboard-check"),
            html.Div("No decisions match this view.", className="decision-empty-title"),
            html.Div(
                "Clear a filter, or raise one from a chat answer with Create decision.",
                className="decision-empty-hint",
            ),
        ],
        className="decision-empty",
    )


def _excerpt(text: str | None, limit: int = 120) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
