"""Complete a widget's numbers deterministically, after the model has extracted them.

The extractors report the figures they can find in the rows. They routinely find
some and miss others — a product row arrives with a carrier premium and a Marsh
premium but no share of wallet, or with a share and no whitespace — and the board
then prints "—" beside a measure the data plainly supports. That is the "share of
wallet is missing" / "no premium shown for this product" defect.

Nothing here invents a number. Every function is arithmetic over figures the model
already reported, using the SAME definitions the schemas state:

    whitespace          = max(Marsh premium - carrier premium, 0)
    share of WALLET     = carrier premium / Marsh premium          (outward)
    share of PORTFOLIO  = line premium / the carrier's own total   (inward)

The two shares are governed terms (`core/definitions/terms.yaml`) and must never
be merged, so they take different denominators and are filled independently — one
being derivable never fills the other.

There are two entry points, and the difference between them is what happens to a
row with no figures at all:

* :func:`complete_widget` — the GENERATION path. A row carrying no premium is
  dropped, because a row of dashes is not evidence; a widget left with no rows is
  then dropped by :mod:`ui.boardroom.builder`, and a page left with no widgets
  goes with it.
* :func:`recompute_widget` — the EDITING path. Every row is kept, however empty:
  an author clearing a field mid-edit must not have their row deleted under them.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.boardroom.money import format_money
from core.boardroom.opportunity import band_rows

# The measures a product / industry row is expected to carry once completed. They
# are set even when they come out None, so a reader (and a test) can tell "not
# derivable from these figures" from "this widget never considered it".
_DERIVED_KEYS = ("whitespace_premium_value", "share_of_wallet_pct", "share_of_portfolio_pct")

# value field -> the display field that should spell it out.
_MONEY_FIELDS = (
    ("carrier_premium_value", "carrier_premium"),
    ("marsh_premium_value", "marsh_premium"),
    ("whitespace_premium_value", "whitespace_premium"),
    ("premium_value", "premium"),
    ("premium_exposed_value", "premium_exposed"),
)


def as_number(value: Any) -> Optional[float]:
    """A float when the value really is one, else ``None`` (never 0.0 for junk)."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def share_pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    """``part`` as a percentage of ``whole`` — ``None`` unless both are usable."""
    if part is None or whole is None or whole <= 0:
        return None
    return round(part / whole * 100.0, 1)


def whitespace_of(carrier: Optional[float], marsh: Optional[float]) -> Optional[float]:
    """Marsh premium the carrier does not write, floored at zero."""
    if carrier is None or marsh is None:
        return None
    return max(marsh - carrier, 0.0)


def has_premium(row: Dict[str, Any]) -> bool:
    """True when a row states at least one real premium figure."""
    return any(
        as_number(row.get(key)) is not None
        for key in ("carrier_premium_value", "marsh_premium_value", "premium_value")
    )


def carrier_premium(row: Dict[str, Any]) -> Optional[float]:
    """What the carrier writes on this row, under either field name.

    ZERO is an answer, not a missing value — "the carrier writes nothing in this
    industry" is the whole point of a whitespace row. An `or` chain here read 0.0
    as absent and left the share of wallet blank on exactly the rows the widget
    exists to show.
    """
    value = as_number(row.get("carrier_premium_value"))
    return value if value is not None else as_number(row.get("premium_value"))


def carrier_total(rows: List[Dict[str, Any]]) -> Optional[float]:
    """The carrier's own premium across the rows — share of portfolio's denominator.

    Only valid when EVERY row reports a carrier premium: a partial total would
    make each line look like a bigger slice of the book than it is.
    """
    values = [carrier_premium(r) for r in rows]
    if not values or any(v is None for v in values):
        return None
    return sum(values) or None


def spell_out_money(row: Dict[str, Any]) -> Dict[str, Any]:
    """Give every numeric amount on a row the display string its VALUE implies.

    Always derived, never merely filled in where missing. The number is the fact;
    the string is a rendering of it, and the only thing that knows the reporting
    currency is `core.boardroom.money`. A model-authored "£33.8m" used to survive
    into the board because a display string was left alone whenever one was
    present — so a board could print a model's pounds beside a derived figure in
    the configured currency, on the same row. Two currencies on one board is
    worse than either currency alone.

    A display string carrying no digits is PROSE, not a rendering — "No current
    premium" says something the number 0 does not, and rewriting it to "$0" would
    lose the point of the sentence. Only amounts are re-rendered.
    """
    row = dict(row)
    for value_key, display_key in _MONEY_FIELDS:
        value = as_number(row.get(value_key))
        if value is None:
            continue
        row[value_key] = value
        shown = str(row.get(display_key) or "").strip()
        if not shown or any(character.isdigit() for character in shown):
            row[display_key] = format_money(value)
    return row


def complete_premium_row(row: Dict[str, Any], *, portfolio_total: Optional[float]) -> Dict[str, Any]:
    """One product / industry row with every measure its own figures imply.

    ``portfolio_total`` is the carrier's own premium across the widget's rows —
    the denominator share of portfolio needs, which no single row can see.
    """
    row = dict(row)
    carrier = carrier_premium(row)
    marsh = as_number(row.get("marsh_premium_value"))
    derived = {
        "whitespace_premium_value": whitespace_of(carrier, marsh),
        "share_of_wallet_pct": share_pct(carrier, marsh),
        "share_of_portfolio_pct": share_pct(carrier, portfolio_total),
    }
    for key in _DERIVED_KEYS:
        if as_number(row.get(key)) is None:
            row[key] = derived[key]
    return spell_out_money(row)


def complete_premium_rows(
    rows: List[Dict[str, Any]], *, drop_empty: bool
) -> List[Dict[str, Any]]:
    """Complete every row; drop the ones stating no premium when asked to."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    kept = [r for r in rows if has_premium(r)] if drop_empty else rows
    total = carrier_total([r for r in kept if has_premium(r)])
    return [complete_premium_row(r, portfolio_total=total) for r in kept]


def by_whitespace(row: Dict[str, Any]) -> float:
    """Ranking key: the money left on the table, biggest first."""
    return as_number(row.get("whitespace_premium_value")) or 0.0


def by_exposure(item: Dict[str, Any]) -> float:
    """Ranking key: the premium a watch item puts at risk, biggest first."""
    return as_number(item.get("premium_exposed_value")) or 0.0


# ── one completer per widget ─────────────────────────────────────────────────


def complete_headroom(headroom: Dict[str, Any], *, drop_empty: bool = True) -> Dict[str, Any]:
    """Product Line Headroom, ranked by the whitespace it now knows."""
    headroom = dict(headroom or {})
    rows = complete_premium_rows(headroom.get("rows") or [], drop_empty=drop_empty)
    headroom["rows"] = sorted(rows, key=by_whitespace, reverse=True) if drop_empty else rows
    return headroom


def complete_whitespace(whitespace: Dict[str, Any], *, drop_empty: bool = True) -> Dict[str, Any]:
    """Industry Whitespace — same measures, ranked and banded.

    The band (`core.boardroom.opportunity`) reads the two growth rates against
    the share, so the colour on a row is a reading of that row's own numbers.
    """
    whitespace = dict(whitespace or {})
    rows = complete_premium_rows(whitespace.get("rows") or [], drop_empty=drop_empty)
    rows = band_rows(rows)
    whitespace["rows"] = sorted(rows, key=by_whitespace, reverse=True) if drop_empty else rows
    return whitespace


def wallet_benchmark(bubbles: List[Dict[str, Any]]) -> Optional[float]:
    """The carrier's OVERALL share of wallet across the lines.

    Premium-weighted, not a mean of percentages: a 60% share of a tiny line and a
    5% share of the whole book do not average to 32.5% in any sense a reader
    would accept. Total carrier premium over total Marsh premium is the figure
    the vertical line has to be, because that is the number each bubble's x is
    being compared against.
    """
    carrier = [carrier_premium(b) for b in bubbles]
    marsh = [as_number(b.get("marsh_premium_value")) for b in bubbles]
    if not carrier or any(v is None for v in carrier) or any(v is None for v in marsh):
        return None
    return share_pct(sum(carrier), sum(marsh))


def portfolio_benchmark(bubbles: List[Dict[str, Any]]) -> Optional[float]:
    """An even split of the carrier's own book across its lines.

    The horizontal line answers "is this line a bigger part of the book than its
    fair share?" — so it sits at 100/N, and a bubble above it is a line the
    carrier is over-indexed in. Averaging the reported shares gives the same
    number when every line is present, and a misleading one when they are not.
    """
    positioned = [b for b in bubbles if b.get("share_of_portfolio_pct") is not None]
    if not positioned:
        return None
    return round(100.0 / len(positioned), 1)


def complete_portfolio_map(portfolio_map: Dict[str, Any], *, drop_empty: bool = True) -> Dict[str, Any]:
    """The bubble map — a generated bubble needs BOTH shares to have a position.

    Both benchmark axes are computed here when the extractor did not report them.
    Without them the plot is a scatter of dots with nothing to read them against;
    with them it has four quadrants and every bubble is a sentence.
    """
    portfolio_map = dict(portfolio_map or {})
    bubbles = complete_premium_rows(portfolio_map.get("bubbles") or [], drop_empty=drop_empty)
    if drop_empty:
        bubbles = [
            b
            for b in bubbles
            if b.get("share_of_wallet_pct") is not None
            and b.get("share_of_portfolio_pct") is not None
        ]
    portfolio_map["bubbles"] = bubbles

    # Derived over EVERY line, not just the ones the plot draws: the benchmark is
    # the book's average, and the plot shows only its biggest lines.
    derived = False
    if as_number(portfolio_map.get("wallet_benchmark_pct")) is None:
        value = wallet_benchmark(bubbles)
        if value is not None:
            portfolio_map["wallet_benchmark_pct"] = value
            derived = True
    if as_number(portfolio_map.get("portfolio_benchmark_pct")) is None:
        value = portfolio_benchmark(bubbles)
        if value is not None:
            portfolio_map["portfolio_benchmark_pct"] = value
            derived = True
    if derived and not str(portfolio_map.get("benchmark_label") or "").strip():
        portfolio_map["benchmark_label"] = "Carrier average"
    return portfolio_map


def complete_top_carriers(top_carriers: Dict[str, Any], *, drop_empty: bool = True) -> Dict[str, Any]:
    """Top Carriers — a standing with no premium says nothing, so it goes."""
    top_carriers = dict(top_carriers or {})
    carriers = [c for c in (top_carriers.get("carriers") or []) if isinstance(c, dict)]
    if drop_empty:
        carriers = [c for c in carriers if as_number(c.get("premium_value")) is not None]
    top_carriers["carriers"] = [spell_out_money(c) for c in carriers]
    return top_carriers


def complete_watchlist(watchlist: Dict[str, Any], *, drop_empty: bool = True) -> Dict[str, Any]:
    """Watch items, ordered by the premium they put at risk.

    Ordering is the whole ranking now: the board no longer prints a High/Medium/
    Low label, so the money at stake is what puts an item at the top.
    """
    watchlist = dict(watchlist or {})
    items = [spell_out_money(i) for i in (watchlist.get("items") or []) if isinstance(i, dict)]
    watchlist["items"] = sorted(items, key=by_exposure, reverse=True) if drop_empty else items
    return watchlist


Completer = Callable[..., Dict[str, Any]]

# widget name -> the function that completes it. Both entry points map over this,
# so adding a widget is adding a row rather than another branch.
COMPLETERS: Dict[str, Completer] = {
    "headroom": complete_headroom,
    "whitespace": complete_whitespace,
    "portfolio_map": complete_portfolio_map,
    "top_carriers": complete_top_carriers,
    "watchlist": complete_watchlist,
}


def _apply(name: str, payload: Any, *, drop_empty: bool) -> Any:
    completer = COMPLETERS.get(name)
    if completer is None or not isinstance(payload, dict):
        return payload
    return completer(payload, drop_empty=drop_empty)


def complete_widget(name: str, payload: Any) -> Any:
    """Generation path: complete the numbers and drop rows with nothing to say."""
    return _apply(name, payload, drop_empty=True)


def recompute_widget(name: str, payload: Any) -> Any:
    """Editing path: complete the numbers, keep every row the author has."""
    return _apply(name, payload, drop_empty=False)
