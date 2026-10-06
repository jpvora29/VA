"""How money is stated, everywhere a reader sees it: millions, or billions.

Premium is stored in raw USD and used to be printed by six formatters, each
choosing its own unit per value — so one answer read "$412K" in a sentence,
"$1.2B" in a KPI, "$840M" in a table and "12,345,678" in a raw column. The rule
the business reads in is simple, and this module is the only place it lives:

    MILLIONS by default      $8.2M, $0.4M, $0.04M; $1,250.0M is never written
    BILLIONS from $1B        $1.3B — only when the amount is that large
    never K                  a small line is "$0.4M", not "$412K" or "$412,345"

One floor: a lone amount under $10K is written in dollars ("$390"), because in
millions it would read "$0.00M" — a figure that states nothing and that the
claim verifier cannot match. Premium never gets near it; toy data does.

A table or chart shares ONE unit across its column (`money_scale`), so figures
compare down the page; a single figure in a sentence picks its own
(`money_text`). Pure, so every surface can import it.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

MILLION = 1_000_000.0
BILLION = 1_000_000_000.0

#: Below this a lone amount is written in dollars (see the module note).
TINY = 10_000.0

#: The two units, coarsest first. Nothing smaller than a million is offered.
UNITS: Tuple[Tuple[float, str], ...] = ((BILLION, "B"), (MILLION, "M"))


def money_scale(values: Iterable[Optional[float]]) -> Tuple[float, str]:
    """(divisor, suffix) for a column of money: billions only when its largest
    amount reaches a billion, otherwise millions."""
    largest = max((abs(float(v)) for v in values if v is not None), default=0.0)
    return (BILLION, "B") if largest >= BILLION else (MILLION, "M")


def decimals_for(scaled: float) -> int:
    """One decimal; two for an amount under 0.1 of the unit, so $40K reads
    "$0.04M" rather than a misleading "$0.0M"."""
    size = abs(scaled)
    return 2 if 0 < size < 0.1 else 1


def money_text(value: Optional[float], *, symbol: str = "$", signed: bool = False,
               scale: Optional[Tuple[float, str]] = None) -> str:
    """One amount as a reader sees it: "$8.2M", "-$0.4M", "+$1.3B", "—" for none.

    ``scale`` pins the unit (a table's shared one); otherwise the amount picks
    its own — millions, or billions from $1B.
    """
    if value is None:
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if amount < 0 else ("+" if signed and amount > 0 else "")
    if scale is None and abs(amount) < TINY:
        return f"{sign}{symbol}{abs(amount):,.0f}"
    divisor, suffix = scale or money_scale([amount])
    scaled = amount / divisor
    return f"{sign}{symbol}{abs(scaled):,.{decimals_for(scaled)}f}{suffix}"
