"""Render a :class:`~studio.review.model.ReviewReport` — the Review tab's body.

Deliberately dumb: every judgement was made in :mod:`studio.review`, so nothing here
computes, thresholds or explains. Each builder takes the part of the report it draws and
returns a card, and :func:`review_report_view` lists the cards in reading order — which
is also the order an author works down the page:

    readiness   how much of the deck carries this run's data
    coverage    what the data does and does not support
    reasons     one card per cause, with the pages it affects and how to resolve it
    commentary  which prose boxes were written, and what the writing could not claim
"""
from __future__ import annotations

from typing import Any, List, Sequence, Tuple

from dash import html

from studio.review.commentary import field_reason, lost_claim_families
from studio.review.model import Capability, CauseGroup, ReviewReport

#: How many individual slots a cause card lists before it stops naming them. The pages
#: are always listed; the point of the group is that the slots are interchangeable.
_MAX_LISTED = 6


def review_report_view(report: ReviewReport) -> html.Div:
    """The whole diagnosis, as the cards the Review tab stacks."""
    return html.Div(
        [
            _readiness_card(report),
            _coverage_card(report),
            *_reason_cards(report),
            _commentary_card(report),
        ],
        className="qs-rv",
    )


# ── readiness ────────────────────────────────────────────────────────────────


def _readiness_card(report: ReviewReport) -> html.Div:
    """The headline. What it counts depends on WHICH document is on screen.

    For the editable template doc the honest number is coverage — how much of the
    template carries this run's data. For the assembled deck it is not: what filled
    there is a number in a file now, so there is no denominator, and the number that
    matters is how many placeholders are still in the thing about to be sent.
    """
    scope = " · ".join(p for p in (
        report.subject,
        report.period_label or (f"FY{report.period_year}" if report.period_year else ""),
        f"{report.slides_total - report.slides_hidden} of {report.slides_total} pages",
    ) if p)
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className="bi bi-clipboard2-pulse"), "Deck readiness"],
                             className="qs-panel-title"),
                    html.Div(_headline(report),
                             className="qs-review-score" + (" ok" if report.clean else "")),
                ],
                className="qs-review-head",
            ),
            html.Div(scope, className="qs-rv-scope") if scope else html.Span(),
            _meter(report.coverage_pct()) if report.measures_coverage else html.Span(),
            html.Div(_stats(report), className="qs-rv-stats"),
            html.P(
                "Everything below is computed from the deck you are previewing — nothing "
                "is re-run, so what this says is what the export will contain.",
                className="qs-rv-note",
            ),
        ],
        className="qs-review-card",
    )


def _headline(report: ReviewReport) -> str:
    if report.measures_coverage:
        return f"{report.coverage_pct()}% of values filled"
    if report.clean:
        return "No placeholders left"
    n = report.slots_open
    return f"{n} placeholder{'' if n == 1 else 's'} left"


def _stats(report: ReviewReport) -> List[Any]:
    if report.measures_coverage:
        return [
            _stat(report.slots_filled, "filled from your data", "ok"),
            _stat(report.slots_open, "still as the template", "warn"),
            _stat(len(report.errors()), "to fix before sending", "err"),
        ]
    return [
        _stat(report.slides_total - report.slides_hidden, "pages in the deck", "ok"),
        _stat(report.slots_open, "boxes still showing a placeholder", "warn"),
        _stat(len(report.errors()), "to fix before sending", "err"),
    ]


def _meter(pct: int) -> html.Div:
    return html.Div(
        html.Div(className="qs-rv-meter-fill", style={"width": f"{max(0, min(100, pct))}%"}),
        className="qs-rv-meter",
    )


def _stat(value: int, label: str, tone: str) -> html.Div:
    return html.Div(
        [html.Div(str(value), className=f"qs-rv-stat-num {tone}"),
         html.Div(label, className="qs-rv-stat-lbl")],
        className="qs-rv-stat",
    )


# ── what the data supports ───────────────────────────────────────────────────


def _coverage_card(report: ReviewReport) -> html.Div:
    """Every capability of the run, so an absence is stated rather than inferred."""
    if not report.capabilities:
        return html.Span()
    blocking = {c.id for c in report.blocking_capabilities()}
    return html.Div(
        [
            html.Div([html.I(className="bi bi-database-check"), "What this run's data supports"],
                     className="qs-panel-title"),
            html.P(
                "Each figure on the deck needs something from the data. Where it is not "
                "there, the template's own placeholder is kept rather than a number that "
                "would be wrong.",
                className="qs-rv-note",
            ),
            html.Div([_capability_row(c, c.id in blocking) for c in report.capabilities],
                     className="qs-rv-caps"),
        ],
        className="qs-review-card",
    )


def _capability_row(cap: Capability, blocking: bool) -> html.Div:
    """One capability. A missing one that costs this deck nothing is stated, not alarmed."""
    if cap.available:
        icon, tone = "bi-check-circle-fill", "ok"
    elif blocking:
        icon, tone = "bi-exclamation-triangle-fill", "warn"
    else:
        icon, tone = "bi-dash-circle", "idle"
    return html.Div(
        [
            html.I(className=f"bi {icon} qs-rv-cap-icon {tone}"),
            html.Div(
                [
                    html.Div(cap.label, className="qs-rv-cap-label"),
                    html.Div(cap.detail, className="qs-rv-cap-detail"),
                ],
            ),
            html.Span("affects this deck", className="qs-tf-pill warn") if blocking else html.Span(),
        ],
        className=f"qs-rv-cap {tone}",
    )


# ── one card per reason ──────────────────────────────────────────────────────


def _reason_cards(report: ReviewReport) -> List[Any]:
    """A card per cause — errors first, then the honest data gaps.

    When there is nothing open, ONE card says so; a page of green ticks for checks the
    author never worried about is not reassurance, it is scrolling.
    """
    if report.clean:
        return [_all_clear(report)]
    return [_reason_card(g) for g in (*report.errors(), *report.gaps())]


def _all_clear(report: ReviewReport) -> html.Div:
    blurb = (
        "Every mapped value on every page the deck ships resolved from your data, and "
        "every commentary box was written."
        if report.measures_coverage else
        "No placeholder survived the fill: every box on every page the deck ships "
        "carries a real value, and no commentary box is still showing its 'fill me' mark."
    )
    return html.Div(
        [
            html.Div([html.I(className="bi bi-patch-check-fill"), "Nothing unresolved"],
                     className="qs-panel-title"),
            html.P(blurb, className="qs-rv-note"),
        ],
        className="qs-review-card qs-rv-clear",
    )


def _reason_card(group: CauseGroup) -> html.Div:
    """The cause, what it costs, where, and what to do about it."""
    cause = group.cause
    tone = "err" if cause.severity == "error" else "warn"
    return html.Div(
        [
            html.Div(
                [
                    html.I(className=(
                        "bi bi-exclamation-octagon-fill" if tone == "err"
                        else "bi bi-exclamation-triangle-fill") + f" qs-rv-reason-icon {tone}"),
                    html.Div(cause.title, className="qs-rv-reason-title"),
                    html.Span(_count_label(group), className=f"qs-tf-pill {tone}"),
                ],
                className="qs-rv-reason-head",
            ),
            html.P(cause.why, className="qs-rv-why"),
            _pages_line(group.slides()),
            _slot_list(group.findings),
            _fix_line(cause.fix),
        ],
        className=f"qs-review-card qs-rv-reason {tone}",
    )


def _count_label(group: CauseGroup) -> str:
    n = group.count
    return f"{n} place" if n == 1 else f"{n} places"


def _pages_line(slides: Sequence[int]) -> Any:
    if not slides:
        return html.Span()
    shown = ", ".join(str(s) for s in slides[:12])
    more = "" if len(slides) <= 12 else f" +{len(slides) - 12} more"
    label = "Page" if len(slides) == 1 else "Pages"
    return html.Div([html.Span(f"{label} ", className="qs-rv-k"),
                     html.Span(shown + more, className="qs-rv-v")], className="qs-rv-line")


def _slot_list(findings: Sequence[Any]) -> Any:
    """The individual boxes, so "which one?" does not mean hunting the canvas.

    Shows the words that were actually around the placeholder, because for an unmapped
    slot those words ARE the finding — they are what the mapper had to work with.
    """
    if not findings:
        return html.Span()
    rows = [
        html.Div(
            [
                html.Span(f"p{f.slide_no}", className="qs-rv-slot-page"),
                html.Code(f.token or "—", className="qs-rv-slot-token"),
                html.Span(f.context or (f.role or ""), className="qs-rv-slot-ctx"),
            ],
            className="qs-rv-slot",
        )
        for f in findings[:_MAX_LISTED]
    ]
    if len(findings) > _MAX_LISTED:
        rows.append(html.Div(f"and {len(findings) - _MAX_LISTED} more like it",
                             className="qs-rv-slot more"))
    return html.Div(rows, className="qs-rv-slots")


def _fix_line(fix: str) -> Any:
    if not fix:
        return html.Div(
            [html.I(className="bi bi-info-circle"),
             html.Span("Nothing to change here — this is how the template is meant to work.")],
            className="qs-rv-fix idle",
        )
    return html.Div([html.I(className="bi bi-wrench-adjustable"), html.Span(fix)],
                    className="qs-rv-fix")


# ── commentary ───────────────────────────────────────────────────────────────


def _commentary_card(report: ReviewReport) -> Any:
    """What the writing covered, and what it could not claim.

    The second half is the one authors ask about: commentary is written from the same
    resolved facts the figures come from, so a missing capability is a missing argument,
    not a lazy writer.
    """
    lost = lost_claim_families(report.capabilities)
    ledger = report.commentary_fields
    if not report.commentary and not lost and not ledger:
        return html.Span()
    return html.Div(
        [
            html.Div(
                [
                    html.Div([html.I(className="bi bi-chat-square-quote"), "Commentary"],
                             className="qs-panel-title"),
                    _ledger_score(ledger) if ledger else _commentary_score(report),
                ],
                className="qs-review-head",
            ),
            _unwritten_line(report) if report.commentary or not ledger else html.Span(),
            _field_list(ledger, lost) if ledger else _no_ledger_note(report),
            _lost_claims(lost),
        ],
        className="qs-review-card qs-rv-commentary",
    )


# ── the commentary fields, one by one ────────────────────────────────────────

_STATUS_CHIP = {
    "empty": ("Not populated", "err", "bi-x-circle-fill"),
    "draft": ("Standard wording", "warn", "bi-dash-circle-fill"),
    "written": ("Written", "ok", "bi-check-circle-fill"),
}


def _ledger_score(ledger) -> Any:
    written = sum(1 for f in ledger if f.populated)
    empty = len(ledger) - written
    return html.Div(f"{written} of {len(ledger)} fields populated",
                    className="qs-review-score" + ("" if empty else " ok"))


def _no_ledger_note(report: ReviewReport) -> Any:
    if report.source != "assembled":
        return html.Span()
    return html.P("This deck was built before Studio recorded each commentary field. "
                  "Generate it again to see which fields were populated.",
                  className="qs-rv-note")


def _field_row(outcome, lost: Tuple[str, ...]) -> html.Button:
    label, tone, icon = _STATUS_CHIP.get(outcome.status, _STATUS_CHIP["written"])
    where = " · ".join(p for p in (outcome.block, outcome.page) if p)
    return html.Button(
        [
            html.Span(f"p{outcome.slide_no}", className="qs-rv-field-page"),
            html.Span(
                [html.Span(outcome.field, className="qs-rv-field-name"),
                 html.Span(where, className="qs-rv-field-where")],
                className="qs-rv-field-main",
            ),
            html.Span([html.I(className=f"bi {icon}"), label],
                      className=f"qs-rv-field-chip {tone}"),
            html.Span(field_reason(outcome, lost), className="qs-rv-field-why")
            if outcome.status != "written" else None,
        ],
        id={"type": "qs-rv-open", "slide": max(0, outcome.slide_no - 1), "role": outcome.role,
            "block": outcome.block},
        n_clicks=0, className=f"qs-rv-field is-{outcome.status}",
        title="Open this page on the Canvas",
    )


def _field_list(ledger, lost: Tuple[str, ...]) -> Any:
    """Every commentary field: the ones not populated first, then the rest, by page."""
    missing = [f for f in ledger if not f.populated]
    standard = [f for f in ledger if f.status == "draft"]
    written = [f for f in ledger if f.status == "written"]
    blocks = []
    if missing:
        blocks.append(html.Div(f"Not populated ({len(missing)})", className="qs-rv-sub"))
        blocks.append(html.Div([_field_row(f, lost) for f in missing], className="qs-rv-fields"))
    else:
        blocks.append(html.P("Every commentary field in the deck carries text.",
                             className="qs-rv-note"))
    rest = standard + written
    if rest:
        blocks.append(html.Details(
            [html.Summary(f"Populated fields ({len(rest)})", className="qs-rv-sub qs-rv-more"),
             html.Div([_field_row(f, lost) for f in sorted(rest, key=lambda o: o.slide_no)],
                      className="qs-rv-fields")],
            open=not missing,
        ))
    return html.Div(blocks, className="qs-rv-fieldwrap")


def _commentary_score(report: ReviewReport) -> Any:
    """The count, when there IS a denominator.

    There is one for the editable template doc, whose manifest names every prose box.
    There is none for the assembled deck: a box the writer filled is ordinary text in
    the file by then and cannot be told from the template's own copy, so only the
    UNWRITTEN ones are visible — and "0 of 0 written" would be a lie in both directions.
    """
    unwritten = sum(1 for c in report.commentary if not c.filled)
    if not report.measures_coverage:
        if not unwritten:
            return html.Div("No box left unwritten", className="qs-review-score ok")
        return html.Div(f"{unwritten} box(es) unwritten", className="qs-review-score")
    written, total = report.commentary_written(), len(report.commentary)
    return html.Div(f"{written} of {total} boxes written",
                    className="qs-review-score" + (" ok" if written == total else ""))


def _unwritten_line(report: ReviewReport) -> Any:
    missing = [c for c in report.commentary if not c.filled]
    if not missing:
        return html.P(
            "Every prose box on every page the deck ships was replaced with commentary "
            "written from this run's facts.", className="qs-rv-note")
    pages = ", ".join(str(n) for n in sorted({c.slide_no for c in missing}))
    return html.P(
        f"{len(missing)} box(es) on page(s) {pages} were not written, so they still carry "
        "the example commentary the template was authored with. Those pages are not safe "
        "to send.", className="qs-rv-note err")


def _lost_claims(lost: Tuple[str, ...]) -> Any:
    if not lost:
        return html.Span()
    return html.Div(
        [
            html.Div("What the commentary could not argue", className="qs-rv-sub"),
            html.P(
                "Commentary is written only from facts that resolved, and never states a "
                "comparison it cannot evidence. Without the data below, no column anywhere "
                "in the deck can make these points:",
                className="qs-rv-note",
            ),
            html.Ul([html.Li(family) for family in lost], className="qs-rv-lost"),
        ],
        className="qs-rv-lostwrap",
    )


__all__ = ["review_report_view"]
