"""Renderers for the explainable Boardroom widgets.

Roadmap phase 1: every widget here shows a business measure a person can defend
— premium in currency, share of wallet, a named comparison — and never a rating.
That means no normalised 0-100 score AND no High/Medium/Low: both were labels a
reader could not check, and two readers never agreed what one meant. Where a
rating used to sit, the money does, and the rows are ordered by it.

Two conventions run through the whole module:

* **Actual measures.** A value is drawn from its ``*_display`` string when the
  extractor gave one, and formatted from ``*_value`` when it did not, so the
  screen and the exported slide read identically. What the extractor left out is
  computed first by :mod:`core.boardroom.derive`, never guessed at here.
* **Explain in place.** How a figure was arrived at lives beside it in a native
  ``<details>`` drawer, so opening it costs no callback and no re-render.

Rows carry ``data-*`` attributes that ``assets/boardroom_ui.js`` uses to filter
and sort client-side; nothing here depends on that script running.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from dash import html

from core.boardroom import opportunity
from core.boardroom.money import format_money

_TONES = ("good", "warn", "danger", "neutral")

# Presence states, in the language the board reads them in.
_STATUS_LABEL = {
    "no_premium": "No current premium",
    "low_presence": "Low presence",
    "established": "Established",
    "unknown": "",
}
_STATUS_TONE = {
    "no_premium": "warn",
    "low_presence": "neutral",
    "established": "good",
    "unknown": "neutral",
}
# What replaced the severity label: the list is ordered by money at risk, and it
# says so where the "why this priority?" drawer used to be.
_WATCH_ORDER_NOTE = "Ordered by the premium exposed. No severity is assigned — each row states the movement and the periods it was measured over."


def tone(value: Optional[str]) -> str:
    v = (value or "neutral").strip().lower()
    return v if v in _TONES else "neutral"


# ───────────────────────────── shared parts ──────────────────────────────


def _section(title: str, icon: str, body, *, meta: Optional[List[Any]] = None, cls: str = ""):
    """The shell every explainable widget wears: title, optional meta row, body."""
    head = [html.Div([html.I(className=icon), html.Span(title)], className="bm-section-title")]
    if meta:
        head.append(html.Div([m for m in meta if m is not None], className="bm-x-meta"))
    return html.Div(head + [body], className=("bm-widget bm-x " + cls).strip())


def _basis(text: str):
    """The comparison basis chip — every comparison must name its basis."""
    if not (text or "").strip():
        return None
    return html.Span(
        [html.I(className="bi bi-arrow-left-right"), html.Span(text)], className="bm-x-basis"
    )


def _definition(text: str, label: str = "How this is calculated"):
    """A collapsed methodology drawer — open costs no round trip."""
    if not (text or "").strip():
        return None
    return html.Details(
        [
            html.Summary([html.I(className="bi bi-info-circle"), html.Span(label)]),
            html.Div(text, className="bm-x-drawer-body"),
        ],
        className="bm-x-drawer",
    )


def _empty(note: str, fallback: str):
    """The honest empty state: say why, never draw a manufactured widget."""
    return html.Div(
        [html.I(className="bi bi-info-circle"), html.Span((note or "").strip() or fallback)],
        className="bm-x-empty",
    )


def _money(display: str, value: Any) -> str:
    text = (display or "").strip()
    if text:
        return text
    return format_money(value) if value not in (None, "") else "—"


def _pct(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _move_tone(pct: Any) -> str:
    """Green up, red down, neutral when there is no comparable movement."""
    value = _to_number(pct)
    if value is None:
        return ""
    return "good" if value >= 0 else "danger"


def _to_number(value: Any) -> Optional[float]:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _status_pill(status: str):
    label = _STATUS_LABEL.get(status or "unknown", "")
    if not label:
        return None
    return html.Span(label, className=f"bm-x-status {_STATUS_TONE.get(status, 'neutral')}")


# ── plotting helpers, shared by the bubble map and the retired positioning plot ──


def _axis_bounds(
    values: List[float], benchmark: Optional[float], *, floor_at_zero: bool = False
) -> tuple[float, float]:
    """Plot bounds from the real values, padded — never a 0-100 rescale.

    ``floor_at_zero`` for an axis that cannot go negative (a share, a premium):
    padding a 2.2% low into "-4.4%" prints an axis label that cannot exist.
    """
    points = [v for v in values if v is not None]
    if benchmark is not None:
        points = points + [benchmark]
    if not points:
        return 0.0, 1.0
    low, high = min(points), max(points)
    if high == low:
        pad = abs(high) * 0.1 or 1.0
    else:
        pad = (high - low) * 0.15
    low, high = low - pad, high + pad
    return (max(0.0, low), high) if floor_at_zero else (low, high)


# The plot area is inset from the panel edge so a point at the extreme of its
# range still has room for its dot and its label instead of being clipped.
_PLOT_INSET_PCT = 10.0


def _position_pct(value: Optional[float], low: float, high: float) -> float:
    """Where a real value sits in the plot, as a percentage of the inset area."""
    span = 100.0 - 2 * _PLOT_INSET_PCT
    if value is None or high == low:
        return 50.0
    fraction = max(0.0, min(1.0, (value - low) / (high - low)))
    return _PLOT_INSET_PCT + fraction * span


def _axis_tick(text: str, at: float, axis: str):
    style = {"left": f"{at:.1f}%"} if axis == "x" else {"bottom": f"{at:.1f}%"}
    return html.Div(text, className=f"bm-x-tick {axis}", style=style)


def _paired_bar(carrier_value: Any, total_value: Any, *, carrier_text: str, whitespace_text: str):
    """Total = the Marsh book; the filled portion = what the carrier writes.

    Both amounts are printed on the bar: the roadmap's rule is that the colour
    shows presence and the label carries the money.
    """
    total = max(_number(total_value), 0.0)
    held = max(min(_number(carrier_value), total), 0.0)
    held_pct = (held / total * 100.0) if total > 0 else 0.0
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        className="bm-x-bar-held",
                        style={"width": f"{held_pct:.1f}%"},
                        title=f"Carrier premium: {carrier_text}",
                    )
                ],
                className="bm-x-bar-track",
                title=f"Whitespace: {whitespace_text}",
            ),
            html.Div(
                [
                    # Both halves are named. The written half used to be a bare
                    # amount next to a labelled "whitespace" amount, so which
                    # premium a product line was showing had to be inferred.
                    html.Span(
                        [html.I(className="bi bi-shield-check"), f"{carrier_text} written"],
                        className="bm-x-bar-tag held",
                    ),
                    html.Span(
                        [html.I(className="bi bi-slash-square"), f"{whitespace_text} whitespace"],
                        className="bm-x-bar-tag gap",
                    ),
                ],
                className="bm-x-bar-tags",
            ),
        ],
        className="bm-x-bar",
    )


# ───────────────────────── 1. Risk & Watchlist ─────────────────────────


def _exposure_tag(item: Dict[str, Any]):
    """The premium at stake, printed where a severity label used to sit.

    High/Medium/Low was the last unexplained rating on the board: two readers
    never agreed what "Medium" meant, and the label carried no number. The
    amount exposed IS the ranking — the rows are ordered by it — and it needs no
    key to read.
    """
    exposed = _money(item.get("premium_exposed"), item.get("premium_exposed_value"))
    if exposed == "—":
        return None
    return html.Span(exposed, className="bm-x-headline-value", title="Premium exposed")


def _watch_field(label: str, value: str, icon: str = "", value_tone: str = ""):
    """One labelled fact. ``value_tone`` colours the value when it is a movement."""
    if not (value or "").strip():
        return None
    return html.Div(
        [
            html.Span(label, className="bm-x-field-label"),
            html.Span(
                [html.I(className=icon) if icon else None, html.Span(value)],
                className=("bm-x-field-value " + tone(value_tone) if value_tone else "bm-x-field-value"),
            ),
        ],
        className="bm-x-field",
    )


def _watch_item(item: Dict[str, Any]):
    movement = (item.get("movement") or "").strip()
    exposed = _money(item.get("premium_exposed"), item.get("premium_exposed_value"))
    duration = int(_number(item.get("consecutive_periods")) or 1)
    fields = [
        _watch_field("Scope", item.get("scope", ""), "bi bi-crosshair"),
        _watch_field("Premium exposed", exposed, "bi bi-cash-stack"),
        _watch_field(
            "Share of portfolio", _pct(item.get("share_of_portfolio_pct")), "bi bi-diagram-3"
        )
        if item.get("share_of_portfolio_pct") is not None
        else None,
        _watch_field("Movement", movement, "bi bi-graph-down-arrow"),
        _watch_field("Comparison", item.get("comparison", ""), "bi bi-arrow-left-right"),
        _watch_field(
            "Duration",
            f"Adverse for {duration} consecutive periods" if duration > 1 else "Single period",
            "bi bi-hourglass-split",
        ),
        _watch_field("Owner action", item.get("owner_action", ""), "bi bi-person-check"),
    ]
    trigger = (item.get("trigger") or "").strip()
    breach = (item.get("breached_kpi") or "").strip()
    return html.Div(
        [
            html.Div(
                [
                    html.Span(item.get("risk", ""), className="bm-x-row-title"),
                    _exposure_tag(item),
                ],
                className="bm-x-row-head",
            ),
            html.Div([f for f in fields if f is not None], className="bm-x-fields"),
            html.Div([html.I(className="bi bi-flag"), html.Span(trigger)], className="bm-x-trigger")
            if trigger
            else None,
            html.Div([html.I(className="bi bi-bullseye"), html.Span(breach)], className="bm-x-trigger breach")
            if breach
            else None,
        ],
        className=f"bm-x-row watch {tone(item.get('tone'))}",
        **{"data-premium": str(_number(item.get("premium_exposed_value")))},
    )


def render_watchlist(data: Dict[str, Any]):
    """Risk & Watchlist — one row per issue, each carrying its own evidence."""
    watchlist = (data or {}).get("watchlist") or {}
    items = watchlist.get("items") or []
    body = (
        html.Div([_watch_item(i) for i in items], className="bm-x-rows")
        if items
        else _empty(watchlist.get("note"), "No watch item is supported by comparable periods in this data.")
    )
    return _section(
        "Risk & watchlist",
        "bi bi-exclamation-diamond",
        body,
        meta=[_basis(watchlist.get("basis", "")), _definition(_WATCH_ORDER_NOTE, "How this list is ordered")],
        cls="bm-x-watchlist",
    )


# ───────────────────── 2. Product Line Headroom ─────────────────────


def _headroom_row(row: Dict[str, Any]):
    carrier = _money(row.get("carrier_premium"), row.get("carrier_premium_value"))
    marsh = _money(row.get("marsh_premium"), row.get("marsh_premium_value"))
    gap = _money(row.get("whitespace_premium"), row.get("whitespace_premium_value"))
    return html.Div(
        [
            html.Div(
                [
                    html.Span(row.get("product_line", ""), className="bm-x-row-title"),
                    _status_pill(row.get("status", "unknown")),
                    html.Span(gap, className="bm-x-headline-value", title="Whitespace premium"),
                ],
                className="bm-x-row-head",
            ),
            _paired_bar(
                row.get("carrier_premium_value"),
                row.get("marsh_premium_value"),
                carrier_text=carrier,
                whitespace_text=gap,
            ),
            html.Div(
                [
                    f
                    for f in (
                        _watch_field("Marsh premium", marsh, "bi bi-people"),
                        _watch_field("Share of wallet", _pct(row.get("share_of_wallet_pct")), "bi bi-pie-chart"),
                        _watch_field(
                            "Share of portfolio",
                            _pct(row.get("share_of_portfolio_pct")),
                            "bi bi-diagram-3",
                        ),
                        _watch_field("Market movement", row.get("market_change", ""), "bi bi-graph-up-arrow"),
                        _watch_field("Suggested focus", row.get("focus", ""), "bi bi-signpost-2"),
                    )
                    if f is not None
                ],
                className="bm-x-fields",
            ),
        ],
        className="bm-x-row headroom",
        **{"data-whitespace": str(_number(row.get("whitespace_premium_value")))},
    )


def render_headroom(data: Dict[str, Any]):
    """Product Line Headroom — carrier premium inside the Marsh book, in currency."""
    headroom = (data or {}).get("headroom") or {}
    rows = headroom.get("rows") or []
    body = (
        html.Div([_headroom_row(r) for r in rows], className="bm-x-rows")
        if rows
        else _empty(headroom.get("note"), "Premium is not split by product line in this data.")
    )
    return _section(
        "Product line headroom",
        "bi bi-bar-chart-steps",
        body,
        meta=[_basis(headroom.get("basis", "")), _definition(headroom.get("definition", ""), "How whitespace is calculated")],
        cls="bm-x-headroom",
    )


# ───────────────────── 3. Industry Whitespace ─────────────────────


def _band_pill(band: str):
    """The opportunity band, coloured. Absent when the growth rates cannot say."""
    label = opportunity.band_label(band)
    if not label:
        return None
    return html.Span(
        label,
        className=f"bm-x-band {opportunity.band_tone(band)}",
        title=opportunity.band_reason(band),
    )


def _whitespace_row(row: Dict[str, Any]):
    marsh = _money(row.get("marsh_premium"), row.get("marsh_premium_value"))
    carrier = _money(row.get("carrier_premium"), row.get("carrier_premium_value"))
    gap = _money(row.get("whitespace_premium"), row.get("whitespace_premium_value"))
    band = (row.get("opportunity") or "").strip()
    return html.Div(
        [
            html.Div(
                [
                    html.Span(row.get("industry", ""), className="bm-x-row-title"),
                    _band_pill(band),
                    _status_pill(row.get("status", "unknown")),
                    html.Span(gap, className="bm-x-headline-value", title="Whitespace premium"),
                ],
                className="bm-x-row-head",
            ),
            _paired_bar(
                row.get("carrier_premium_value"),
                row.get("marsh_premium_value"),
                carrier_text=carrier,
                whitespace_text=gap,
            ),
            html.Div(
                [
                    f
                    for f in (
                        _watch_field("Marsh premium", marsh, "bi bi-people"),
                        _watch_field("Share of wallet", _pct(row.get("share_of_wallet_pct")), "bi bi-pie-chart"),
                        _watch_field(
                            "Share of portfolio",
                            _pct(row.get("share_of_portfolio_pct")),
                            "bi bi-diagram-3",
                        ),
                        # Whether the unwritten premium is unplaced or simply
                        # written by the peer set changes what to do about it.
                        _watch_field(
                            "Peers hold",
                            _pct(row.get("peer_share_of_wallet_pct")),
                            "bi bi-people-fill",
                        )
                        if row.get("peer_share_of_wallet_pct") is not None
                        else None,
                        _watch_field(
                            "Market movement",
                            row.get("marsh_change", ""),
                            "bi bi-graph-up-arrow",
                            _move_tone(row.get("marsh_change_pct")),
                        ),
                        _watch_field(
                            "Carrier movement",
                            row.get("carrier_change", ""),
                            "bi bi-arrow-up-right",
                            _move_tone(row.get("carrier_change_pct")),
                        ),
                    )
                    if f is not None
                ],
                className="bm-x-fields",
            ),
            html.Div(
                [html.I(className="bi bi-signpost-2"), html.Span(row.get("focus_reason"))],
                className="bm-x-trigger focus",
            )
            if (row.get("focus_reason") or "").strip()
            else None,
        ],
        className=f"bm-x-row whitespace band-{band}" if band else "bm-x-row whitespace",
        **{
            "data-product": (row.get("product_line") or "").strip().lower(),
            "data-whitespace": str(_number(row.get("whitespace_premium_value"))),
            "data-band": band,
        },
    )


def _product_filter(whitespace: Dict[str, Any], rows: List[Dict[str, Any]]):
    """The required product-line filter, applied in the browser.

    Industry Whitespace ranks industries WITHIN a product line, so the filter is
    part of the widget's meaning rather than a convenience — it is rendered even
    when only one product line is present, and it says which one is active.
    """
    options = [str(p).strip() for p in (whitespace.get("product_lines") or []) if str(p).strip()]
    for row in rows:
        product = (row.get("product_line") or "").strip()
        if product and product not in options:
            options.append(product)
    active = (whitespace.get("product_line") or (options[0] if options else "")).strip()
    if not options:
        return html.Span(
            [html.I(className="bi bi-funnel"), html.Span("Product line: not stated in this data")],
            className="bm-x-filter-static",
        )
    return html.Label(
        [
            html.I(className="bi bi-funnel"),
            html.Span("Product line"),
            html.Select(
                [
                    html.Option(p, value=p.lower(), selected=(p.lower() == active.lower()))
                    for p in ["All"] + options
                ],
                className="bm-x-select",
                **{"data-bm-filter": "product"},
            ),
        ],
        className="bm-x-filter",
    )


def render_whitespace(data: Dict[str, Any]):
    """Industry Whitespace — ranked industries where Marsh writes and the carrier does not."""
    whitespace = (data or {}).get("whitespace") or {}
    rows = whitespace.get("rows") or []
    body = (
        html.Div(
            [_whitespace_row(r) for r in rows],
            className="bm-x-rows",
            **{"data-bm-filter-target": "product"},
        )
        if rows
        else _empty(whitespace.get("note"), "No industry dimension is present in this data.")
    )
    empty_hint = html.Div(
        "No industry matches this product line.", className="bm-x-empty", hidden=True,
        **{"data-bm-filter-empty": "product"},
    )
    return _section(
        "Industry whitespace",
        "bi bi-grid-1x2",
        html.Div([body, empty_hint]),
        meta=[
            _product_filter(whitespace, rows) if rows else None,
            _basis(whitespace.get("basis", "")),
            _definition(whitespace.get("definition", ""), "How whitespace is calculated"),
            _definition(opportunity.rule_summary(), "What the colours mean"),
        ],
        cls="bm-x-whitespace",
    )


# ───────────────────── 4. Quarterly Performance ─────────────────────


def _change_tone(row: Dict[str, Any]) -> str:
    change = row.get("change_pct")
    if change in (None, ""):
        return "neutral"
    return "good" if _number(change) >= 0 else "danger"


def _quarter_row(row: Dict[str, Any]):
    complete = bool(row.get("complete", True))
    change_pct = row.get("change_pct")
    change_bits = [
        (row.get("change_currency") or "").strip(),
        f"{_number(change_pct):+.1f}%" if change_pct not in (None, "") else "",
    ]
    change = " / ".join([b for b in change_bits if b]) or "—"
    return html.Div(
        [
            html.Div(
                [
                    html.Span(row.get("quarter", ""), className="bm-x-q-label"),
                    html.Span(
                        "Partial",
                        className="bm-x-status warn",
                        title="Partial quarter — shown, but never compared",
                    )
                    if not complete
                    else None,
                ],
                className="bm-x-q-head",
            ),
            html.Div(_money(row.get("premium"), row.get("premium_value")), className="bm-x-q-value"),
            html.Div(change, className=f"bm-x-q-change {_change_tone(row)}"),
            html.Div(_pct(row.get("share_of_wallet_pct")), className="bm-x-q-sow"),
            html.Div((row.get("rank_change") or "—"), className="bm-x-q-rank"),
            html.Div((row.get("driver") or "—"), className="bm-x-q-driver"),
        ],
        className="bm-x-q-row" + ("" if complete else " partial"),
    )


def render_quarterly(data: Dict[str, Any]):
    """Quarterly Performance — adjacent, complete quarters, with the basis named."""
    quarterly = (data or {}).get("quarterly") or {}
    rows = quarterly.get("rows") or []
    if not rows:
        body = _empty(quarterly.get("note"), "Quarterly history is unavailable for this scope.")
    else:
        header = html.Div(
            [
                html.Div("Quarter", className="bm-x-q-head"),
                html.Div("Premium", className="bm-x-q-value"),
                html.Div("Change", className="bm-x-q-change"),
                html.Div("Share of wallet", className="bm-x-q-sow"),
                html.Div("Rank", className="bm-x-q-rank"),
                html.Div("Main driver", className="bm-x-q-driver"),
            ],
            className="bm-x-q-row is-head",
        )
        body = html.Div([header] + [_quarter_row(r) for r in rows], className="bm-x-q-table")
    return _section(
        "Quarterly performance",
        "bi bi-calendar3-range",
        body,
        meta=[_basis(quarterly.get("basis", ""))],
        cls="bm-x-quarterly",
    )


# ───────────────── 5. Product portfolio map (bubbles) ─────────────────
#
# Two share measures, two denominators, one plot:
#   x  share of WALLET     carrier premium / Marsh premium in the line  (outward)
#   y  share of PORTFOLIO  the line / the carrier's own premium         (inward)
#   r  premium in the line, area-proportional
# The benchmark lines turn the plot into four business readings — see
# `_QUADRANTS` — so a bubble's position is a sentence, not a coordinate.

_BUBBLE_MIN_PX = 22
_BUBBLE_MAX_PX = 74

# (x above benchmark, y above benchmark) -> what that corner means.
_QUADRANTS = {
    (True, True): ("Core strength", "Big share of the book, and winning the wallet"),
    (False, True): ("Over-weight, under-placed", "A big part of the book where the wallet share is thin"),
    (True, False): ("Winning but small", "Strong wallet share in a line the book barely uses"),
    (False, False): ("Low presence", "Little of the book, little of the wallet"),
}


def _bubble_px(value: Any, largest: float) -> float:
    """Bubble diameter, area-proportional to premium (never radius-proportional)."""
    premium = max(_number(value), 0.0)
    if largest <= 0:
        return _BUBBLE_MIN_PX
    scale = (premium / largest) ** 0.5
    return _BUBBLE_MIN_PX + (_BUBBLE_MAX_PX - _BUBBLE_MIN_PX) * scale


def _quadrant_of(bubble: Dict[str, Any], x_bench: Any, y_bench: Any) -> str:
    """The business reading of where a bubble sits, or '' without benchmarks."""
    if x_bench in (None, "") or y_bench in (None, ""):
        return ""
    x, y = bubble.get("share_of_wallet_pct"), bubble.get("share_of_portfolio_pct")
    if x is None or y is None:
        return ""
    title, detail = _QUADRANTS[(_number(x) >= _number(x_bench), _number(y) >= _number(y_bench))]
    return f"{title} — {detail}"


def _bubble(bubble: Dict[str, Any], *, x_low, x_high, y_low, y_high, largest, x_bench, y_bench):
    size = _bubble_px(bubble.get("premium_value"), largest)
    premium = _money(bubble.get("premium"), bubble.get("premium_value"))
    wallet, portfolio = bubble.get("share_of_wallet_pct"), bubble.get("share_of_portfolio_pct")
    quadrant = _quadrant_of(bubble, x_bench, y_bench)
    growth = (bubble.get("growth") or "").strip()
    hover = " · ".join(
        part
        for part in (
            bubble.get("product_line", ""),
            f"Share of wallet {_pct(wallet)}",
            f"Share of portfolio {_pct(portfolio)}",
            f"Premium {premium}",
            growth,
            quadrant,
        )
        if part
    )
    return html.Div(
        [
            html.Div(
                premium,
                className="bm-x-bubble",
                style={"width": f"{size:.0f}px", "height": f"{size:.0f}px"},
            ),
            html.Span(bubble.get("product_line", ""), className="bm-x-bubble-label"),
        ],
        className=f"bm-x-bubble-point {tone(bubble.get('tone'))}",
        style={
            "left": f"{_position_pct(wallet, x_low, x_high):.1f}%",
            "bottom": f"{_position_pct(portfolio, y_low, y_high):.1f}%",
        },
        title=hover,
    )


# How many lines the plot draws. A book with fourteen product lines drew fourteen
# overlapping bubbles and became unreadable — which is the opposite of what a map
# is for. The seven biggest by premium are the book; the rest are named in the
# footnote so nothing is silently hidden, and Product Line Headroom below lists
# every one of them with its numbers.
_MAX_BUBBLES = 7


def _bubble_footnote(hidden: List[Dict[str, Any]]):
    """Names the lines the plot did not draw, so "top 7" is never a silent cut."""
    if not hidden:
        return None
    names = ", ".join(str(b.get("product_line") or "").strip() for b in hidden if b.get("product_line"))
    return html.Div(
        [
            html.I(className="bi bi-three-dots"),
            html.Span(
                f"{len(hidden)} smaller line{'s' if len(hidden) > 1 else ''} not plotted"
                + (f": {names}" if names else "")
                + ". Every line is listed under Product line headroom."
            ),
        ],
        className="bm-x-note",
    )


def render_portfolio_map(data: Dict[str, Any]):
    """Share of wallet against share of portfolio, one bubble per product line.

    The plot is the POSITION of the book — where each line sits against the two
    benchmarks. The numbers behind each line (Marsh premium, the whitespace, the
    suggested focus) are stated once, by Product Line Headroom on the same page.
    This widget used to repeat them underneath the plot as a second row list, so
    the page said the same thing about the same products twice.
    """
    portfolio = (data or {}).get("portfolio_map") or {}
    bubbles = [b for b in (portfolio.get("bubbles") or []) if b]
    if not bubbles:
        return _section(
            "Product portfolio map",
            "bi bi-circle-square",
            _empty(portfolio.get("note"), "Premium is not split by product line in this data."),
            cls="bm-x-portfolio",
        )

    # Biggest premium first, then the cut: the plot is the shape of the book, so
    # the lines that carry it are the ones that have to be legible.
    bubbles.sort(key=lambda b: _number(b.get("premium_value")), reverse=True)
    bubbles, hidden = bubbles[:_MAX_BUBBLES], bubbles[_MAX_BUBBLES:]

    x_bench = portfolio.get("wallet_benchmark_pct")
    y_bench = portfolio.get("portfolio_benchmark_pct")
    # Both axes are percentages of a whole, so neither can pad below zero.
    x_low, x_high = _axis_bounds(
        [b.get("share_of_wallet_pct") for b in bubbles], x_bench, floor_at_zero=True
    )
    y_low, y_high = _axis_bounds(
        [b.get("share_of_portfolio_pct") for b in bubbles], y_bench, floor_at_zero=True
    )
    largest = max((_number(b.get("premium_value")) for b in bubbles), default=0.0)

    # Both axes are drawn AND named. An unlabelled dashed line is a line; a
    # labelled one turns the plot into four quadrants a reader can name — left of
    # the vertical is "below the carrier's average wallet share", above the
    # horizontal is "a bigger part of the book than an even split".
    label = str(portfolio.get("benchmark_label") or "Carrier average").strip()
    lines = []
    if x_bench not in (None, ""):
        at = _position_pct(x_bench, x_low, x_high)
        lines.append(
            html.Div(
                className="bm-x-benchline v",
                style={"left": f"{at:.1f}%"},
                title=f"{label}: {_pct(x_bench)} share of wallet",
            )
        )
        lines.append(
            html.Div(
                f"Avg share of wallet {_pct(x_bench)}",
                className="bm-x-benchlabel v",
                style={"left": f"{at:.1f}%"},
            )
        )
    if y_bench not in (None, ""):
        at = _position_pct(y_bench, y_low, y_high)
        lines.append(
            html.Div(
                className="bm-x-benchline h",
                style={"bottom": f"{at:.1f}%"},
                title=f"{label}: {_pct(y_bench)} share of portfolio",
            )
        )
        lines.append(
            html.Div(
                f"Avg share of portfolio {_pct(y_bench)}",
                className="bm-x-benchlabel h",
                style={"bottom": f"{at:.1f}%"},
            )
        )

    plot = html.Div(
        lines
        + [
            _bubble(
                b, x_low=x_low, x_high=x_high, y_low=y_low, y_high=y_high,
                largest=largest, x_bench=x_bench, y_bench=y_bench,
            )
            for b in bubbles
        ]
        + [
            _axis_tick(_pct(x_low), _PLOT_INSET_PCT, "x"),
            _axis_tick(_pct(x_high), 100 - _PLOT_INSET_PCT, "x"),
            _axis_tick(_pct(y_low), _PLOT_INSET_PCT, "y"),
            _axis_tick(_pct(y_high), 100 - _PLOT_INSET_PCT, "y"),
        ],
        className="bm-x-plot bm-x-bubbleplot",
    )
    body = html.Div(
        [
            html.Div("Share of portfolio — how the book is split", className="bm-x-ylab"),
            html.Div(plot, className="bm-x-plotwrap"),
            html.Div("Share of wallet — how much of Marsh's placement is won", className="bm-x-xlab"),
            html.Div(
                [html.I(className="bi bi-circle-fill"), html.Span("Bubble size = premium in the line")],
                className="bm-x-note",
            ),
            _bubble_footnote(hidden),
            html.Div(portfolio.get("note", ""), className="bm-x-note") if portfolio.get("note") else None,
        ],
        className="bm-x-poswrap",
    )
    return _section(
        "Product portfolio map",
        "bi bi-circle-square",
        body,
        meta=[
            _basis(portfolio.get("basis", "")),
            html.Span(
                [html.I(className="bi bi-rulers"), html.Span(f"Benchmarks: {portfolio.get('benchmark_label', '—')}")],
                className="bm-x-basis",
            )
            if (x_bench is not None or y_bench is not None)
            else None,
            _definition(
                "Share of wallet is the carrier's premium as a percentage of the Marsh book in the "
                "same scope. Share of portfolio is that line as a percentage of the carrier's own "
                "premium. Different denominators — read them separately. Bubble area is premium.",
                "How the two shares differ",
            ),
        ],
        cls="bm-x-portfolio",
    )


# ───────────────── 6. Top carriers ─────────────────


def render_top_carriers(data: Dict[str, Any]):
    """Who leads this scope in the Marsh book, and how each is moving.

    Peer identities arrive anonymised from the evidence boundary, so this widget
    prints whatever label the rows carry and never tries to resolve one.
    """
    standings = (data or {}).get("top_carriers") or {}
    carriers = [c for c in (standings.get("carriers") or []) if c]
    if not carriers:
        return _section(
            "Top carriers",
            "bi bi-bar-chart-line",
            _empty(standings.get("note"), "No carrier comparison is present in this data."),
            cls="bm-x-carriers",
        )
    field_size = standings.get("field_size")
    largest = max((_number(c.get("premium_value")) for c in carriers), default=0.0)

    rows = []
    for index, carrier in enumerate(carriers, start=1):
        rank = carrier.get("rank") or index
        subject = bool(carrier.get("is_subject"))
        premium = _money(carrier.get("premium"), carrier.get("premium_value"))
        width = (_number(carrier.get("premium_value")) / largest * 100.0) if largest > 0 else 0.0
        movement = (carrier.get("movement") or "").strip()
        move_tone = "neutral"
        if carrier.get("movement_pct") not in (None, ""):
            move_tone = "good" if _number(carrier.get("movement_pct")) >= 0 else "danger"
        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                f"#{rank}" + (f" of {field_size}" if field_size else ""),
                                className="bm-x-rank",
                            ),
                            html.Span(carrier.get("carrier", ""), className="bm-x-row-title"),
                            html.Span("This carrier", className="bm-x-status good") if subject else None,
                            html.Span(premium, className="bm-x-headline-value"),
                        ],
                        className="bm-x-row-head",
                    ),
                    html.Div(
                        html.Div(className="bm-x-bar-held", style={"width": f"{width:.1f}%"}),
                        className="bm-x-bar-track",
                    ),
                    html.Div(
                        [
                            f
                            for f in (
                                _watch_field(
                                    "Share of wallet", _pct(carrier.get("share_of_wallet_pct")), "bi bi-pie-chart"
                                ),
                                _watch_field(
                                    "Movement", movement, "bi bi-graph-up-arrow", value_tone=move_tone
                                ),
                            )
                            if f is not None
                        ],
                        className="bm-x-fields",
                    ),
                ],
                className="bm-x-row carrier" + (" is-subject" if subject else ""),
            )
        )
    return _section(
        "Top carriers",
        "bi bi-bar-chart-line",
        html.Div(rows, className="bm-x-rows"),
        meta=[
            html.Span(
                [html.I(className="bi bi-crosshair"), html.Span(standings.get("scope"))],
                className="bm-x-basis",
            )
            if (standings.get("scope") or "").strip()
            else None,
            _basis(standings.get("basis", "")),
            _definition(
                "Ranked by premium within the Marsh book for this scope. Individual peers are "
                "shown anonymised — the numbers are exact, the identities are not disclosed.",
                "How this ranking works",
            ),
        ],
        cls="bm-x-carriers",
    )


# ───────────────── 7. Actual-measure positioning (retired) ─────────────────


def render_positioning_actual(data: Dict[str, Any]):
    """Positioning on the measures themselves, with named benchmark lines."""
    matrix = (data or {}).get("positioning_actual") or {}
    points = [p for p in (matrix.get("points") or []) if p]
    if not points:
        return _section(
            "Positioning",
            "bi bi-crosshair2",
            _empty(matrix.get("note"), "No actual premium and score pair is available for this scope."),
            cls="bm-x-positioning",
        )

    x_bench, y_bench = matrix.get("x_benchmark"), matrix.get("y_benchmark")
    x_low, x_high = _axis_bounds([p.get("x_value") for p in points], x_bench)
    y_low, y_high = _axis_bounds([p.get("y_value") for p in points], y_bench)
    x_unit, y_unit = matrix.get("x_unit", ""), matrix.get("y_unit", "")

    dots = [
        html.Div(
            [
                html.Span(className="bm-x-dot" + (" subject" if p.get("is_subject") else "")),
                html.Span(p.get("label", ""), className="bm-x-dot-label"),
            ],
            className=f"bm-x-point {tone(p.get('tone'))}",
            style={
                "left": f"{_position_pct(p.get('x_value'), x_low, x_high):.1f}%",
                "bottom": f"{_position_pct(p.get('y_value'), y_low, y_high):.1f}%",
            },
            title=(
                f"{p.get('label', '')} — {matrix.get('x_label', 'x')}: "
                f"{p.get('x_display') or p.get('x_value')}, "
                f"{matrix.get('y_label', 'y')}: {p.get('y_display') or p.get('y_value')}"
            ),
        )
        for p in points
    ]
    benchmark_label = matrix.get("benchmark_label", "Peer average")
    lines = []
    if x_bench is not None:
        lines.append(
            html.Div(
                className="bm-x-benchline v",
                style={"left": f"{_position_pct(x_bench, x_low, x_high):.1f}%"},
                title=f"{benchmark_label}: {x_bench}{x_unit}",
            )
        )
    if y_bench is not None:
        lines.append(
            html.Div(
                className="bm-x-benchline h",
                style={"bottom": f"{_position_pct(y_bench, y_low, y_high):.1f}%"},
                title=f"{benchmark_label}: {y_bench}{y_unit}",
            )
        )

    plot = html.Div(
        lines
        + dots
        + [
            _axis_tick(f"{x_low:.1f}{x_unit}", _PLOT_INSET_PCT, "x"),
            _axis_tick(f"{x_high:.1f}{x_unit}", 100 - _PLOT_INSET_PCT, "x"),
            _axis_tick(f"{y_low:.1f}{y_unit}", _PLOT_INSET_PCT, "y"),
            _axis_tick(f"{y_high:.1f}{y_unit}", 100 - _PLOT_INSET_PCT, "y"),
        ],
        className="bm-x-plot",
    )
    body = html.Div(
        [
            html.Div(f"{matrix.get('y_label', 'Broker score')} {y_unit}".strip(), className="bm-x-ylab"),
            html.Div(plot, className="bm-x-plotwrap"),
            html.Div(f"{matrix.get('x_label', 'Share of wallet')} {x_unit}".strip(), className="bm-x-xlab"),
            html.Div(matrix.get("note", ""), className="bm-x-note") if matrix.get("note") else None,
        ],
        className="bm-x-poswrap",
    )
    return _section(
        "Positioning on actual measures",
        "bi bi-crosshair2",
        body,
        meta=[
            html.Span(
                [html.I(className="bi bi-rulers"), html.Span(f"Benchmark: {benchmark_label}")],
                className="bm-x-basis",
            )
            if (x_bench is not None or y_bench is not None)
            else None
        ],
        cls="bm-x-positioning",
    )
