"""Display formatting helpers for the Studio renderers.

Pure string/number shaping — kept separate so the renderers stay about layout and
these stay about how a premium / percent / delta reads in a boardroom.
"""
from __future__ import annotations

from typing import Optional


def money(value: float, *, currency: str = "USD") -> str:
    """Compact currency: 57.6M / 1.2B / 940K, with a sensible small-value fallback."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        body = f"{v / 1_000_000_000:.2f}B"
    elif v >= 1_000_000:
        body = f"{v / 1_000_000:.1f}M"
    elif v >= 1_000:
        body = f"{v / 1_000:.0f}K"
    else:
        body = f"{v:,.0f}"
    return f"{sign}{currency} {body}"


def pct(value: float, *, signed: bool = False, places: int = 1) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{v:+.{places}f}%" if signed else f"{v:.{places}f}%"


def delta_tone(value: Optional[float], *, good_is_up: bool = True) -> str:
    """Map a signed delta to a semantic tone class (good / danger / neutral)."""
    if value is None:
        return "neutral"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if v == 0:
        return "neutral"
    up = v > 0
    return "good" if up == good_is_up else "danger"


def rank_label(rank: int, of_n: Optional[int] = None) -> str:
    return f"#{int(rank)} of {int(of_n)}" if of_n else f"#{int(rank)}"
