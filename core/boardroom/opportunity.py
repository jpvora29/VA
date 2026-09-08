"""Which whitespace gap is worth chasing — from the facts, never from an opinion.

A ranked list of unwritten premium says where the money is, not where to go. Two
industries with the same gap are completely different prospects:

* the market is growing, the carrier is small in it, and what it does write is
  already growing — the market is moving and the carrier is moving with it;
* the market is growing and the carrier is going backwards in it — the gap is
  widening while you read the board.

So a row is banded from three figures it already reports: how fast the MARKET
moved (`marsh_change_pct`), how fast the CARRIER moved (`carrier_change_pct`),
and how much of the wallet it holds (`share_of_wallet_pct`). The band drives a
colour, and the colour is what makes a long list scannable.

This is a reading of stated facts, not a rating: every band names the test that
produced it (:func:`band_reason`), the row prints both growth numbers beside the
colour, and a row missing a growth rate is left UNBANDED rather than guessed at.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def as_number(value: Any) -> Optional[float]:
    """A float when the value really is one, else ``None``.

    Defined here rather than imported from `core.boardroom.derive`: derive calls
    this module, and a module that reads facts should not depend on the module
    that completes them.
    """
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# A market moving less than this is flat for the purpose of choosing where to go;
# a share above this is a position, not a gap. Both are read against figures the
# rows already carry, and both are printed in the widget's own explanation, so a
# reader can disagree with the line rather than with the colour.
GROWING_PCT = 2.0
LOW_SHARE_PCT = 15.0

# band -> (label, tone). Tone is the widget's existing colour vocabulary.
BANDS: Dict[str, tuple] = {
    "prime": ("Prime gap", "good"),
    "open": ("Open market", "warn"),
    "losing": ("Losing ground", "danger"),
    "held": ("Already held", "neutral"),
    "flat": ("Flat market", "neutral"),
}


def _growing(value: Optional[float]) -> bool:
    return value is not None and value >= GROWING_PCT


def _shrinking(value: Optional[float]) -> bool:
    return value is not None and value < 0


def classify(
    *,
    marsh_change_pct: Optional[float],
    carrier_change_pct: Optional[float],
    share_of_wallet_pct: Optional[float],
) -> str:
    """The band for one row, or ``""`` when the facts do not support one.

    Read top to bottom — the first true statement wins, so a row is banded by the
    most decision-relevant thing true about it.
    """
    market, carrier = as_number(marsh_change_pct), as_number(carrier_change_pct)
    share = as_number(share_of_wallet_pct)
    if market is None:
        return ""
    if not _growing(market):
        return "flat"
    if share is not None and share > LOW_SHARE_PCT:
        return "held"
    if _shrinking(carrier):
        return "losing"
    if _growing(carrier):
        return "prime"
    return "open"


def band_label(band: str) -> str:
    return BANDS.get(band, ("", ""))[0]


def band_tone(band: str) -> str:
    return BANDS.get(band, ("", "neutral"))[1]


def band_reason(band: str) -> str:
    """The test behind a band, in the reader's language."""
    return {
        "prime": (
            f"The market grew {GROWING_PCT:g}%+ , the carrier holds "
            f"{LOW_SHARE_PCT:g}% or less of it, and the carrier is growing here too"
        ),
        "open": (
            f"The market grew {GROWING_PCT:g}%+ and the carrier holds "
            f"{LOW_SHARE_PCT:g}% or less of it, but is not growing into it"
        ),
        "losing": f"The market grew {GROWING_PCT:g}%+ while the carrier went backwards",
        "held": f"The carrier already holds more than {LOW_SHARE_PCT:g}% of this wallet",
        "flat": f"The market moved less than {GROWING_PCT:g}%, so the gap is not opening",
    }.get(band, "")


def rule_summary() -> str:
    """The whole banding rule in one line, for the widget's explanation drawer."""
    return (
        f"Colour reads the two growth rates together: a market growing "
        f"{GROWING_PCT:g}% or more where the carrier holds {LOW_SHARE_PCT:g}% or "
        f"less of the wallet is a gap — green when the carrier is already growing "
        f"into it, amber when it is not, red when it is going backwards. Grey means "
        f"the market is flat or the carrier already holds the wallet. A row with no "
        f"comparable period is left uncoloured."
    )


def band_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach the derived band to every row, leaving reported fields alone."""
    banded = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        row["opportunity"] = classify(
            marsh_change_pct=row.get("marsh_change_pct"),
            carrier_change_pct=row.get("carrier_change_pct"),
            share_of_wallet_pct=row.get("share_of_wallet_pct"),
        )
        banded.append(row)
    return banded
