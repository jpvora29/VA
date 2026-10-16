"""Which deliverable Generate builds — a full QBR, or the Carrier Executive Summary.

The two share the whole Setup brief (carrier, markets, period, peers, data basis): the
selection picks the DATA, the deliverable picks the DECK. Pure layout and constants; the
callbacks that read the choice live in ``studio.authoring.setup``.
"""
from __future__ import annotations

from typing import Optional, Tuple

from dash import html

REPORT_QBR = "qbr"
REPORT_EXEC_SUMMARY = "exec_summary"
DEFAULT_REPORT = REPORT_QBR

OPTIONS = (
    {"label": "Full QBR", "value": REPORT_QBR},
    {"label": "Executive summary", "value": REPORT_EXEC_SUMMARY},
)

TIP = ("What should Generate build? Full QBR is the complete deck — overall, product and "
       "country sections. Executive summary is a two-page read for carrier executives: a "
       "fact-checked summary paragraph (built from per-product, per-country and overall "
       "analysis) and a portfolio & market detail page with charts, ranks and a line-of-"
       "business table. Both use the same selection below.")

#: The executive summary template's pages: (label, icon, note).
EXEC_PAGES: Tuple[Tuple[str, str, str], ...] = (
    ("Cover", "bi-file-earmark-richtext", "Carrier name and date"),
    ("Executive summary", "bi-chat-square-text",
     "One paragraph from verified product, country and overall findings"),
    ("Portfolio & market detail", "bi-bar-chart",
     "Premium and SoW vs peers by country, rank by country, line-of-business table"),
    ("Back cover", "bi-file-earmark-check", ""),
)


def is_exec_summary(report: Optional[str]) -> bool:
    return str(report or "") == REPORT_EXEC_SUMMARY


def page_count(report: Optional[str]) -> Optional[int]:
    """The executive summary's fixed page count; ``None`` for a QBR (ticks decide it)."""
    return len(EXEC_PAGES) if is_exec_summary(report) else None


def exec_summary_pages_panel() -> html.Div:
    """"What's in your executive summary" — the fixed pages, nothing to tick."""
    rows = [
        html.Div(
            [
                html.I(className=f"bi {icon} qs-slide-icon"),
                html.Div([html.Span(label, className="qs-slide-name"),
                          html.Span(note, className="qs-slide-note") if note else None],
                         className="qs-slide-text"),
            ],
            className="qs-slide-row qs-exec-page",
        )
        for label, icon, note in EXEC_PAGES
    ]
    return html.Div(
        [
            html.Div([html.Span([html.B(str(len(EXEC_PAGES))), " pages"],
                                className="qs-tsec-total"),
                      html.Span([html.B("1"), " AI-written paragraph"],
                                className="qs-tsec-total alt")],
                     className="qs-tsec-summary"),
            html.Div("Every figure is computed from the data; the model only writes the "
                     "summary and every sentence is checked against the figures.",
                     className="qs-tsec-hint"),
            html.Div(rows, className="qs-slide-list"),
        ],
        className="qs-tsec qs-exec-pages",
    )
