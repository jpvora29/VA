"""The charts a performance answer should carry, decided from the data.

One chart chosen by a model from whatever result sets happened to be lying around
answers whatever that result set was about. A performance question has three
things worth showing, and which three is not a judgement call:

    1. timing      quarters across the compared years, so the shape of the
                   movement is visible rather than its total
    2. contribution premium by line with the movement beside it, so the reader
                   sees which line the total came from
    3. position    share of wallet by line, so size and penetration are not
                   confused with each other

They are built here, deterministically, from figures the primitives already
computed — so the chart cannot describe a different slice from the prose beside
it, and a title cannot promise something the rows do not contain.

Titles are the other half of that. A title is written from the ACTUAL series,
period and dimension in the rows, never from the question, because a title
generated from the question is the one that misleads: ask "how did Zurich do?"
and get a chart headed "How did Zurich do?" over a plot of four quarters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analytics.positioning import PositioningPack, SlicePosition

#: At most this many charts. Three is what fits a column beside the prose without
#: the reader scrolling the panel; a fourth is always the least useful one.
MAX_CHARTS = 3

#: Axis labels. Short, because an axis title competing with the tick labels for
#: width is what makes a chart look cluttered.
PREMIUM_AXIS = "Premium"
CHANGE_AXIS = "Change vs prior year"
WALLET_AXIS = "Share of wallet (%)"
QUARTER_AXIS = "Quarter"


@dataclass(frozen=True)
class ChartSpec:
    """One chart, ready for the renderer: its rows and how to draw them."""

    key: str
    title: str
    rows: Tuple[Dict[str, Any], ...]
    chart_type: str
    x: str
    y: Tuple[str, ...]
    series: Tuple[str, ...] = ()
    #: Axis titles. Stated rather than derived, because a chart comparing two
    #: years has a y of ["2024", "2025"] and deriving the label from that names
    #: the series instead of the measure.
    x_title: str = ""
    y_title: str = ""
    #: Two or three words for the tab. The full title says what the chart shows
    #: and is too long to sit in a tab strip; the tab says which chart it is.
    tab: str = ""

    def as_view(self) -> Dict[str, Any]:
        """The shape `ui.evidence.build_views` already consumes."""
        return {
            "title": self.title,
            "tab": self.tab or self.title,
            "rows": [dict(row) for row in self.rows],
            "chart_data": {
                "chart_type": self.chart_type,
                "x": self.x,
                "y": list(self.y),
                "series": list(self.series),
                "title": self.title,
                "x_title": self.x_title,
                "y_title": self.y_title,
            },
        }


def _period_label(scope: Mapping[str, Any]) -> str:
    """The period the scope pins, for a title. Empty when it pins none."""
    for key, value in (scope or {}).items():
        if str(key).lower() in {"year", "survey_year"}:
            if isinstance(value, (list, tuple)):
                value = value[0] if len(value) == 1 else None
            return str(value) if value else ""
    return ""


def _place(scope: Mapping[str, Any]) -> str:
    for key, value in (scope or {}).items():
        if str(key).lower() in {"country", "surveycountry"}:
            if isinstance(value, (list, tuple)):
                value = value[0] if len(value) == 1 else None
            return str(value) if value else ""
    return ""


def _where(scope: Mapping[str, Any]) -> str:
    """" in Singapore" / "" — the scope clause a title can carry honestly."""
    place = _place(scope)
    return f" in {place}" if place else ""


# --------------------------------------------------------------------------- #
# The three charts
# --------------------------------------------------------------------------- #


def quarterly_chart(
    rows: Sequence[Mapping[str, Any]], *, scope: Mapping[str, Any] = ()
) -> Optional[ChartSpec]:
    """Quarters across the compared years, as grouped bars.

    `rows` are expected as ``{"Quarter": "Q1", "<year>": value, ...}`` — one
    column per year, which is what makes the two years sit side by side under
    each quarter instead of running end to end as one long series. A single year
    is not a comparison and yields no chart.
    """
    usable = [dict(row) for row in rows or [] if row]
    if not usable:
        return None
    years = sorted(
        key for key in usable[0]
        if str(key).isdigit() and len(str(key)) == 4
    )
    if len(years) < 2:
        return None
    return ChartSpec(
        key="quarterly",
        tab="Quarterly",
        title=f"Quarterly premium, {years[0]} vs {years[-1]}{_where(scope)}",
        rows=tuple(usable),
        chart_type="bar",
        x=QUARTER_AXIS if QUARTER_AXIS in usable[0] else "Quarter",
        y=tuple(years),
        x_title=QUARTER_AXIS,
        y_title=PREMIUM_AXIS,
    )


def contribution_chart(
    pack: PositioningPack, *, scope: Mapping[str, Any] = ()
) -> Optional[ChartSpec]:
    """Movement by line — which lines the headline came from, and which offset it.

    Deliberately the CHANGE and not the premium: a bar chart of premium by line
    shows which line is biggest, which the table already says. The change is what
    the question asked about, and plotting it puts the offsetting line visibly
    on the other side of zero.
    """
    movers = [p for p in pack.positions if p.movement is not None]
    if len(movers) < 2:
        return None
    movers.sort(key=lambda p: p.movement or 0.0)
    rows = tuple(
        {_dimension_label(pack): p.slice, CHANGE_AXIS: round(p.movement or 0.0, 1)}
        for p in movers
    )
    period = _period_label(scope)
    return ChartSpec(
        key="contribution",
        tab="What moved",
        title=f"Premium movement by {_dimension_label(pack).lower()}"
              + (f", {period} vs prior year" if period else "")
              + _where(scope),
        rows=rows,
        chart_type="bar",
        x=_dimension_label(pack),
        y=(CHANGE_AXIS,),
        x_title=_dimension_label(pack),
        y_title=CHANGE_AXIS,
    )


def wallet_chart(
    pack: PositioningPack, *, scope: Mapping[str, Any] = ()
) -> Optional[ChartSpec]:
    """Share of wallet by line — penetration, kept apart from size.

    The chart that answers "where are we strong" as opposed to "where are we
    big", which the premium table cannot show and readers routinely conflate.
    """
    held = [p for p in pack.positions if p.share_of_wallet is not None]
    if len(held) < 2:
        return None
    held.sort(key=lambda p: p.share_of_wallet or 0.0, reverse=True)
    rows = tuple(
        {_dimension_label(pack): p.slice, WALLET_AXIS: round(p.share_of_wallet or 0.0, 1)}
        for p in held
    )
    period = _period_label(scope)
    return ChartSpec(
        key="wallet",
        tab="Share of wallet",
        title=f"Share of Marsh wallet by {_dimension_label(pack).lower()}"
              + (f", {period}" if period else "")
              + _where(scope),
        rows=rows,
        chart_type="bar",
        x=_dimension_label(pack),
        y=(WALLET_AXIS,),
        x_title=_dimension_label(pack),
        y_title=WALLET_AXIS,
    )


def _dimension_label(pack: PositioningPack) -> str:
    """"Product_Line" -> "Product line". The axis reads as English, not a column."""
    raw = (pack.dimension or "Slice").replace("_", " ").strip()
    return raw[:1].upper() + raw[1:].lower() if raw else "Slice"


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #


def build_chart_plan(
    pack: Optional[PositioningPack] = None,
    *,
    quarterly_rows: Sequence[Mapping[str, Any]] = (),
    scope: Mapping[str, Any] = (),
    limit: int = MAX_CHARTS,
) -> List[ChartSpec]:
    """The charts this answer should carry, most informative first.

    Order is the argument's order, not the data's: timing, then what drove it,
    then where the carrier stands. A chart whose data is missing is skipped
    rather than drawn empty, so a thin turn produces fewer charts and never a
    blank one.
    """
    candidates = [
        quarterly_chart(quarterly_rows, scope=scope),
        contribution_chart(pack, scope=scope) if pack else None,
        wallet_chart(pack, scope=scope) if pack else None,
    ]
    return [spec for spec in candidates if spec is not None][:limit]


def quarterly_rows_from(
    facts: Sequence[Any], *, current_year: int, prior_year: int
) -> List[Dict[str, Any]]:
    """Aligned-period facts as one row per quarter with a column per year.

    The renderer draws a grouped bar from columns, so the two years have to be
    columns rather than rows. Built from the facts `compute_aligned_periods`
    already produced, so the chart and the quarterly claim quote one calculation.
    """
    by_period: Dict[str, Dict[str, Any]] = {}
    for fact in facts or []:
        dims = getattr(fact, "dims", {}) or {}
        if dims.get("grain") != "quarter":
            continue
        label = str(dims.get("period") or "")
        if not label:
            continue
        support = (getattr(fact, "support", None) or [{}])[0]
        row = by_period.setdefault(label, {QUARTER_AXIS: label})
        for year in (prior_year, current_year):
            value = support.get(str(year))
            if value is not None:
                row[str(year)] = float(value)
    ordered = sorted(by_period.values(), key=lambda row: str(row[QUARTER_AXIS]))
    # Only quarters where BOTH years are present can be compared side by side;
    # a half-drawn pair reads as a collapse rather than as missing data.
    return [
        row for row in ordered
        if str(current_year) in row and str(prior_year) in row
    ]
