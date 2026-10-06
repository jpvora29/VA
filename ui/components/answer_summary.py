"""The reading bands of an answer card.

Reading order for a business reader, and why:

    SUMMARY             the answer in one or two sentences, with the three
                        numbers a leader asks for first (premium, change, share
                        of wallet) beside it — per market when there are several
    KEY TAKEAWAYS       each titled part of the answer as ONE numbered row, its
                        deciding figure as a chip on the right; a watch-out is a
                        row with an amber chip, not a separate box
    RECOMMENDED NEXT    "What it means" / "What to do", set after the evidence
    STEP                because it is what the reader acts on last

Pure presentation over `ui.answer_layout` (which does the reading) and
`ui.components.deltas` (which colours direction).
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from dash import html

from ui.answer_layout import (Badge, Scorecard, Section, badge_for, is_per_line,
                               split_points, takeaways_and_next_steps)
from ui.components.answer_markdown import answer_markdown


def _markdown(text: str, class_name: str = "") -> Any:
    # One HTML block, so the coloured ▲/▼ spans reach the page
    # (see ui.components.answer_markdown).
    return answer_markdown(text, class_name)


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


def _stat(label: str, value: Any, note: Any = None, *, tone: str = "") -> Any:
    return html.Div(
        [
            html.Div(label, className="sum-stat-label"),
            html.Div(value, className="sum-stat-value" + (f" is-{tone}" if tone else "")),
            html.Div(note, className="sum-stat-note") if note is not None else None,
        ],
        className="sum-stat",
    )


def _direction(value: Optional[float]) -> str:
    return "" if value is None else "up" if value > 0 else "down" if value < 0 else "flat"


def summary_stats(card: Scorecard) -> Any:
    """The three numbers beside the summary: size, movement, standing."""
    if card.is_market_view:
        stats = [
            _stat("Marsh book premium", _money(card.premium, card.unit)),
            _stat("Largest line", card.top_line or "—",
                  f"{_percent(card.top_share)} of the book" if card.top_line else None),
        ]
        return html.Div(stats, className="sum-stats")
    tone = _direction(card.yoy)
    arrow = {"up": "▲ ", "down": "▼ ", "flat": ""}.get(tone, "")
    stats = [
        _stat("Premium", _money(card.premium, card.unit)),
        _stat("Change", f"{arrow}{abs(card.yoy):.1f}%" if card.yoy is not None else "—",
              "vs prior year" if card.yoy is not None else "No prior year", tone=tone),
    ]
    if card.share_of_wallet is not None:
        stats.append(_stat("Share of wallet", _percent(card.share_of_wallet), "of Marsh's book"))
    elif card.top_line:
        stats.append(_stat("Largest line", card.top_line,
                           f"{_percent(card.top_share)} of premium"))
    return html.Div(stats, className="sum-stats")


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
    """The summary: the answer on the left, its numbers on the right.

    One scope puts its three stats beside the text, so the band is read in one
    sweep; several markets put one card per market under it instead.
    """
    if not (headline or cards):
        return None
    side = summary_stats(cards[0]) if len(cards) == 1 else None
    below = scorecard_block(cards) if len(cards) > 1 else None
    text = html.Div(
        [
            html.Div("Summary", className="answer-summary-label"),
            html.Div(answer_markdown(headline, inline=True),
                     className="answer-headline") if headline else None,
            html.Div(answer_markdown(standfirst, inline=True),
                     className="answer-standfirst") if standfirst else None,
        ],
        className="answer-summary-text",
    )
    return html.Div(
        [html.Div([text, side], className="answer-summary-row" + (" has-stats" if side else "")),
         below],
        className="answer-summary",
    )


def _band_label(text: str) -> Any:
    return html.Div(text, className="answer-band-label")


def _single_point(body: str) -> str:
    """A one-point section reads as a sentence, not as a one-item list."""
    lines = [line for line in body.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].lstrip()[:2] in ("- ", "* ", "+ "):
        return lines[0].lstrip()[2:]
    return body


def _chip(badge: Optional[Badge]) -> Any:
    if badge is None:
        return None
    icon = "bi bi-exclamation-triangle-fill" if badge.tone == "warn" else ""
    return html.Div([html.I(className=icon) if icon else None, html.Span(badge.text)],
                    className=f"takeaway-chip is-{badge.tone}")


def _as_list(points: Sequence[str]) -> str:
    """Points back to Markdown: list items, with a table left as a table."""
    return "\n\n".join(p if p.startswith("|") else f"- {p}" for p in points)


def _more(points: Sequence[str], body_class: str) -> Any:
    """The rest of a takeaway's points, one click away."""
    if not points:
        return None
    label = f"{len(points)} more point" + ("" if len(points) == 1 else "s")
    return html.Details(
        [html.Summary([html.Span(label), html.I(className="bi bi-chevron-down")],
                      className="takeaway-more-toggle"),
         _markdown(_as_list(points), body_class)],
        className="takeaway-more",
    )


def _takeaway(number: int, section: Section, body_class: str) -> Any:
    """One finding: its title, its lead sentence, its chip — the rest folded."""
    points = split_points(section.body)
    lead, rest = (points[0], points[1:]) if points else (section.body, [])
    return html.Div(
        [
            html.Div(str(number), className="takeaway-num"),
            html.Div(
                [
                    html.Div(section.title, className="takeaway-title"),
                    _markdown(lead, body_class + " takeaway-lead"),
                    _more(rest, body_class),
                ],
                className="takeaway-text",
            ),
            _chip(badge_for(section)),
        ],
        className=f"takeaway tone-{section.tone}",
    )


def _detail(section: Section, body_class: str) -> Any:
    """A per-line list ("By product") — the position table holds the same rows,
    so it is offered closed, under the takeaways."""
    count = len(split_points(section.body))
    return html.Details(
        [html.Summary([html.I(className="bi bi-list-ul"), html.Span(section.title),
                       html.Span(f"{count} lines", className="answer-detail-count"),
                       html.I(className="bi bi-chevron-down")],
                      className="answer-detail-toggle"),
         _markdown(section.body, body_class)],
        className="answer-detail",
    )


def takeaway_list(intro: str, sections: Sequence[Section], body_class: str = "") -> List[Any]:
    """The findings as numbered rows (title, lead sentence, chip; the rest
    folded), then any per-line detail lists, closed."""
    findings, _steps = takeaways_and_next_steps(sections)
    rows = [s for s in findings if not is_per_line(s)]
    details = [s for s in findings if is_per_line(s)]
    out: List[Any] = []
    if intro:
        out.append(html.Div(_markdown(intro, body_class), className="answer-intro"))
    if rows:
        out.append(_band_label("Key takeaways"))
        out.append(html.Div([_takeaway(i, s, body_class) for i, s in enumerate(rows, 1)],
                            className="takeaways"))
    out.extend(_detail(s, body_class) for s in details)
    return out


def next_step_band(sections: Sequence[Section], body_class: str = "") -> Optional[Any]:
    """"What it means" / "What to do", as the recommended next step."""
    _findings, steps = takeaways_and_next_steps(sections)
    if not steps:
        return None
    return html.Div(
        [_band_label("Recommended next step")]
        + [_markdown(_single_point(step.body), body_class) for step in steps],
        className="answer-next-step",
    )
