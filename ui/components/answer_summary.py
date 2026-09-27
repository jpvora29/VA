"""The top of an answer card: the executive summary band and the section cards.

Reading order for a business reader, and why:

    EXECUTIVE SUMMARY   the answer in one or two sentences, and the four numbers
                        a leader asks for first (premium, change, share of
                        wallet, largest line) — per market when there are several
    THE ANALYSIS        each titled part of the answer as its own card, two to a
                        row; "What it means" and "Watch-outs" as full-width
                        callouts, because they are what the reader acts on

Pure presentation over `ui.answer_layout` (which does the reading) and
`ui.components.deltas` (which colours direction).
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from dash import dcc, html

from ui.answer_layout import ACTION, DEFAULT, RISK, Scorecard, Section
from ui.components.deltas import mark_deltas, mark_line


def _markdown(text: str, class_name: str = "") -> Any:
    return dcc.Markdown(mark_deltas(text), className=class_name or None,
                        dangerously_allow_html=True)


def _money(value: Optional[float], unit: str) -> str:
    if value is None:
        return "—"
    return f"${value:,.1f}{unit}" if unit else f"${value:,.0f}"


def _percent(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _change(value: Optional[float], label: str = "vs prior year") -> Any:
    if value is None:
        return html.Span("No prior year", className="kpi-muted")
    direction = "up" if value > 0 else "down" if value < 0 else "flat"
    arrow = {"up": "▲", "down": "▼", "flat": "■"}[direction]
    return html.Span([html.Span(f"{arrow} {abs(value):.1f}%", className=f"delta delta-{direction}"),
                      html.Span(f" {label}", className="kpi-muted")])


def _tile(label: str, value: Any, note: Any = None, *, icon: str = "") -> Any:
    return html.Div(
        [
            html.Div([html.I(className=f"{icon} kpi-icon") if icon else None, label],
                     className="kpi-label"),
            html.Div(value, className="kpi-value"),
            html.Div(note, className="kpi-note") if note is not None else None,
        ],
        className="kpi-tile",
    )


def _single(card: Scorecard) -> Any:
    tiles = [
        _tile("Marsh book premium" if card.is_market_view else "Premium",
              _money(card.premium, card.unit),
              None if card.is_market_view else _change(card.yoy), icon="bi bi-cash-stack"),
    ]
    if not card.is_market_view:
        tiles.append(_tile("Share of wallet", _percent(card.share_of_wallet),
                           html.Span("of Marsh's book in these lines", className="kpi-muted"),
                           icon="bi bi-bullseye"))
    tiles.append(_tile("Largest line", card.top_line or "—",
                       html.Span(f"{_percent(card.top_share)} of the "
                                 + ("book" if card.is_market_view else "carrier's premium"),
                                 className="kpi-muted"), icon="bi bi-box-seam"))
    if card.extras.get("top_market"):
        tiles.append(_tile("Largest market", card.extras["top_market"],
                           html.Span(f"{_percent(card.extras.get('top_market_share'))} of the "
                                     "carrier's premium", className="kpi-muted"),
                           icon="bi bi-globe2"))
    if card.mover_line:
        tiles.append(_tile("Biggest mover", card.mover_line,
                           _change(card.mover_yoy, "YoY"), icon="bi bi-activity"))
    return html.Div(tiles, className="kpi-row")


def _market_card(card: Scorecard) -> Any:
    return html.Div(
        [
            html.Div([html.I(className="bi bi-geo-alt"), card.market or "All markets"],
                     className="market-card-name"),
            html.Div(_money(card.premium, card.unit), className="market-card-value"),
            html.Div(_change(card.yoy), className="market-card-change")
            if not card.is_market_view else None,
            html.Div(
                [
                    html.Span(f"SoW {_percent(card.share_of_wallet)}")
                    if card.share_of_wallet is not None else None,
                    html.Span(f"{card.top_line} {_percent(card.top_share)}")
                    if card.top_line else None,
                ],
                className="market-card-meta",
            ),
        ],
        className="market-card",
    )


def scorecard_block(cards: Sequence[Scorecard]) -> Optional[Any]:
    """KPI tiles for one scope, or one card per market side by side."""
    if not cards:
        return None
    if len(cards) == 1:
        return _single(cards[0])
    return html.Div([_market_card(card) for card in cards], className="market-cards")


def summary_band(headline: str, standfirst: str, cards: Sequence[Scorecard]) -> Optional[Any]:
    """The executive summary: the answer, then its numbers."""
    tiles = scorecard_block(cards)
    if not (headline or tiles is not None):
        return None
    return html.Div(
        [
            html.Div([html.I(className="bi bi-stars"), "Executive summary"],
                     className="answer-summary-label"),
            html.Div(dcc.Markdown(mark_line(headline.replace("<", "&lt;")),
                                  dangerously_allow_html=True),
                     className="answer-headline") if headline else None,
            html.Div(dcc.Markdown(mark_line(standfirst.replace("<", "&lt;")),
                                  dangerously_allow_html=True),
                     className="answer-standfirst") if standfirst else None,
            tiles,
        ],
        className="answer-summary",
    )


#: More points than this and a section takes the full row.
LONG_SECTION = 5


def section_cards(intro: str, sections: Sequence[Section], body_class: str = "") -> List[Any]:
    """The analysis as cards: intro text, then each titled section."""
    out: List[Any] = []
    if intro:
        out.append(html.Div(_markdown(intro, body_class), className="answer-intro"))
    if not sections:
        return out
    #: A long list reads better across the card than down half of it.
    long = {id(s) for s in sections if s.points > LONG_SECTION}
    plain = [s for s in sections if s.tone == DEFAULT and not s.has_table and id(s) not in long]
    # An odd card out stretches across the row rather than leaving a hole.
    stretch = plain[-1] if len(plain) % 2 == 1 else None
    cards = []
    for section in sections:
        wide = (section.tone in (ACTION, RISK) or section.has_table or section is stretch
                or id(section) in long)
        cards.append(html.Div(
            [
                html.Div([html.I(className=f"{section.icon} answer-section-icon"),
                          html.Span(section.title)], className="answer-section-head"),
                _markdown(section.body, body_class),
            ],
            className=f"answer-section tone-{section.tone}" + (" is-wide" if wide else ""),
        ))
    out.append(html.Div(cards, className="answer-sections"))
    return out
