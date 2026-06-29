"""Token-aware number rendering — format a value to match its placeholder's style.

The template author encodes the desired format in the placeholder itself:
``$xx,xxxm`` (dollars, millions, comma-grouped), ``x.xB`` (billions, 1 dp),
``$xxx.xM`` (dollars, millions, 1 dp), ``x.x%`` (percent, 1 dp), ``#x`` (a hashed
rank), ``PY (+x.x%▲)`` (a signed prior-year delta with a trend arrow). Rendering a
RAW number against its token reproduces that exact style — so values fit the box
(no overflow/overlap), read like the template, and the sign/arrow follow the data.
"""
from __future__ import annotations

import re
from typing import Any

# The numeric placeholder inside a token (same grammar as slot detection).
_NUM = re.compile(r"(?<![A-Za-z$])\$?[xX]+(?:[.,][xX]+)*(?:[MBKmbk])?%?(?![A-Za-z])")
_ARROWS = "▲▼►"


def _money(raw: float, *, dollar: bool = True) -> str:
    """Compact money — billions for ≥1bn, else millions/thousands. Short by design so
    long figures (``$2,293m``) stop overflowing their boxes; keeps the token's ``$``."""
    a = abs(float(raw))
    pfx = "$" if dollar else ""
    if a >= 1e9:
        return f"{pfx}{a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{pfx}{a / 1e6:,.0f}M"
    if a >= 1e3:
        return f"{pfx}{a / 1e3:,.0f}K"
    return f"{pfx}{a:,.0f}"


def _format_number(raw: float, sub: str) -> str:
    """Format ``raw`` to match the placeholder substring ``sub`` (scale/decimals/$/%)."""
    low = sub.lower()
    dollar = "$" in sub
    pct = "%" in sub
    scale = "b" if "b" in low else ("m" if ("m" in low or "," in sub) else "")
    decimals = len(re.findall(r"[xX]", sub.split(".", 1)[1])) if "." in sub else 0
    comma = "," in sub

    val = float(raw)
    if not pct:
        val = val / 1e9 if scale == "b" else (val / 1e6 if scale == "m" else val)
    num = f"{val:,.{decimals}f}" if comma else f"{val:.{decimals}f}"

    out = ("$" if dollar else "") + num
    if scale == "b":
        out += "B"
    elif scale == "m":
        out += "M" if "M" in sub else "m"
    if pct:
        out += "%"
    return out


def render_token(token: str, value: Any, value_kind: str = "") -> str:
    """Render ``value`` into ``token``'s style; non-numerics pass straight through."""
    if value is None:
        return token
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value)

    m = _NUM.search(token)
    if not m:
        return str(value)
    pre, sub, post = token[: m.start()], m.group(0), token[m.end():]

    forced_sign = bool(pre) and pre[-1] in "+-"
    if forced_sign:
        pre = pre[:-1]

    low = sub.lower()
    is_money = value_kind == "money" or "$" in sub or (low.endswith(("m", "b", "k")) and "%" not in sub)
    if is_money:
        # Auto-scale money (billions for the big figures); replaces the whole token
        # number incl. its own $ / m so nothing is left doubled.
        body = _money(abs(value) if value < 0 else value, dollar="$" in sub)
    else:
        body = _format_number(abs(value) if value < 0 else value, sub)
    if value < 0 and not body.startswith("-"):
        body = "-" + body
    elif forced_sign and value > 0:
        body = "+" + body

    result = pre + body + post
    if any(a in result for a in _ARROWS):
        arrow = "▲" if value > 0 else ("▼" if value < 0 else "►")
        result = re.sub(f"[{_ARROWS}]", arrow, result)
    return result
