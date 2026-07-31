"""Section understanding — classify each slide of ANY deck into a section TYPE.

The backbone of the "understands any uploaded/changed template" engine: a generic,
keyword-driven classifier (no hard-coded slide indices) that labels every slide with
a :class:`Section`. Downstream uses it to pick section-specific behaviour — e.g. which
slides carry fact-grounded commentary (Trading Summary, SWOT, Highlights), which are
per-product breakdown grids, which are dividers — so the same code handles a template
whose slides are reordered, renamed, added or removed.

Pure/deterministic: reads only the analyzed ``Template`` (titles + shape text).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Dict, List

from studio.template_fill.analyze import Slide, Template

# A short divider title that is just an enumerated entity, e.g. "Country (1)".
_DIVIDER_TITLE = re.compile(r"^\s*(?:country|region|product)\s*\(\s*\d+\s*\)\s*$", re.I)


class Section(str, Enum):
    COVER = "cover"
    SUMMARY = "summary"
    HIGHLIGHTS = "highlights"
    TRADING_SUMMARY = "trading_summary"
    GWP_PERFORMANCE = "gwp_performance"
    PORTFOLIO = "portfolio"
    FEEDBACK = "feedback"
    RANKING = "ranking"
    GROWTH = "growth"
    SWOT = "swot"
    COUNTRY_DIVIDER = "country_divider"
    BREAKDOWN = "breakdown"
    CARRIER_TITLE = "carrier_title"
    BACK_COVER = "back_cover"
    OTHER = "other"


# Ordered (title keyword(s) → Section); first match wins, so specific phrases precede
# generic ones ("trading summary" before "summary"; "portfolio and lc"/"ranking" before
# "portfolio analysis"; "gwp yoy growth" before the bare "growth rate" cue).
_TITLE_RULES: List[tuple] = [
    (("swot",), Section.SWOT),
    (("trading summary",), Section.TRADING_SUMMARY),
    (("feedback",), Section.FEEDBACK),
    (("breakdown",), Section.BREAKDOWN),
    (("lc ranking", "portfolio and lc", "ranking"), Section.RANKING),
    (("gwp yoy growth", "gwp performance", "yoy gwp growth"), Section.GWP_PERFORMANCE),
    (("growth rate", "vs marsh growth"), Section.GROWTH),
    (("highlight",), Section.HIGHLIGHTS),
    (("portfolio analysis", "portfolio"), Section.PORTFOLIO),
    (("carrier:",), Section.CARRIER_TITLE),
    (("summary",), Section.SUMMARY),
]

# Layout-name cues for the slides that carry no meaningful title text: the deck cover
# (whose only text IS the carrier placeholder) and the closing back cover.
_LAYOUT_RULES: List[tuple] = [
    (("title slide",), Section.COVER),
    (("back cover",), Section.BACK_COVER),
]


def section_of(slide: Slide) -> Section:
    """The :class:`Section` of one slide, from its title (and obvious shape cues)."""
    title = slide.title().strip()
    low = title.lower()
    if _DIVIDER_TITLE.match(title):
        return Section.COUNTRY_DIVIDER
    for keywords, section in _TITLE_RULES:
        if any(k in low for k in keywords):
            return section
    layout = str(getattr(slide, "layout", "") or "").lower()
    for keywords, section in _LAYOUT_RULES:
        if any(k in layout for k in keywords):
            return section
    return Section.OTHER


def classify_sections(template: Template) -> Dict[int, Section]:
    """``{slide_idx: Section}`` for the whole deck."""
    return {s.index: section_of(s) for s in template.slides}
