""""How this was calculated" — the trust drawer under an answer.

One native ``<details>``: the summary line carries the verification badge, so the
state is readable without opening it, and opening costs no callback and no
re-render.

The drawer is ordered as the reader's questions arrive, which is not the order it
was originally built in:

    1  what we understood you to ask
    2  the steps we took            <- how the number was made
    3  the numbers in this answer   <- whether each one is real
    4  what the terms mean

Steps come BEFORE the figure check because "how was this calculated" is the
question on the summary line — leading with a coverage fraction answered a
question nobody had opened the drawer to ask.

Three things were wrong with the first version, all of them wording rather than
structure, and all reported by a reader rather than found by a test:

* it said "4 of 5 found in the result rows". "Result rows" is the machine's word
  for evidence, and a fraction is a score, not an explanation.
* it listed an unmatched figure under "Not found in the rows:" with nothing
  beside it. A number named as a problem, with no verdict and no advice, leaves
  the reader alarmed and no better informed.
* it ended each block with "12 rows came back", which is the machine's unit. When
  the query grouped by product line, twelve rows are twelve product lines —
  :mod:`core.answers.steps` now says that instead.

Pure presentation — :mod:`core.answers.provenance` builds the record and
:mod:`core.answers.figures` supplies the wording of the check.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from dash import html

from core.answers import figures as fig
from core.answers.provenance import (
    NO_EVIDENCE_NOTE,
    STATE_LABEL,
    STATE_TONE,
    UNVERIFIED,
    checked_figures,
)
from core.answers.steps import UNNAMED_SOURCE, Calculation, describe_all

# A long answer can state twenty figures; past this many the receipt becomes the
# wall it was meant to replace.
_FIGURE_LIMIT = 12


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


def _heading(text: str, hint: str = ""):
    """A section title, and one line saying what the section is for."""
    return html.Div(
        [
            html.Div(text, className="prov-heading"),
            html.Div(hint, className="prov-hint") if hint else None,
        ],
        className="prov-heading-block",
    )


def _question_section(prov: Dict[str, Any]):
    """What the answer understood the question to be."""
    question = str(prov.get("question") or "").strip()
    if not question:
        return None
    return html.Div(
        [
            _heading("What we understood you to ask"),
            html.Div(f"“{question}”", className="prov-question"),
            html.Div(
                [
                    html.I(className="bi bi-pencil-square"),
                    html.Span("You rewrote this answer; its figures were checked again."),
                ],
                className="prov-edited",
            )
            if prov.get("edited")
            else None,
        ],
        className="prov-section",
    )


def _step_list(calculation: Calculation):
    """The steps as a numbered walk-through, ending in what came out.

    The outcome is the LAST entry by construction, and it is marked by position
    rather than by matching its text — the line the reader is looking for should
    not depend on a string comparison holding.
    """
    steps = calculation.all_steps
    last = len(steps) - 1 if calculation.outcome else -1
    return html.Ol(
        [
            html.Li(step, className="prov-step" + (" outcome" if i == last else ""))
            for i, step in enumerate(steps)
        ],
        className="prov-steps",
    )


def _calculation_block(calculation: Calculation):
    """One query: its business name, its steps, and the SQL one click down."""
    return html.Div(
        [
            html.Div(calculation.title, className="prov-source"),
            _step_list(calculation),
            html.Details(
                [
                    html.Summary("Show the technical query", className="prov-sql-summary"),
                    html.Pre(calculation.sql, className="prov-sql"),
                ],
                className="prov-sql-drawer",
            )
            if calculation.sql
            else None,
        ],
        className="prov-query",
    )


def _steps_section(queries: List[Dict[str, Any]]):
    """How the figures were produced, step by step."""
    if not queries:
        return None
    calculations = describe_all(queries)
    hint = (
        "Each step is one thing we did to the data, in the order we did it."
        if len(calculations) == 1
        else "We looked at more than one set of data. Here is what we did to each."
    )
    return html.Div(
        [_heading("The steps we took", hint)]
        + [_calculation_block(c) for c in calculations],
        className="prov-section",
    )


def _figure_row(figure: fig.Figure):
    found = figure.supported
    return html.Div(
        [
            html.Span(figure.text, className="prov-figure-value"),
            html.Span(
                [
                    html.I(className="bi bi-check-circle-fill" if found else "bi bi-question-circle-fill"),
                    html.Span(fig.verdict(figure)),
                ],
                className="prov-figure-verdict " + ("ok" if found else "missing"),
            ),
        ],
        className="prov-figure",
    )


def _figures_section(prov: Dict[str, Any]):
    """Every figure the answer states, with a verdict beside it.

    The list is the point. Naming only the failures made the check feel like a
    warning system; showing every figure with its verdict makes it a receipt, and
    the one line of advice underneath says what an absent figure actually means.
    """
    figures = checked_figures(prov)
    state = str(prov.get("state") or UNVERIFIED)
    if not figures:
        # Two different silences. No evidence at all is the badge's reason;
        # evidence but no checkable figure means the answer simply stated none,
        # and saying "every figure was found" about nothing would be a lie.
        note = NO_EVIDENCE_NOTE if state == UNVERIFIED else fig.summary([])
        return html.Div([_heading("The numbers in this answer"),
                         html.Div(note, className="prov-note")],
                        className="prov-section")

    guidance = fig.advice(figures)
    # A long answer can state twenty figures, and twenty rows turn a receipt back
    # into a wall. The ones that did not match are never dropped — they lead.
    ranked = sorted(figures, key=lambda f: f.supported)
    shown, hidden = ranked[:_FIGURE_LIMIT], ranked[_FIGURE_LIMIT:]
    rest = (
        f"and {len(hidden)} more, all found in the data"
        if all(f.supported for f in hidden)
        else f"and {len(hidden)} more"
    )
    return html.Div(
        [
            _heading("The numbers in this answer", fig.summary(figures)),
            html.Div(
                [_figure_row(f) for f in shown]
                + ([html.Div(rest, className="prov-figure more")] if hidden else []),
                className="prov-figures",
            ),
            html.Div(
                [html.I(className="bi bi-info-circle-fill"), html.Span(guidance)],
                className="prov-missing",
            )
            if guidance
            else None,
        ],
        className="prov-section",
    )


def _term(term: Dict[str, Any]):
    """One governed term: what it means, and how it is worked out."""
    return html.Div(
        [
            html.Div(term.get("label", ""), className="prov-term-label"),
            html.Div(term.get("definition", ""), className="prov-term-def"),
            html.Div(
                [
                    html.Span("Worked out as", className="prov-term-formula-label"),
                    html.Span(_arithmetic(term["formula"])),
                ],
                className="prov-term-formula",
            )
            if term.get("formula")
            else None,
        ],
        className="prov-term",
    )


_AGG_IN_FORMULA = re.compile(r"(?i)\b(sum|avg|mean|count|max|min)\s*\(\s*([^()]*?)\s*\)")
_AGG_WORDS = {
    "sum": "total {}", "avg": "average {}", "mean": "average {}",
    "count": "count of {}", "max": "highest {}", "min": "lowest {}",
}


def _arithmetic(formula: str) -> str:
    """A formula in the symbols and words a business reader reads.

    The glossary writes a formula the way an analyst would — `SUM(Premium) over
    the selected filters` — which is exactly the SQL vocabulary the rest of this
    panel exists to keep out. The definition is governed and stays as written;
    only its rendering changes here.
    """
    text = _AGG_IN_FORMULA.sub(
        lambda m: _AGG_WORDS[m.group(1).lower()].format(m.group(2).lower()),
        str(formula or ""),
    )
    for source, target in (("/", " ÷ "), ("*", " × ")):
        text = text.replace(source, target)
    return " ".join(text.split())


def _terms_section(terms: List[Dict[str, Any]]):
    """The governed meaning of each term the answer used."""
    if not terms:
        return None
    return html.Div(
        [
            _heading(
                "What these terms mean",
                "The agreed ICG definitions, so the words mean the same thing everywhere.",
            )
        ]
        + [_term(term) for term in terms],
        className="prov-section",
    )


def dataset_label(prov: Dict[str, Any] | None, period: str = "") -> str:
    """The data this answer read, named in business words — "Premium · Q2 2026".

    Taken from the first calculation's own title rather than from a table name,
    because the title is already the humanised source (:mod:`core.answers.steps`)
    and the reader should never meet a schema object.
    """
    calculations = describe_all((prov or {}).get("queries") or [])
    source = calculations[0].title if calculations else ""
    # "The data · Q2 2026" tells the reader nothing they did not already know.
    # When the query recorded no lens, the period alone is the honest chip.
    if source == UNNAMED_SOURCE:
        source = ""
    parts = [p for p in (source, (period or "").strip()) if p]
    return " · ".join(parts)


def _dataset_chip(label: str):
    """The source, stated on the closed drawer so it costs no click to read."""
    if not label:
        return None
    return html.Span(
        [html.I(className="bi bi-database"), html.Span(label)],
        className="prov-dataset",
        title=f"This answer was built from {label}",
    )


def provenance_drawer(prov: Dict[str, Any] | None, *, period: str = ""):
    """The whole panel, or ``None`` when the turn recorded nothing to show.

    ``period`` is the timeframe the answer ran under, taken from its own scope.
    It rides on the dataset chip because "which data" and "over what window" are
    one question, and answering half of it on the closed drawer is what sends the
    reader hunting for the other half.
    """
    if not prov:
        return None
    sections = [
        _question_section(prov),
        _steps_section(prov.get("queries") or []),
        _figures_section(prov),
        _terms_section(prov.get("terms") or []),
    ]
    body = [s for s in sections if s is not None]
    if not body:
        return None
    return html.Details(
        [
            html.Summary(
                [
                    html.I(className="bi bi-chevron-right prov-chevron"),
                    html.Span("Source & calculation", className="prov-summary-text"),
                    verification_badge(str(prov.get("state") or UNVERIFIED)),
                    _dataset_chip(dataset_label(prov, period)),
                ],
                className="prov-summary",
            ),
            html.Div(body, className="prov-body"),
        ],
        className="prov-drawer",
    )
