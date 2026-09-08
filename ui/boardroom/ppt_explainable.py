"""PowerPoint renderers for the explainable Boardroom widgets.

Parity is the point: the roadmap requires that "PowerPoint shows the same values
and definitions as the app". So each renderer here draws the same fields, in the
same order, with the same wording as its counterpart in
:mod:`ui.boardroom.widgets_explainable` — including the comparison basis, the
whitespace definition, and the ordering rule under the watchlist.

Each renderer has the export's standard signature
``(slide, x, y, w, h, widget, ctx)`` and draws in inches.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from pptx.enum.text import PP_ALIGN
from pptx.util import Inches

from core.boardroom import opportunity
from core.boardroom.money import format_money
from ui.boardroom.ppt_kit import (
    GRAY,
    LIGHT_BORDER,
    NAVY,
    SOFT_BG,
    WHITE,
    _dot,
    _hex_rgb,
    _para,
    _rect,
    _rounded,
    _set_cell,
    _textbox,
    _tone_color,
)

_STATUS_LABEL = {
    "no_premium": "No current premium",
    "low_presence": "Low presence",
    "established": "Established",
}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(display: str, value: Any) -> str:
    text = (display or "").strip()
    if text:
        return text
    return format_money(value) if value not in (None, "") else "—"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _caption(slide, x, y, w, text: str):
    if not (text or "").strip():
        return
    _, tf = _textbox(slide, x, y, w, 0.2)
    _para(tf, text, size=8.5, italic=True, color=GRAY, first=True)


def _empty(slide, x, y, w, note: str, fallback: str):
    _, tf = _textbox(slide, x, y, w, 0.3)
    _para(tf, (note or "").strip() or fallback, size=9.5, italic=True, color=GRAY, first=True)


def _dot_at(slide, x, y, d, subject: bool, tone: Any):
    """A plotted carrier: the subject in brand navy, everyone else by tone."""
    _dot(slide, x, y, d, _hex_rgb("#001f52") if subject else _tone_color(tone),
         line=WHITE if subject else None)


def _paired_bar(slide, x, y, w, carrier_value: Any, total_value: Any):
    """Full bar = the Marsh book; filled portion = what the carrier writes."""
    total = max(_num(total_value), 0.0)
    held = max(min(_num(carrier_value), total), 0.0)
    _rounded(slide, x, y, w, 0.11, fill=SOFT_BG, line=None, radius=0.5)
    if total > 0 and held > 0:
        _rounded(slide, x, y, max(0.08, w * held / total), 0.11, fill=_tone_color("neutral"),
                 line=None, radius=0.5)


# ───────────────────────── 1. Risk & Watchlist ─────────────────────────


def render_watchlist(slide, x, y, w, h, widget, ctx):
    watchlist = (widget.get("data") or {}).get("watchlist") or {}
    items = watchlist.get("items") or []
    _caption(slide, x, y, w, watchlist.get("basis", ""))
    top = y + (0.22 if watchlist.get("basis") else 0)
    if not items:
        _empty(slide, x, top, w, watchlist.get("note"),
               "No watch item is supported by comparable periods in this data.")
        return

    # A table keeps the slide editable and the columns aligned with the card.
    # There is no Priority column: the board stopped rating these rows High /
    # Medium / Low, so the slide states the exposure and the movement and lets
    # the order (biggest exposure first) carry the ranking.
    cols = ["Risk", "Scope", "Premium exposed", "Movement", "Comparison"]
    widths = [0.26, 0.21, 0.17, 0.15, 0.21]
    shape = slide.shapes.add_table(
        len(items) + 1, len(cols), Inches(x), Inches(top), Inches(w), Inches(min(h - 0.5, 0.34 * (len(items) + 1)))
    )
    table = shape.table
    for j, (col, frac) in enumerate(zip(cols, widths)):
        table.columns[j].width = Inches(w * frac)
        _set_cell(table.cell(0, j), col, size=9, bold=True, fill=SOFT_BG)
    for i, item in enumerate(items, start=1):
        cells = [
            item.get("risk", ""),
            item.get("scope", ""),
            _money(item.get("premium_exposed"), item.get("premium_exposed_value")),
            item.get("movement", ""),
            item.get("comparison", "") or watchlist.get("basis", ""),
        ]
        for j, text in enumerate(cells):
            _set_cell(table.cell(i, j), text, size=8.5, bold=(j == 0), color=NAVY, fill=WHITE)
    # The trigger sentence goes in the notes so the slide can be defended without
    # reprinting a paragraph per row.
    triggers = [f"{item.get('risk', '')}: {item.get('trigger', '')}" for item in items]
    triggers.append("Ordered by premium exposed; no severity is assigned.")
    _note(slide, "Risk & watchlist\n" + "\n".join(triggers))


# ───────────────────── 2. Product Line Headroom ─────────────────────


def _headroom_like_rows(slide, x, y, w, h, rows, *, name_key: str, change_key: str, footer: str):
    """Shared drawing for the two ranked paired-bar widgets."""
    row_h = min(0.72, max(0.42, (h - (0.22 if footer else 0)) / max(len(rows), 1)))
    for i, row in enumerate(rows):
        ry = y + i * row_h
        carrier = _money(row.get("carrier_premium"), row.get("carrier_premium_value"))
        marsh = _money(row.get("marsh_premium"), row.get("marsh_premium_value"))
        gap = _money(row.get("whitespace_premium"), row.get("whitespace_premium_value"))
        _, tf = _textbox(slide, x, ry, w * 0.6, 0.22)
        _para(tf, str(row.get(name_key, "")), size=10, bold=True, color=NAVY, first=True, space_after=0)
        _, tf = _textbox(slide, x + w * 0.6, ry, w * 0.4, 0.22)
        _para(tf, f"{gap} whitespace", size=10, bold=True, color=_tone_color("neutral"),
              first=True, align=PP_ALIGN.RIGHT)
        _paired_bar(slide, x, ry + 0.24, w, row.get("carrier_premium_value"), row.get("marsh_premium_value"))
        detail = [f"Carrier {carrier}", f"Marsh {marsh}"]
        # Both shares, spelled out: they have different denominators, so an
        # abbreviated "share" on a slide is a number nobody can interpret.
        if row.get("share_of_wallet_pct") is not None:
            detail.append(f"Share of wallet {_pct(row.get('share_of_wallet_pct'))}")
        if row.get("share_of_portfolio_pct") is not None:
            detail.append(f"Share of portfolio {_pct(row.get('share_of_portfolio_pct'))}")
        if row.get("peer_share_of_wallet_pct") is not None:
            detail.append(f"Peers hold {_pct(row.get('peer_share_of_wallet_pct'))}")
        if (row.get(change_key) or "").strip():
            detail.append(str(row.get(change_key)))
        status = _STATUS_LABEL.get(row.get("status") or "", "")
        if status:
            detail.append(status)
        band = opportunity.band_label((row.get("opportunity") or "").strip())
        if band:
            detail.append(band)
        _, tf = _textbox(slide, x, ry + 0.38, w, 0.2)
        _para(tf, "  |  ".join(detail), size=8.5, color=GRAY, first=True)
    if footer:
        _caption(slide, x, y + h - 0.2, w, footer)


def render_headroom(slide, x, y, w, h, widget, ctx):
    headroom = (widget.get("data") or {}).get("headroom") or {}
    rows = headroom.get("rows") or []
    if not rows:
        _empty(slide, x, y, w, headroom.get("note"), "Premium is not split by product line in this data.")
        return
    footer = " · ".join(p for p in (headroom.get("basis", ""), headroom.get("definition", "")) if p)
    _headroom_like_rows(slide, x, y, w, h, rows, name_key="product_line",
                        change_key="market_change", footer=footer)


# ───────────────────── 3. Industry Whitespace ─────────────────────


def render_whitespace(slide, x, y, w, h, widget, ctx):
    whitespace = (widget.get("data") or {}).get("whitespace") or {}
    rows = whitespace.get("rows") or []
    product = (whitespace.get("product_line") or "").strip()
    # The product-line filter is part of the widget's meaning, so the slide
    # states which product the ranking is for — exactly as the screen does.
    if product:
        _, tf = _textbox(slide, x, y, w, 0.22)
        _para(tf, f"Product line: {product}", size=9, bold=True, color=GRAY, first=True)
        y, h = y + 0.24, h - 0.24
    if not rows:
        _empty(slide, x, y, w, whitespace.get("note"), "No industry dimension is present in this data.")
        return
    shown = [r for r in rows if not product or (r.get("product_line") or product).lower() == product.lower()]
    # The band is a colour on screen and a word on the slide, but it is the same
    # reading of the same two movements, so the rule travels with it.
    footer = " · ".join(
        p
        for p in (whitespace.get("basis", ""), whitespace.get("definition", ""),
                  opportunity.rule_summary())
        if p
    )
    _headroom_like_rows(slide, x, y, w, h, shown or rows, name_key="industry",
                        change_key="marsh_change", footer=footer)


# ───────────────────── 4. Quarterly Performance ─────────────────────


def render_quarterly(slide, x, y, w, h, widget, ctx):
    quarterly = (widget.get("data") or {}).get("quarterly") or {}
    rows = quarterly.get("rows") or []
    basis = quarterly.get("basis") or ""
    if not rows:
        _empty(slide, x, y, w, quarterly.get("note"), "Quarterly history is unavailable for this scope.")
        return
    _caption(slide, x, y, w, f"Basis: {basis}" if basis else "")
    top = y + (0.22 if basis else 0)
    cols = ["Quarter", "Premium", "Change", "Share of wallet", "Rank", "Main driver"]
    shape = slide.shapes.add_table(
        len(rows) + 1, len(cols), Inches(x), Inches(top), Inches(w),
        Inches(min(max(h - 0.3, 0.5), 0.32 * (len(rows) + 1)))
    )
    table = shape.table
    for j, col in enumerate(cols):
        _set_cell(table.cell(0, j), col, size=9, bold=True, fill=SOFT_BG)
    for i, row in enumerate(rows, start=1):
        change_bits = [
            (row.get("change_currency") or "").strip(),
            f"{_num(row.get('change_pct')):+.1f}%" if row.get("change_pct") not in (None, "") else "",
        ]
        change = " / ".join([b for b in change_bits if b]) or "—"
        complete = bool(row.get("complete", True))
        label = row.get("quarter", "") + ("" if complete else "  (partial)")
        values = [
            label,
            _money(row.get("premium"), row.get("premium_value")),
            change,
            _pct(row.get("share_of_wallet_pct")),
            row.get("rank_change") or "—",
            row.get("driver") or "—",
        ]
        tone = "neutral"
        if row.get("change_pct") not in (None, ""):
            tone = "good" if _num(row.get("change_pct")) >= 0 else "danger"
        for j, text in enumerate(values):
            _set_cell(
                table.cell(i, j), text, size=8.5, bold=(j == 0),
                color=_tone_color(tone) if j == 2 else NAVY,
                fill=SOFT_BG if not complete else WHITE,
            )


# ───────────────── 5. Actual-measure positioning ─────────────────


def _bounds(values: List[Any], benchmark: Any, *, floor_at_zero: bool = False) -> Tuple[float, float]:
    """Padded bounds from the real values; mirrors the on-screen plot exactly."""
    points = [_num(v) for v in values if v not in (None, "")]
    if benchmark not in (None, ""):
        points.append(_num(benchmark))
    if not points:
        return 0.0, 1.0
    low, high = min(points), max(points)
    pad = (abs(high) * 0.1 or 1.0) if high == low else (high - low) * 0.15
    low, high = low - pad, high + pad
    return (max(0.0, low), high) if floor_at_zero else (low, high)


# Matches `_MAX_BUBBLES` on screen — the slide and the board plot the same lines.
MAX_BUBBLES = 7


def render_portfolio_map(slide, x, y, w, h, widget, ctx):
    """Share of wallet (x) against share of portfolio (y), bubble area = premium.

    The two shares have different denominators, so the slide names both axes in
    full — exactly as the screen does — rather than saying "share" twice.
    """
    portfolio = (widget.get("data") or {}).get("portfolio_map") or {}
    bubbles = [b for b in (portfolio.get("bubbles") or []) if b]
    if not bubbles:
        _empty(slide, x, y, w, portfolio.get("note"),
               "Premium is not split by product line in this data.")
        return

    # The same cut the screen makes, for the same reason: fourteen overlapping
    # bubbles is not a map. Every line is listed by Product line headroom.
    bubbles.sort(key=lambda b: _num(b.get("premium_value")), reverse=True)
    bubbles, hidden = bubbles[:MAX_BUBBLES], bubbles[MAX_BUBBLES:]

    x_bench = portfolio.get("wallet_benchmark_pct")
    y_bench = portfolio.get("portfolio_benchmark_pct")
    x_low, x_high = _bounds(
        [b.get("share_of_wallet_pct") for b in bubbles], x_bench, floor_at_zero=True
    )
    y_low, y_high = _bounds(
        [b.get("share_of_portfolio_pct") for b in bubbles], y_bench, floor_at_zero=True
    )
    largest = max((_num(b.get("premium_value")) for b in bubbles), default=0.0)

    plot_h = max(h - 1.5, 1.2)
    plot_w = min(w, plot_h * 1.6)
    px0, py0 = x, y + 0.06
    _rounded(slide, px0, py0, plot_w, plot_h, fill=SOFT_BG, line=LIGHT_BORDER, radius=0.03)

    def px(value):
        span = x_high - x_low or 1.0
        return px0 + 0.25 + (plot_w - 0.5) * (_num(value) - x_low) / span

    def py(value):
        span = y_high - y_low or 1.0
        return py0 + 0.25 + (plot_h - 0.5) * (1 - (_num(value) - y_low) / span)

    # Both benchmark axes, NAMED — the same two lines the board draws, and for
    # the same reason: unlabelled, they are decoration; labelled, they make the
    # plot four quadrants a reader can say out loud.
    if x_bench not in (None, ""):
        _rect(slide, px(x_bench), py0 + 0.04, 0.012, plot_h - 0.08, LIGHT_BORDER)
        _, tf = _textbox(slide, px(x_bench) - 0.6, py0 + 0.02, 1.2, 0.18)
        _para(tf, f"Avg share of wallet {_pct(x_bench)}", size=7, bold=True,
              color=GRAY, first=True, align=PP_ALIGN.CENTER)
    if y_bench not in (None, ""):
        _rect(slide, px0 + 0.04, py(y_bench), plot_w - 0.08, 0.012, LIGHT_BORDER)
        _, tf = _textbox(slide, px0 + 0.08, py(y_bench) - 0.19, 1.5, 0.18)
        _para(tf, f"Avg share of portfolio {_pct(y_bench)}", size=7, bold=True,
              color=GRAY, first=True)

    for bubble in sorted(bubbles, key=lambda b: _num(b.get("premium_value")), reverse=True):
        premium = _num(bubble.get("premium_value"))
        # Area-proportional, like the screen: diameter follows the square root.
        scale = (premium / largest) ** 0.5 if largest > 0 else 0.0
        d = 0.18 + 0.42 * scale
        cx = px(bubble.get("share_of_wallet_pct")) - d / 2
        cy = py(bubble.get("share_of_portfolio_pct")) - d / 2
        _dot_at(slide, cx, cy, d, True, bubble.get("tone"))
        _, tf = _textbox(slide, cx + d + 0.04, cy + d / 2 - 0.1, 1.9, 0.2)
        _para(tf, bubble.get("product_line", ""), size=8.5, bold=True, color=NAVY, first=True)

    caption = "Share of wallet % →   (↑ share of portfolio %)   ·   bubble size = premium"
    if hidden:
        caption += f"   ·   top {MAX_BUBBLES} lines by premium ({len(hidden)} smaller not plotted)"
    _, tf = _textbox(slide, px0, py0 + plot_h + 0.04, plot_w, 0.2)
    _para(tf, caption, size=8, italic=True, color=GRAY, first=True, align=PP_ALIGN.CENTER)

    # No per-line table here. It listed product line, both shares, premium and
    # growth — which is Product Line Headroom's slide, on the same deck, saying
    # the same thing about the same products. The plot is the position; the
    # numbers are stated once.


def render_top_carriers(slide, x, y, w, h, widget, ctx):
    """Who leads the scope in the Marsh book. Peer labels are already anonymised."""
    standings = (widget.get("data") or {}).get("top_carriers") or {}
    carriers = [c for c in (standings.get("carriers") or []) if c]
    if not carriers:
        _empty(slide, x, y, w, standings.get("note"), "No carrier comparison is present in this data.")
        return
    field_size = standings.get("field_size")
    caption = " · ".join(p for p in (standings.get("scope", ""), standings.get("basis", "")) if p)
    _caption(slide, x, y, w, caption)
    top = y + (0.22 if caption else 0)

    cols = ["Rank", "Carrier", "Premium", "Share of wallet", "Movement"]
    shape = slide.shapes.add_table(
        len(carriers) + 1, len(cols), Inches(x), Inches(top), Inches(w),
        Inches(min(max(h - 0.3, 0.5), 0.32 * (len(carriers) + 1))),
    )
    table = shape.table
    for j, col in enumerate(cols):
        _set_cell(table.cell(0, j), col, size=9, bold=True, fill=SOFT_BG)
    for i, carrier in enumerate(carriers, start=1):
        subject = bool(carrier.get("is_subject"))
        rank = carrier.get("rank") or i
        move_tone = "neutral"
        if carrier.get("movement_pct") not in (None, ""):
            move_tone = "good" if _num(carrier.get("movement_pct")) >= 0 else "danger"
        values = [
            f"#{rank}" + (f" of {field_size}" if field_size else ""),
            carrier.get("carrier", ""),
            _money(carrier.get("premium"), carrier.get("premium_value")),
            _pct(carrier.get("share_of_wallet_pct")),
            carrier.get("movement") or "—",
        ]
        for j, text in enumerate(values):
            _set_cell(
                table.cell(i, j), text, size=8.5, bold=subject,
                color=_tone_color(move_tone) if j == 4 else NAVY,
                fill=SOFT_BG if subject else WHITE,
            )


def render_positioning_actual(slide, x, y, w, h, widget, ctx):
    matrix = (widget.get("data") or {}).get("positioning_actual") or {}
    points = [p for p in (matrix.get("points") or []) if p]
    if not points:
        _empty(slide, x, y, w, matrix.get("note"),
               "No actual premium and score pair is available for this scope.")
        return
    x_bench, y_bench = matrix.get("x_benchmark"), matrix.get("y_benchmark")
    x_low, x_high = _bounds([p.get("x_value") for p in points], x_bench)
    y_low, y_high = _bounds([p.get("y_value") for p in points], y_bench)

    note = (matrix.get("note") or "").strip()
    plot_h = h - 0.5 - (0.22 if note else 0)
    plot_w = min(w - 0.3, plot_h * 1.5)
    px0, py0 = x + (w - plot_w) / 2, y + 0.06
    _rounded(slide, px0, py0, plot_w, plot_h, fill=SOFT_BG, line=LIGHT_BORDER, radius=0.03)

    def px(value):
        span = x_high - x_low or 1.0
        return px0 + 0.15 + (plot_w - 0.3) * (_num(value) - x_low) / span

    def py(value):
        span = y_high - y_low or 1.0
        return py0 + 0.15 + (plot_h - 0.3) * (1 - (_num(value) - y_low) / span)

    label = matrix.get("benchmark_label") or "Peer average"
    if x_bench not in (None, ""):
        _rect(slide, px(x_bench), py0 + 0.04, 0.012, plot_h - 0.08, LIGHT_BORDER)
    if y_bench not in (None, ""):
        _rect(slide, px0 + 0.04, py(y_bench), plot_w - 0.08, 0.012, LIGHT_BORDER)

    for p in points:
        subject = bool(p.get("is_subject"))
        d = 0.22 if subject else 0.15
        cx, cy = px(p.get("x_value")) - d / 2, py(p.get("y_value")) - d / 2
        _dot_at(slide, cx, cy, d, subject, p.get("tone"))
        shown = f"{p.get('label', '')}  ({p.get('x_display') or p.get('x_value')}, {p.get('y_display') or p.get('y_value')})"
        _, tf = _textbox(slide, cx + d + 0.02, cy - 0.02, 1.8, 0.2)
        _para(tf, shown, size=8, bold=subject, color=NAVY, first=True)

    axis = (
        f"{matrix.get('x_label', 'Share of wallet')} {matrix.get('x_unit', '')} →   "
        f"(↑ {matrix.get('y_label', 'Broker score')} {matrix.get('y_unit', '')})"
    )
    _, tf = _textbox(slide, px0, py0 + plot_h + 0.04, plot_w, 0.2)
    _para(tf, f"{axis}   ·   benchmark: {label}", size=8, italic=True, color=GRAY,
          first=True, align=PP_ALIGN.CENTER)
    if note:
        _caption(slide, x, y + h - 0.2, w, note)


# ───────────────────────── height estimates ─────────────────────────


def estimate_height(kind: str, data: Dict[str, Any], w_in: float) -> float:
    """Inches this widget needs, mirroring how tall the renderers above draw."""
    if kind == "watchlist":
        items = ((data.get("watchlist") or {}).get("items")) or []
        return 0.5 + 0.34 * (len(items) + 1) if items else 0.6
    if kind == "headroom":
        rows = ((data.get("headroom") or {}).get("rows")) or []
        return 0.4 + 0.72 * len(rows) if rows else 0.6
    if kind == "whitespace":
        rows = ((data.get("whitespace") or {}).get("rows")) or []
        return 0.65 + 0.72 * len(rows) if rows else 0.85
    if kind == "quarterly":
        rows = ((data.get("quarterly") or {}).get("rows")) or []
        return 0.45 + 0.32 * (len(rows) + 1) if rows else 0.6
    if kind == "portfolio_map":
        bubbles = ((data.get("portfolio_map") or {}).get("bubbles")) or []
        return (3.4 + 0.3 * len(bubbles)) if bubbles else 0.6
    if kind == "top_carriers":
        carriers = ((data.get("top_carriers") or {}).get("carriers")) or []
        return (0.45 + 0.32 * (len(carriers) + 1)) if carriers else 0.6
    if kind == "positioning_actual":
        return 3.7
    return 1.2


RENDERERS: Dict[str, Callable] = {
    "watchlist": render_watchlist,
    "portfolio_map": render_portfolio_map,
    "top_carriers": render_top_carriers,
    "headroom": render_headroom,
    "whitespace": render_whitespace,
    "quarterly": render_quarterly,
    "positioning_actual": render_positioning_actual,
}


def _note(slide, text: str) -> None:
    """Append to the slide's speaker notes without clobbering what is there."""
    try:
        frame = slide.notes_slide.notes_text_frame
        frame.text = (frame.text + "\n\n" + text).strip() if frame.text else text
    except Exception:  # noqa: BLE001 - notes are a nicety, never a failure
        pass
