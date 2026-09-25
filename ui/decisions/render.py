"""The Decision Board shell: header, view switch, filters, and the two-pane workspace.

The page is a queue and a brief side by side. Everything above them states what
you are looking at — how many decisions are live, how many are late, which week
the agenda is named for — and everything inside them is painted by
``ui.decisions.callbacks`` so a filter change never rebuilds the chrome.

The three views (Board, List, Agenda) are views over the *same* records, not
filters: switching changes the grouping and nothing about which decisions are in
play. Board is ``ui.decisions.render.board_columns``; the other two are
``ui.decisions.queue``.

Render functions are pure: plain decision dicts (from ``core.store.decisions``)
in, Dash components out. Colours and labels come from ``ui.decisions.model``.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from core.store.decisions import ACTIVE_STATUSES
from ui.decisions import agenda as ag
from ui.decisions import brief, model, queue


# ── Board shell (mounted by the view router) ────────────────────────────────


def decision_board_view() -> html.Div:
    """The full page: header, lede, filters, the week ribbon, and the workspace."""
    return html.Div(
        [
            _header(),
            _lede(),
            _toolbar(),
            html.Div(
                queue.week_ribbon_shell(),
                id="decision-ribbon",
                className=ribbon_class(model.DEFAULT_VIEW),
            ),
            _workspace(),
        ],
        className="decision-board-view",
    )


def ribbon_class(view: str) -> str:
    """The week ribbon belongs to the Agenda; the other two views hide it.

    Hidden rather than unmounted, because its step buttons are callback Inputs
    and a callback cannot fire on a control that is not in the layout.
    """
    return "decision-ribbon" + ("" if view == "agenda" else " decision-ribbon-off")


def _header() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-clipboard-check"),
                    html.Div(
                        [
                            html.H2("Decision Board", className="decision-board-title"),
                            html.Div(
                                "Every decision this analysis led to",
                                className="decision-board-subtitle",
                            ),
                        ],
                    ),
                ],
                className="decision-board-heading",
            ),
            view_switch(model.DEFAULT_VIEW),
            dbc.Button(
                [html.I(className="bi bi-plus-lg me-1"), "New decision"],
                id="decision-new-btn",
                n_clicks=0,
                className="decision-new-btn",
            ),
        ],
        className="decision-board-header",
    )


def view_switch(active: str) -> html.Div:
    """A segmented control over the three readings of the queue.

    Rendered fresh on every switch rather than styled clientside, so the active
    view survives a reload and is readable to a screen reader as a pressed
    button rather than as a colour.
    """
    return html.Div(
        [
            html.Button(
                [html.I(className=view.icon), html.Span(view.label)],
                id={"type": "decision-view", "view": view.key},
                n_clicks=0,
                className="decision-view-btn"
                + (" decision-view-on" if view.key == active else ""),
                title=view.hint,
                **{"aria-pressed": "true" if view.key == active else "false"},
            )
            for view in model.VIEWS
        ],
        id="decision-view-switch",
        className="decision-view-switch",
        role="group",
    )


def _lede() -> html.Div:
    """The page's one sentence, and the two counts a review opens with."""
    return html.Div(
        [
            html.Div(
                [
                    html.H1("Make the next decision clear.", className="decision-lede-title"),
                    html.Div(id="decision-counts", className="decision-lede-counts"),
                ],
            ),
            html.Button(
                id="decision-archive-toggle",
                n_clicks=0,
                className="decision-archive-toggle",
            ),
        ],
        className="decision-board-lede",
    )


def counts_line(active: int, overdue: int) -> list[Any]:
    """"5 active decisions · 1 overdue", with the overdue part set apart.

    Overdue is a separate span because it is the number the reader is actually
    scanning for, and because zero overdue should read as nothing at all rather
    than as a reassuring "0 overdue" they have to parse.
    """
    line: list[Any] = [
        html.Span(f"{active} active {'decision' if active == 1 else 'decisions'}")
    ]
    if overdue:
        line += [
            html.Span(" · ", className="decision-count-sep"),
            html.Span(f"{overdue} overdue", className="decision-count-overdue"),
        ]
    return line


def archive_label(showing_archive: bool, archived: int) -> list[Any]:
    """The archive link's text: into the archive, or back out of it."""
    if showing_archive:
        return [html.I(className="bi bi-arrow-left me-1"), html.Span("Active decisions")]
    return [html.Span(f"Archived ({archived})")]


def _toolbar() -> html.Div:
    return html.Div(
        [
            dbc.Input(
                id="decision-search",
                type="search",
                placeholder="Search decisions…",
                debounce=True,
                className="decision-search",
            ),
            dcc.Dropdown(
                id="decision-filter-owner",
                options=[],
                multi=True,
                placeholder="Owner: anyone",
                className="decision-filter",
            ),
            dcc.Dropdown(
                id="decision-filter-status",
                options=model.status_options(),
                multi=True,
                placeholder="Status",
                className="decision-filter",
            ),
            dcc.Dropdown(
                id="decision-filter-priority",
                options=model.priority_options(),
                multi=True,
                placeholder="Priority",
                className="decision-filter",
            ),
            dcc.Dropdown(
                id="decision-sort",
                options=[
                    {"label": "Due date", "value": "due"},
                    {"label": "Manual order", "value": "manual"},
                    {"label": "Recently updated", "value": "updated"},
                    {"label": "Recently created", "value": "created"},
                    {"label": "Priority", "value": "priority"},
                ],
                value="due",
                clearable=False,
                className="decision-sort",
            ),
        ],
        className="decision-toolbar",
    )


def _workspace() -> html.Div:
    """Queue on the left, the selected decision's brief on the right.

    Both panes are mounted here and only their contents are repainted, so the
    queue keeps its scroll position while the reader works down it.
    """
    return html.Div(
        [
            html.Div(id="decision-board", className="decision-board"),
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-file-earmark-text"),
                            html.Span("Decision brief"),
                        ],
                        className="decision-brief-header",
                    ),
                    html.Div(
                        brief.empty_brief(),
                        id="decision-brief-content",
                        className="decision-brief-scroll",
                    ),
                    brief.brief_actions(),
                ],
                id="decision-brief",
                className="decision-brief",
            ),
        ],
        className="decision-workspace",
    )


# ── Board view: Kanban columns ──────────────────────────────────────────────


def board_columns(
    decisions: list[dict[str, Any]],
    today: date,
    selected: str | None,
    statuses: tuple[str, ...] = ACTIVE_STATUSES,
) -> html.Div:
    """One column per status, in canonical order, each holding its cards.

    Only the active statuses get a column. Archived used to sit here as a fourth,
    which made a finished record compete for width with the work in flight; it
    now has its own view behind the header's archive link.
    """
    by_status: dict[str, list[dict[str, Any]]] = {s: [] for s in statuses}
    for d in decisions:
        by_status.setdefault(d["status"], []).append(d)
    return html.Div(
        [_column(status, by_status.get(status, []), today, selected) for status in statuses],
        className="decision-columns",
    )


def _column(
    status: str, cards: list[dict[str, Any]], today: date, selected: str | None
) -> html.Div:
    meta = model.status_meta(status)
    return html.Div(
        [
            html.Div(
                [
                    html.Span(className=f"decision-dot decision-dot-{meta.color}"),
                    html.Span(meta.label, className="decision-col-title"),
                    html.Span(str(len(cards)), className="decision-col-count"),
                ],
                className="decision-col-header",
            ),
            html.Div(
                [decision_card(d, today, selected) for d in cards]
                or [html.Div("No decisions", className="decision-col-empty")],
                className="decision-col-body",
            ),
        ],
        className=f"decision-col decision-col-{meta.color}",
    )


def decision_card(d: dict[str, Any], today: date, selected: str | None = None) -> html.Div:
    """A colour-coded sticky card. Clicking the body selects it into the brief."""
    meta = model.status_meta(d["status"])
    decision_id = d["id"]
    due = ag.due_state(d.get("due_date"), today)
    footer_bits: list[Any] = [
        html.Span(
            model.priority_label(d["priority"]),
            className=f"decision-prio decision-prio-{model.priority_class(d['priority'])}",
        )
    ]
    if d.get("owner"):
        footer_bits.append(
            html.Span([html.I(className="bi bi-person me-1"), d["owner"]], className="decision-owner")
        )
    footer_bits.append(
        html.Span(
            [html.I(className="bi bi-clock me-1"), due.label or due.date_text],
            className=f"decision-due decision-due-{model.due_class(due.tone)}",
        )
    )

    classes = f"decision-card decision-card-{meta.color}"
    if decision_id == selected:
        classes += " decision-card-selected"
    return html.Div(
        [
            html.Button(
                html.I(className="bi bi-pin-angle-fill" if d["pinned"] else "bi bi-pin-angle"),
                id={"type": "decision-pin", "id": decision_id},
                n_clicks=0,
                className="decision-pin-btn" + (" pinned" if d["pinned"] else ""),
                title="Pin decision",
            ),
            html.Button(
                [
                    html.Div(d["title"], className="decision-card-title"),
                    html.Div(_excerpt(d["statement"]), className="decision-card-statement"),
                ],
                id={"type": "decision-row", "id": decision_id},
                n_clicks=0,
                className="decision-card-open",
            ),
            html.Div(footer_bits, className="decision-card-footer"),
        ],
        className=classes,
    )


def _excerpt(text: str | None, limit: int = 140) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ── Create / edit modal (mounted once in the shell) ─────────────────────────


def decision_modals() -> html.Div:
    """The Decision-Board overlays, mounted once in the app shell.

    Only the editor is an overlay now. Reading a decision happens in the brief
    beside the queue, so the detail off-canvas that used to cover the list is
    gone rather than duplicated.
    """
    return html.Div(
        [
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(id="decision-edit-title")),
                    # Form fields are mounted statically (always in the DOM) so
                    # the save callback's State references never point at a
                    # non-existent object. Opening just pushes values into them.
                    dbc.ModalBody(edit_form(None), id="decision-edit-form"),
                    dbc.ModalFooter(
                        [
                            dbc.Button("Cancel", id="decision-edit-cancel", className="decision-cancel-btn"),
                            dbc.Button("Save decision", id="decision-edit-save", className="decision-save-btn"),
                        ]
                    ),
                ],
                id="decision-edit-modal",
                is_open=False,
                size="lg",
                backdrop="static",
            ),
        ]
    )


# Field value order pushed into the (statically-mounted) form when the editor
# opens. MUST stay in sync with the value Outputs of ``open_editor``.
FORM_VALUE_ORDER = (
    "title", "statement", "rationale", "discussion", "owner",
    "stakeholders", "status", "priority", "decision_date", "due_date",
)


def form_values(d: dict[str, Any] | None) -> tuple[Any, ...]:
    """Ordered field values for ``open_editor`` — defaults when ``d`` is None."""
    d = d or {}
    return (
        d.get("title", ""),
        d.get("statement", ""),
        d.get("rationale", ""),
        d.get("discussion", ""),
        d.get("owner", ""),
        ", ".join(d.get("stakeholders") or []),
        d.get("status", "planned"),
        d.get("priority", "med"),
        d.get("decision_date", ""),
        d.get("due_date", ""),
    )


def edit_form(d: dict[str, Any] | None) -> list[Any]:
    """Form fields for the create/edit modal, prefilled from ``d`` when editing."""
    d = d or {}
    return [
        _input("Title", "decision-f-title", d.get("title", "")),
        _textarea("Decision statement", "decision-f-statement", d.get("statement", "")),
        _textarea("Business rationale", "decision-f-rationale", d.get("rationale", "")),
        _textarea("Discussion points", "decision-f-discussion", d.get("discussion", "")),
        html.Div(
            [
                _input("Owner", "decision-f-owner", d.get("owner", "")),
                _input("Stakeholders (comma-separated)", "decision-f-stakeholders", ", ".join(d.get("stakeholders") or [])),
            ],
            className="decision-form-row",
        ),
        html.Div(
            [
                _select("Status", "decision-f-status", model.status_options(), d.get("status", "planned")),
                _select("Priority", "decision-f-priority", model.priority_options(), d.get("priority", "med")),
            ],
            className="decision-form-row",
        ),
        html.Div(
            [
                _input("Decision date", "decision-f-decision-date", d.get("decision_date", ""), type_="date"),
                _input("Due date", "decision-f-due-date", d.get("due_date", ""), type_="date"),
            ],
            className="decision-form-row",
        ),
        html.Div(id="decision-form-evidence", className="decision-form-evidence"),
    ]


def evidence_preview(items: list[Any]) -> list[Any]:
    """What the editor shows about evidence a draft arrived with.

    Read-only on purpose. The snapshot is what the answer actually said; letting
    it be typed over in the editor would turn a captured figure into a claim.
    """
    if not items:
        return []
    return [
        html.Div("Evidence carried from the analysis", className="decision-form-label"),
        html.Div([brief.evidence_card(item) for item in items], className="decision-evidence-list"),
        html.Div(
            "Captured when this decision was raised, and kept as it was.",
            className="decision-form-hint",
        ),
    ]


def _input(label: str, _id: str, value: Any, type_: str = "text") -> html.Div:
    return html.Div(
        [html.Label(label, className="decision-form-label"), dbc.Input(id=_id, value=value or "", type=type_)],
        className="decision-form-field",
    )


def _textarea(label: str, _id: str, value: Any) -> html.Div:
    return html.Div(
        [html.Label(label, className="decision-form-label"), dbc.Textarea(id=_id, value=value or "", rows=3)],
        className="decision-form-field",
    )


def _select(label: str, _id: str, options: list[dict[str, str]], value: Any) -> html.Div:
    return html.Div(
        [
            html.Label(label, className="decision-form-label"),
            dbc.Select(id=_id, options=options, value=value),
        ],
        className="decision-form-field",
    )
