"""Colour a written change by its OWN sign — green growth, red decline.

The GWP Performance page is authored with static example colours: the YoY badge is a red
circle (the author's example was a decline) and the table's change column is green. A real
number inherits whichever colour the example had, so a +23.0% growth showed in a red badge
and a -0.2 pp fall in green. These helpers repaint by the written value's sign.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from logger import get_logger

logger = get_logger(__name__)

GAIN_GREEN = "2F7500"
LOSS_RED = "C53532"

# GWP-page roles (``studio.template_fill.gwp_page``) whose colour follows the sign.
FILL_BY_SIGN_SUFFIXES = (":panel:yoy",)  # the badge: its shape fill
INK_BY_SIGN_SUFFIXES = (":chg",)  # the table's change column: its text

_NUMBER = re.compile(r"[-+−]?\s*\d+(?:[.,]\d+)*")


def sign_of(text: Any) -> int:
    """+1 for a rise, -1 for a fall, 0 for flat or no number ("+9.1%▲", "-0.2 pp", "23.0%")."""
    t = str(text or "").strip()
    if "▼" in t or "↓" in t:
        return -1
    if "▲" in t or "↑" in t:
        return 1
    found = _NUMBER.search(t)
    if not found:
        return 0
    number = found.group(0).replace(" ", "")
    if number[0] in "-−":
        return -1
    digits = number.lstrip("+").replace(",", "")
    return 1 if float(digits) > 0 else 0


def sign_hex(text: Any) -> str | None:
    """The colour a change of ``text``'s sign is shown in; ``None`` for flat."""
    sign = sign_of(text)
    if sign > 0:
        return GAIN_GREEN
    if sign < 0:
        return LOSS_RED
    return None


def fills_by_sign(role: str) -> bool:
    return role.startswith("gwp:") and role.endswith(FILL_BY_SIGN_SUFFIXES)


def inks_by_sign(role: str) -> bool:
    return role.startswith("gwp:") and role.endswith(INK_BY_SIGN_SUFFIXES)


def fill_shape_by_sign(shape, text: Any) -> None:
    """Paint ``shape``'s solid fill green or red for the sign of ``text``."""
    hexv = sign_hex(text)
    if hexv is None:
        return
    from pptx.dml.color import RGBColor

    try:
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(hexv)
    except Exception as exc:  # noqa: BLE001 — colouring must never break the fill
        logger.warning("template_fill: sign fill skipped: %s", exc)


def ink_runs_by_sign(paragraphs: Iterable[Any], text: Any) -> None:
    """Paint every run of ``paragraphs`` green or red for the sign of ``text``."""
    hexv = sign_hex(text)
    if hexv is None:
        return
    from pptx.dml.color import RGBColor

    try:
        for paragraph in paragraphs:
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor.from_string(hexv)
    except Exception as exc:  # noqa: BLE001 — colouring must never break the fill
        logger.warning("template_fill: sign ink skipped: %s", exc)
