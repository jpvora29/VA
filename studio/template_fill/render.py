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


# A REAL example number the author typed rather than an x-placeholder: an optional sign,
# digits (comma-grouped, optionally with decimals), an optional M/B/K scale and %. The
# scale/% must be ADJACENT to the digits, so a separated unit ("+0.3 pp") stays in the
# surrounding text and keeps its spacing.
_EXAMPLE_NUM = re.compile(
    r"(?P<sign>[+-])?(?P<num>\d[\d,]*(?:\.(?P<dec>\d+))?)(?P<scale>[MmBbKk])?(?P<pct>%)?"
)
_SCALE_DIVISOR = {"m": 1e6, "b": 1e9, "k": 1e3}


def render_example(token: str, value: Any) -> str:
    """Render ``value`` in the style of an *example* ``token`` (not an x-placeholder).

    Some slots carry a real figure the author typed — ``€106.5m``, ``-1.0%``,
    ``+6.1%▲``, ``+0.3 pp``, ``+3``. There is no ``x`` to key off, so the style comes
    from the example itself: its surrounding text (currency symbol, ``pp`` suffix), its
    decimals, its M/B/K scale, whether it was written with a forced ``+``, and any trend
    arrow (re-pointed by the real value's own sign). Non-numeric values pass through.
    """
    if value is None:
        return token
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value)

    m = _EXAMPLE_NUM.search(token or "")
    if m is None:
        return str(value)

    decimals = len(m.group("dec") or "")
    scale = m.group("scale") or ""
    pct = bool(m.group("pct"))
    val = float(value)
    if not pct and scale:
        val /= _SCALE_DIVISOR[scale.lower()]

    grouped = "," in m.group("num")
    digits = f"{abs(val):,.{decimals}f}" if grouped else f"{abs(val):.{decimals}f}"
    sign = "-" if val < 0 else ("+" if m.group("sign") == "+" else "")
    body = sign + digits + scale + ("%" if pct else "")

    out = token[: m.start()] + body + token[m.end():]
    if any(a in out for a in _ARROWS):
        arrow = "▲" if val > 0 else ("▼" if val < 0 else "►")
        out = re.sub(f"[{_ARROWS}]", arrow, out)
    return out
