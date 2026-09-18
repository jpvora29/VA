"""What a result-set column IS, so the reader's table can print and order it.

A table arrives as rows of plain values. Whether `1770.0` is dollars, a score, a
percentage or a year is not in the number, and the panel used to guess by
matching cells against a figure-shaped regex — a guess that puts a rank on the
left because of its hash and a product code on the right because of its digits.

So the producer declares it. This module is the vocabulary they declare in, kept
apart from any one producer because three now speak it: the positioning pack
(`core.analytics.positioning`), the analytics tool path
(`core.analytics.tools.rows`), and the renderer that consumes it
(`ui.components.evidence`).

A column with no declared kind is printed exactly as it arrived. That is the
right default: an undeclared number still sorts numerically, and inventing a
currency mark for it is how a Year column becomes "$2,024".
"""
from __future__ import annotations

from typing import Tuple

#: A label. Left-aligned, sorted as text.
TEXT = "text"

#: Money already divided by ONE scale shared across the whole table, with the
#: scale named once in the header ("Premium in M"). The form a column of figures
#: is compared DOWN — per-cell suffixes ("$1.2M" above "$840k") make that
#: impossible, which is the only thing a column of figures is for.
MONEY = "money"

#: Money at its RAW magnitude, printed with an SI suffix per cell ("$1.77M",
#: "$840k"). For a result set that arrived from a primitive with no shared scale
#: computed for it, where the alternative the reader actually saw was "1770.0".
MONEY_SI = "money_si"

#: A share or rate, already in percentage points (50.8 -> "50.8%").
PERCENT = "percent"

#: A movement in percentage points, printed with its sign ("+4.2%", "-25.0%").
#: The sign IS the direction, and unlike a glyph it also sorts.
SIGNED_PERCENT = "signed_percent"

#: A standing among a field ("#2"). Always accompanied by the field it was taken
#: among — "#5" alone is meaningless (`core/definitions/terms.yaml`).
RANK = "rank"

#: A plain count, grouped ("1,200").
COUNT = "count"

#: Every kind that carries a figure, so a renderer can right-align on membership
#: rather than on a list of names it has to keep in step.
FIGURE_KINDS: Tuple[str, ...] = (
    MONEY, MONEY_SI, PERCENT, SIGNED_PERCENT, RANK, COUNT,
)
