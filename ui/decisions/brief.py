"""The decision brief: one selected record, read beside the queue it came from.

A review reads a decision and then the next one. The board used to open each in
an off-canvas drawer over the queue, so reviewing meant open, read, close, find
your place, open the next — and the drawer hid the very list it was launched
from. The brief is the same content in a column that stays put: selecting a row
repaints this panel and nothing else moves.

The panel is assembled by :class:`DecisionBriefBuilder`, one ``add_`` per part,
so :func:`decision_brief` reads as the list of what a brief contains.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional, Sequence

import dash_bootstrap_components as dbc
from dash import html

from ui.decisions import agenda as ag
from ui.decisions import evidence as ev
from ui.decisions import model
from ui.decisions import queue


def decision_brief(
    d: dict[str, Any], revisions: Sequence[dict[str, Any]], today: date
) -> html.Div:
    """Everything the brief states about the selected decision, in reading order."""
    return (
        DecisionBriefBuilder(d, today)
        .add_badges()
        .add_heading()
        .add_key_facts()
        .add_evidence()
        .add_narrative()
        .add_people_and_dates()
        .add_history(revisions)
        .build()
    )


def empty_brief() -> html.Div:
    """What the rail says before anything is selected."""
    return html.Div(
        [
            html.I(className="bi bi-clipboard-check decision-brief-empty-icon"),
            html.Div("Select a decision", className="decision-brief-empty-title"),
            html.Div(
                "Its statement, the evidence it was taken on, and its history "
                "open here beside the queue.",
                className="decision-brief-empty-hint",
            ),
        ],
        className="decision-brief-empty",
    )


class DecisionBriefBuilder:
    """Builds the brief's body one section at a time.

    Each ``add_`` owns the whole answer for its section, including "this record
    has nothing to say here" — it appends nothing and returns ``self``, so the
    caller never branches.
    """

    def __init__(self, decision: dict[str, Any], today: date) -> None:
        self._d = decision
        self._today = today
        self._parts: list[Any] = []

    # ── sections ────────────────────────────────────────────────────────────

    def add_badges(self) -> "DecisionBriefBuilder":
        meta = model.status_meta(self._d["status"])
        self._parts.append(
            html.Div(
                [
                    html.Span(meta.label, className=f"decision-pill decision-pill-{meta.color}"),
                    html.Span(
                        model.priority_label(self._d["priority"]) + " priority",
                        className=(
                            "decision-prio decision-prio-"
                            + model.priority_class(self._d["priority"])
                        ),
                    ),
                ],
                className="decision-brief-badges",
            )
        )
        return self

    def add_heading(self) -> "DecisionBriefBuilder":
        self._parts.append(html.H3(self._d["title"], className="decision-brief-title"))
        return self

    def add_key_facts(self) -> "DecisionBriefBuilder":
        """Owner and due date — the two facts a review asks about every record."""
        due = ag.due_state(self._d.get("due_date"), self._today)
        self._parts.append(
            html.Div(
                [
                    _fact("Owner", queue.owner_chip(self._d.get("owner"))),
                    _fact(
                        "Due date",
                        [html.I(className="bi bi-calendar3")] + queue.due_block(due),
                    ),
                ],
                className="decision-brief-facts",
            )
        )
        return self

    def add_evidence(self) -> "DecisionBriefBuilder":
        """The evidence this decision was taken on.

        Headed "Evidence used for this decision" rather than "latest": the block
        is a snapshot captured when the decision was raised, and calling it the
        latest would imply it tracks the dataset. It does not, deliberately —
        replacing the evidence under an approved decision would rewrite the basis
        somebody approved it on.
        """
        items = ev.snapshots(self._d.get("evidence"))
        if not items:
            return self
        self._parts.append(
            html.Div(
                [
                    html.Div(
                        "Evidence used for this decision", className="decision-brief-label"
                    ),
                    html.Div([evidence_card(item) for item in items],
                             className="decision-evidence-list"),
                ],
                className="decision-brief-section",
            )
        )
        return self

    def add_narrative(self) -> "DecisionBriefBuilder":
        self._parts.extend(
            [
                _prose("Decision statement", self._d.get("statement")),
                _prose("Business rationale", self._d.get("rationale")),
                _prose("Discussion points", self._d.get("discussion")),
            ]
        )
        return self

    def add_people_and_dates(self) -> "DecisionBriefBuilder":
        stakeholders = ", ".join(self._d.get("stakeholders") or [])
        self._parts.append(
            html.Div(
                [
                    _meta("Stakeholders", stakeholders or "—"),
                    _meta("Decision date", self._d.get("decision_date") or "—"),
                ],
                className="decision-brief-meta",
            )
        )
        return self

    def add_history(self, revisions: Sequence[dict[str, Any]]) -> "DecisionBriefBuilder":
        """The audit trail, collapsed. It is the answer to "who changed this and
        when" — worth keeping, not worth pushing the statement off the screen."""
        self._parts.append(
            html.Details(
                [
                    html.Summary(
                        [
                            html.I(className="bi bi-clock-history"),
                            html.Span(f"History ({len(revisions)})"),
                        ],
                        className="decision-history-summary-row",
                    ),
                    _history(revisions),
                ],
                className="decision-history-details",
            )
        )
        return self

    def build(self) -> html.Div:
        return html.Div(
            [p for p in self._parts if p is not None], className="decision-brief-body"
        )


# ── Footer: the actions, mounted once so callbacks always find them ─────────


def brief_actions() -> html.Div:
    """The action bar under the brief.

    Status moves through a labelled Select rather than by dragging a card: the
    change is stated, it works from the keyboard, and it writes through the same
    audited path as every other edit.

    Everything starts disabled because the brief starts empty; ``paint_brief``
    enables the bar when there is a record for it to act on.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Move to", className="decision-move-label", htmlFor="decision-move"),
                    dbc.Select(
                        id="decision-move",
                        options=model.status_options(),
                        value=None,
                        disabled=True,
                        className="decision-move-select",
                    ),
                ],
                className="decision-move",
            ),
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="bi bi-pencil me-1"), "Edit details"],
                        id="decision-detail-edit",
                        n_clicks=0,
                        disabled=True,
                        className="decision-primary-btn",
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-arrow-counterclockwise me-1"), "Reopen"],
                        id="decision-detail-reopen",
                        n_clicks=0,
                        className="decision-quiet-btn",
                        disabled=True,
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-trash me-1"), "Delete"],
                        id="decision-detail-delete",
                        n_clicks=0,
                        disabled=True,
                        className="decision-quiet-btn decision-quiet-danger",
                    ),
                ],
                className="decision-brief-buttons",
            ),
        ],
        id="decision-brief-actions",
        className="decision-brief-actions",
    )


def reopen_disabled(status: str | None) -> bool:
    """Reopen only applies to an archived (terminal) decision."""
    return status != "archived"


# ── Small parts ─────────────────────────────────────────────────────────────


def evidence_card(item: ev.EvidenceSnapshot) -> html.Div:
    """One evidence snapshot: the figure, what it measures, and where it came from."""
    return html.Div(
        [
            html.Div(
                [
                    html.Div(item.value, className="decision-evidence-value")
                    if item.value
                    else None,
                    html.Div(
                        [
                            html.Div(item.label, className="decision-evidence-label")
                            if item.label
                            else None,
                            html.Div(item.detail, className="decision-evidence-detail")
                            if item.detail
                            else None,
                        ],
                        className="decision-evidence-text",
                    ),
                ],
                className="decision-evidence-head",
            ),
            _source_line("Scope", item.scope),
            _source_line("Source", item.source),
            html.A(
                [html.Span("View evidence"), html.I(className="bi bi-box-arrow-up-right")],
                href=item.url,
                target="_blank",
                className="decision-evidence-link",
            )
            if item.url
            else None,
        ],
        className="decision-evidence-card",
    )


def _source_line(label: str, value: str) -> Optional[html.Div]:
    if not value:
        return None
    return html.Div(
        [html.Span(f"{label}: ", className="decision-evidence-key"), html.Span(value)],
        className="decision-evidence-line",
    )


def _fact(label: str, value: list[Any]) -> html.Div:
    return html.Div(
        [
            html.Div(label, className="decision-brief-label"),
            html.Div(value, className="decision-brief-fact-value"),
        ],
        className="decision-brief-fact",
    )


def _prose(label: str, value: str | None) -> Optional[html.Div]:
    if not (value or "").strip():
        return None
    return html.Div(
        [
            html.Div(label, className="decision-brief-label"),
            html.Div(value, className="decision-brief-prose"),
        ],
        className="decision-brief-section",
    )


def _meta(label: str, value: str) -> html.Div:
    return html.Div(
        [
            html.Div(label, className="decision-brief-label"),
            html.Div(value, className="decision-brief-meta-value"),
        ],
        className="decision-brief-meta-item",
    )


def _history(revisions: Sequence[dict[str, Any]]) -> html.Div:
    if not revisions:
        return html.Div("No revisions yet.", className="decision-history-empty")
    return html.Ul([_revision(r) for r in revisions], className="decision-history")


def _revision(r: dict[str, Any]) -> html.Li:
    action = r.get("action") or "updated"
    field = r.get("field")
    summary = {
        "created": "Decision created",
        "status_changed": f"Status → {_status_label(r.get('new_value'))}",
        "reopened": f"Reopened → {_status_label(r.get('new_value'))}",
    }.get(action, f"Updated {field}" if field else "Updated")
    detail: list[Any] = []
    if action == "updated" and field not in (None, "status"):
        detail.append(
            html.Span(
                f"{_short(r.get('old_value'))} → {_short(r.get('new_value'))}",
                className="decision-history-diff",
            )
        )
    if r.get("note"):
        detail.append(html.Span(r["note"], className="decision-history-note"))
    return html.Li(
        [
            html.Span(summary, className="decision-history-line"),
            *detail,
            html.Span(_when(r.get("created_at")), className="decision-history-when"),
        ],
        className="decision-history-item",
    )


def _status_label(value: Any) -> str:
    return model.status_meta(str(value or "")).label


def _short(value: Any, limit: int = 48) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _when(value: str | None) -> str:
    return (value or "").split(".")[0]
