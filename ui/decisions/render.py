"""Dash rendering for the Decision Board: toolbar, Kanban columns, sticky cards,
the detail panel, and the create/edit modal.

Render functions are pure: they take plain decision dicts (from
``core.store.decisions``) and return Dash components. All interaction lives in
``ui.decisions.callbacks``. Colours/labels come from ``ui.decisions.model`` so
nothing is hard-coded here.
"""
from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from core.store.decisions import STATUSES
from ui.decisions import model


# ── Board shell (mounted by the view router) ────────────────────────────────


def decision_board_view() -> html.Div:
    """The full board: header, filter toolbar, and the columns container.

    The columns themselves are painted by a callback into ``decision-board`` so
    search / filter / sort re-render without rebuilding the toolbar.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-pin-angle-fill"),
                            html.H2("Decision Board", className="decision-board-title"),
                        ],
                        className="decision-board-heading",
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-plus-lg me-1"), "New decision"],
                        id="decision-new-btn",
                        n_clicks=0,
                        className="decision-new-btn",
                    ),
                ],
                className="decision-board-header",
            ),
            _toolbar(),
            html.Div(id="decision-board", className="decision-board"),
        ],
        className="decision-board-view",
    )


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
                    {"label": "Manual order", "value": "manual"},
                    {"label": "Recently updated", "value": "updated"},
                    {"label": "Recently created", "value": "created"},
                    {"label": "Priority", "value": "priority"},
                    {"label": "Due date", "value": "due"},
                ],
                value="manual",
                clearable=False,
                className="decision-sort",
            ),
        ],
        className="decision-toolbar",
    )


# ── Columns + cards ─────────────────────────────────────────────────────────


def board_columns(decisions: list[dict[str, Any]]) -> list[html.Div]:
    """One column per status, in canonical order, each holding its cards."""
    by_status: dict[str, list[dict[str, Any]]] = {s: [] for s in STATUSES}
    for d in decisions:
        by_status.setdefault(d["status"], []).append(d)
    return [_column(status, by_status.get(status, [])) for status in STATUSES]


def _column(status: str, cards: list[dict[str, Any]]) -> html.Div:
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
                [decision_card(d) for d in cards]
                or [html.Div("No decisions", className="decision-col-empty")],
                className="decision-col-body",
            ),
        ],
        className=f"decision-col decision-col-{meta.color}",
    )


def decision_card(d: dict[str, Any]) -> html.Div:
    """A colour-coded sticky card. Clicking the body opens the detail panel."""
    meta = model.status_meta(d["status"])
    decision_id = d["id"]
    footer_bits: list[Any] = [
        html.Span(
            [html.I(className="bi bi-flag-fill me-1"), model.priority_label(d["priority"])],
            className=f"decision-prio decision-prio-{model.priority_class(d['priority'])}",
        )
    ]
    if d.get("owner"):
        footer_bits.append(html.Span([html.I(className="bi bi-person me-1"), d["owner"]], className="decision-owner"))
    if d.get("due_date"):
        footer_bits.append(html.Span([html.I(className="bi bi-clock me-1"), d["due_date"]], className="decision-due"))

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
                id={"type": "decision-card", "id": decision_id},
                n_clicks=0,
                className="decision-card-open",
            ),
            html.Div(footer_bits, className="decision-card-footer"),
        ],
        className=f"decision-card decision-card-{meta.color}",
    )


def _excerpt(text: str | None, limit: int = 140) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ── Detail panel ────────────────────────────────────────────────────────────


def detail_body(d: dict[str, Any], revisions: list[dict[str, Any]]) -> html.Div:
    """Body of the detail off-canvas: all fields + actions + audit trail."""
    meta = model.status_meta(d["status"])
    return html.Div(
        [
            html.Div(
                [
                    html.Span(meta.label, className=f"decision-badge decision-badge-{meta.color}"),
                    html.Span(
                        model.priority_label(d["priority"]) + " priority",
                        className=f"decision-prio decision-prio-{model.priority_class(d['priority'])}",
                    ),
                ],
                className="decision-detail-badges",
            ),
            html.H3(d["title"], className="decision-detail-title"),
            _field("Decision statement", d.get("statement")),
            _field("Business rationale", d.get("rationale")),
            _field("Discussion points", d.get("discussion")),
            html.Div(
                [
                    _meta_item("Owner", d.get("owner") or "—"),
                    _meta_item("Stakeholders", ", ".join(d.get("stakeholders") or []) or "—"),
                    _meta_item("Decision date", d.get("decision_date") or "—"),
                    _meta_item("Due date", d.get("due_date") or "—"),
                ],
                className="decision-detail-meta",
            ),
            _evidence_block(d.get("evidence") or []),
            _links_block(d.get("links") or {}),
            html.Hr(className="decision-detail-rule"),
            html.H5("Revision history", className="decision-history-title"),
            _history(revisions),
        ],
        className="decision-detail-body",
    )


def reopen_disabled(status: str) -> bool:
    """The Reopen action only applies to archived (terminal) decisions."""
    return status != "archived"


def _field(label: str, value: str | None) -> html.Div:
    if not (value or "").strip():
        return html.Div()
    return html.Div(
        [html.Div(label, className="decision-field-label"), html.Div(value, className="decision-field-value")],
        className="decision-field",
    )


def _meta_item(label: str, value: str) -> html.Div:
    return html.Div(
        [html.Div(label, className="decision-meta-label"), html.Div(value, className="decision-meta-value")],
        className="decision-meta-item",
    )


def _evidence_block(evidence: list[dict[str, Any]]) -> html.Div:
    if not evidence:
        return html.Div()
    items = []
    for e in evidence:
        label = e.get("label") or e.get("url") or "Attachment"
        url = e.get("url")
        items.append(
            html.Li(html.A(label, href=url, target="_blank") if url else label)
        )
    return html.Div(
        [html.Div("Supporting evidence", className="decision-field-label"), html.Ul(items)],
        className="decision-field",
    )


def _links_block(links: dict[str, Any]) -> html.Div:
    chats = links.get("chats") or []
    if not chats:
        return html.Div()
    return html.Div(
        [
            html.Div("Linked chats", className="decision-field-label"),
            html.Ul([html.Li(c.get("title") or c.get("id") if isinstance(c, dict) else str(c)) for c in chats]),
        ],
        className="decision-field",
    )


def _history(revisions: list[dict[str, Any]]) -> html.Div:
    if not revisions:
        return html.Div("No revisions yet.", className="decision-history-empty")
    rows = []
    for r in revisions:
        action = r.get("action") or "updated"
        field = r.get("field")
        summary = {
            "created": "Decision created",
            "status_changed": f"Status → {r.get('new_value')}",
            "reopened": f"Reopened → {r.get('new_value')}",
        }.get(action, f"Updated {field}" if field else "Updated")
        detail = []
        if action in ("updated",) and field not in (None, "status"):
            detail = [html.Span(f"{_short(r.get('old_value'))} → {_short(r.get('new_value'))}", className="decision-history-diff")]
        if r.get("note"):
            detail.append(html.Span(r["note"], className="decision-history-note"))
        rows.append(
            html.Li(
                [
                    html.Span(summary, className="decision-history-summary"),
                    *detail,
                    html.Span(_when(r.get("created_at")), className="decision-history-when"),
                ],
                className="decision-history-item",
            )
        )
    return html.Ul(rows, className="decision-history")


def _short(value: Any, limit: int = 48) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _when(value: str | None) -> str:
    return (value or "").split(".")[0]


# ── Create / edit modal + detail off-canvas (mounted once in the shell) ─────


def decision_modals() -> html.Div:
    """All Decision-Board overlays, mounted once in the app shell."""
    return html.Div(
        [
            dbc.Offcanvas(
                html.Div(
                    [
                        # Scrollable, dynamically-rendered fields + revision history.
                        html.Div(id="decision-detail-content", className="decision-detail-scroll"),
                        # Action bar is mounted statically so its buttons always
                        # exist in the DOM (callbacks reference them as Inputs).
                        html.Div(
                            [
                                dbc.Button(
                                    [html.I(className="bi bi-pencil me-1"), "Edit"],
                                    id="decision-detail-edit",
                                    n_clicks=0,
                                    className="decision-action-btn",
                                ),
                                dbc.Button(
                                    [html.I(className="bi bi-arrow-counterclockwise me-1"), "Reopen"],
                                    id="decision-detail-reopen",
                                    n_clicks=0,
                                    className="decision-action-btn",
                                    disabled=True,
                                ),
                                dbc.Button(
                                    [html.I(className="bi bi-trash me-1"), "Delete"],
                                    id="decision-detail-delete",
                                    n_clicks=0,
                                    className="decision-action-btn decision-action-danger",
                                ),
                            ],
                            className="decision-detail-actions",
                        ),
                    ],
                    className="decision-detail-shell",
                ),
                id="decision-detail",
                title="Decision detail",
                placement="end",
                is_open=False,
                className="decision-detail-canvas",
            ),
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
