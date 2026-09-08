""""How this was calculated" — the trust drawer under an answer.

One native ``<details>``: the summary line carries the verification badge, so the
state is readable without opening it, and opening costs no callback and no
re-render. Inside are the four things a reader needs to check a number —

    how the question was interpreted
    which figures were found in the data (and which were not)
    what the business terms mean, from the governed glossary
    how the figures were worked out, as steps in plain English

The unmatched figures are NAMED. A trust panel that only ever says "verified" is
decoration; the moment it can say "I could not find $4.4m in the rows" it starts
being worth opening.

Pure presentation — :mod:`core.answers.provenance` builds the record.
"""
from __future__ import annotations

from typing import Any, Dict, List

from dash import html

from core.answers.provenance import STATE_LABEL, STATE_TONE, UNVERIFIED
from core.answers.steps import describe_all


def verification_badge(state: str):
    """The chip that says whether the prose was checked against the rows."""
    label = STATE_LABEL.get(state, STATE_LABEL[UNVERIFIED])
    tone = STATE_TONE.get(state, "neutral")
    icon = {
        "good": "bi bi-patch-check-fill",
        "warn": "bi bi-exclamation-diamond-fill",
    }.get(tone, "bi bi-dash-circle")
    return html.Span(
        [html.I(className=icon), html.Span(label)],
        className=f"prov-badge {tone}",
    )


def _line(label: str, value: Any):
    return html.Div(
        [html.Span(label, className="prov-label"), html.Span(value, className="prov-value")],
        className="prov-line",
    )


def _figures_section(prov: Dict[str, Any]):
    """What was checked, and — the useful half — what was not found."""
    coverage = prov.get("coverage") or {}
    checkable = int(coverage.get("checkable") or 0)
    supported = int(coverage.get("supported") or 0)
    if not checkable:
        return None

    missing = [
        f for f in (prov.get("figures") or [])
        if f.get("checkable") and not f.get("supported")
    ]
    children = [
        _line("Figures checked", f"{supported} of {checkable} found in the result rows")
    ]
    if missing:
        children.append(
            html.Div(
                [
                    html.I(className="bi bi-search"),
                    html.Span("Not found in the rows: "),
                    html.Span(
                        ", ".join(str(f.get("text")) for f in missing),
                        className="prov-missing-values",
                    ),
                ],
                className="prov-missing",
            )
        )
    return html.Div(children, className="prov-section")


def _terms_section(terms: List[Dict[str, Any]]):
    """The governed meaning of each term the answer used."""
    if not terms:
        return None
    return html.Div(
        [html.Div("What these terms mean", className="prov-heading")]
        + [
            html.Div(
                [
                    html.Span(term.get("label", ""), className="prov-term-label"),
                    html.Span(term.get("definition", ""), className="prov-term-def"),
                    html.Span(f"Computed as {term['formula']}", className="prov-term-formula")
                    if term.get("formula")
                    else None,
                ],
                className="prov-term",
            )
            for term in terms
        ],
        className="prov-section",
    )


def _steps_list(steps: List[str]):
    """The calculation as a numbered list a business reader can follow."""
    return html.Ol(
        [html.Li(step, className="prov-step") for step in steps],
        className="prov-steps",
    )


def _queries_section(queries: List[Dict[str, Any]]):
    """How each figure was arrived at, in steps — with the SQL demoted.

    The panel used to lead with the raw query. That is the wrong artefact for the
    person who needs it: someone asking "can I trust this number?" cannot read a
    SELECT, and showing one says "here is proof you cannot check", which is worse
    than showing nothing. `core.answers.steps` reads the query and describes it;
    the SQL stays available for whoever wants it, one more click down, where a
    technical detail belongs.
    """
    if not queries:
        return None
    blocks = []
    for query in describe_all(queries):
        rows = int(query.get("row_count") or 0)
        steps = query.get("steps") or []
        sql = str(query.get("sql") or "").strip()
        blocks.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(str(query.get("lens") or "query"), className="prov-lens"),
                            html.Span(
                                f"{rows:,} row{'s' if rows != 1 else ''}",
                                className="prov-rows",
                            ),
                        ],
                        className="prov-query-head",
                    ),
                    _steps_list(steps) if steps else None,
                    html.Details(
                        [
                            html.Summary("Show the query", className="prov-sql-summary"),
                            html.Pre(sql, className="prov-sql"),
                        ],
                        className="prov-sql-drawer",
                    )
                    if sql
                    else None,
                ],
                className="prov-query",
            )
        )
    return html.Div(
        [html.Div("How the figures were worked out", className="prov-heading")] + blocks,
        className="prov-section",
    )


def provenance_drawer(prov: Dict[str, Any] | None):
    """The whole panel, or ``None`` when the turn recorded nothing to show."""
    if not prov:
        return None
    sections = [
        _line("Interpreted as", prov["question"]) if prov.get("question") else None,
        # An edited answer says so, and its figures were re-checked against the
        # same rows — the badge describes what is on screen, not what was written.
        _line("Edited", "Rewritten by you; figures re-checked against the data")
        if prov.get("edited")
        else None,
        _figures_section(prov),
        _terms_section(prov.get("terms") or []),
        _queries_section(prov.get("queries") or []),
    ]
    body = [s for s in sections if s is not None]
    if not body:
        return None
    return html.Details(
        [
            html.Summary(
                [
                    verification_badge(str(prov.get("state") or UNVERIFIED)),
                    html.Span("How this was calculated", className="prov-summary-text"),
                    html.I(className="bi bi-chevron-down prov-chevron"),
                ],
                className="prov-summary",
            ),
            html.Div(body, className="prov-body"),
        ],
        className="prov-drawer",
    )
