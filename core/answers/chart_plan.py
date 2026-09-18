"""The views a deterministic answer carries, decided from the data.

One chart chosen by a model from whatever result sets happened to be lying around
answers whatever that result set was about. A business question has a small,
knowable set of things worth showing, and which ones is not a judgement call:

    position      premium by line, the book beside the carrier, so size is visible
    timing        quarters across the compared years, so the shape of the movement
                  is visible rather than its total
    contribution  the movement by line as a waterfall, so the reader sees which
                  line the total came from and which one offset it
    penetration   share of wallet by line, so size and standing are not confused

They are built here, deterministically, from figures the primitives already
computed — so a chart cannot describe a different slice from the prose beside it,
and a title cannot promise something the rows do not contain.

Two things decide the plan, and nothing else:

* **the CATALOGUE** — one builder per chart, each a pure function of the pack. A
  builder returns ``None`` when its data is absent, which is how a thin turn
  produces fewer charts rather than a blank one.
* **the ORDER** — which charts matter most, by the analytical OPERATION the
  question asked for (`core.analysis.operation`). A position request leads with
  premium by line; a movement explanation leads with the waterfall. Adding an
  operation is a row in `_ORDER`, not a branch in the selector (OCP).

Titles are the other half of that. A title is written from the ACTUAL series,
period and dimension in the rows, never from the question, because a title
generated from the question is the one that misleads: ask "how did Zurich do?"
and get a chart headed "How did Zurich do?" over a plot of four quarters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from core.analysis.operation import (
    BREAKDOWN,
    MOVEMENT,
    PENETRATION,
    PERFORMANCE,
    POSITION,
)
from core.analytics.positioning import CARRIER_PREMIUM, MARSH_PREMIUM, PositioningPack

#: At most this many charts. Three is what fits a column beside the prose without
#: the reader scrolling the panel; a fourth is always the least useful one.
MAX_CHARTS = 3

#: What a view IS, as opposed to what it shows. The position table and a bar chart
#: both travel to the renderer down the same channel, and until this existed the
#: only way to tell them apart was that one had an empty `chart_data` — so "no
#: charts please" deleted the table too. A kind is checked; an absence is guessed.
TABLE = "table"
CHART = "chart"

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
            "kind": CHART,
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


def is_chart(view: Mapping[str, Any]) -> bool:
    """Whether a planned view draws a picture, as opposed to laying out rows.

    Reads the declared `kind` and falls back to the presence of a chart spec, so
    a view built before kinds existed (a reloaded conversation, a stored answer)
    is still classified the way it renders.
    """
    kind = str((view or {}).get("kind") or "").strip().lower()
    if kind in (TABLE, CHART):
        return kind == CHART
    return bool((view or {}).get("chart_data"))


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


def _dimension_label(pack: PositioningPack) -> str:
    """"Product_Line" -> "Product line". The axis reads as English, not a column."""
    raw = (pack.dimension or "Slice").replace("_", " ").strip()
    return raw[:1].upper() + raw[1:].lower() if raw else "Slice"


# --------------------------------------------------------------------------- #
# The catalogue — one builder per chart, each a pure function
# --------------------------------------------------------------------------- #


def premium_chart(
    pack: PositioningPack, *, scope: Mapping[str, Any] = ()
) -> Optional[ChartSpec]:
    """Premium by line — the carrier's book beside Marsh's, as grouped bars.

    The chart a reader means by "show me premium by product". It was the one
    chart the plan did not have: `contribution_chart` deliberately plots the
    CHANGE, so a question about how premium is spread across lines was answered
    with a picture of how it moved, and the sizes themselves were only ever in
    the table.

    Two bars per line, not one. The carrier's premium on its own says which line
    is biggest; the Marsh bar beside it says how much of that line the carrier
    holds — the same reading the share-of-wallet column gives numerically, in the
    form a reader takes in at a glance. A market table (no carrier in scope) has
    only the book to plot, so it draws one series.
    """
    sized = [p for p in pack.by_premium() if p.marsh_premium is not None
             or p.carrier_premium is not None]
    if len(sized) < 2:
        return None

    label = _dimension_label(pack)
    if pack.is_market_view:
        rows = tuple(
            {label: p.slice, MARSH_PREMIUM: p.marsh_premium}
            for p in sized if p.marsh_premium is not None
        )
        measures: Tuple[str, ...] = (MARSH_PREMIUM,)
    else:
        rows = tuple(
            {
                label: p.slice,
                MARSH_PREMIUM: p.marsh_premium,
                CARRIER_PREMIUM: p.carrier_premium,
            }
            for p in sized
        )
        measures = (MARSH_PREMIUM, CARRIER_PREMIUM)
    if len(rows) < 2:
        return None

    period = _period_label(scope)
    subject = pack.subject or "the market"
    return ChartSpec(
        key="premium",
        tab="Premium",
        title=f"Premium by {label.lower()} — {subject}"
              + (f", {period}" if period else "")
              + _where(scope),
        rows=rows,
        chart_type="bar",
        x=label,
        y=measures,
        x_title=label,
        y_title=PREMIUM_AXIS,
    )


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

    Deliberately the CHANGE and not the premium: `premium_chart` shows which line
    is biggest, and the change is what a movement question asked about.

    Drawn as a WATERFALL rather than as bars. The reading a movement answer needs
    is cumulative — these losses, less those gains, equals the headline — and a
    bar chart of the same numbers puts each line on its own baseline and leaves
    the reader to add them up. The renderer closes the series with a total bar,
    which is the figure the prose beside it leads with. Rows stay sorted worst
    first so the waterfall descends into the losses and climbs back out.
    """
    movers = [p for p in pack.positions if p.movement is not None]
    if len(movers) < 2:
        return None
    movers.sort(key=lambda p: p.movement or 0.0)
    label = _dimension_label(pack)
    rows = tuple(
        {label: p.slice, CHANGE_AXIS: round(p.movement or 0.0, 1)} for p in movers
    )
    period = _period_label(scope)
    return ChartSpec(
        key="contribution",
        tab="What moved",
        title=f"Premium movement by {label.lower()}"
              + (f", {period} vs prior year" if period else "")
              + _where(scope),
        rows=rows,
        chart_type="waterfall",
        x=label,
        y=(CHANGE_AXIS,),
        x_title=label,
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
    label = _dimension_label(pack)
    rows = tuple(
        {label: p.slice, WALLET_AXIS: round(p.share_of_wallet or 0.0, 1)} for p in held
    )
    period = _period_label(scope)
    return ChartSpec(
        key="wallet",
        tab="Share of wallet",
        title=f"Share of Marsh wallet by {label.lower()}"
              + (f", {period}" if period else "")
              + _where(scope),
        rows=rows,
        chart_type="bar",
        x=label,
        y=(WALLET_AXIS,),
        x_title=label,
        y_title=WALLET_AXIS,
    )


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ChartInputs:
    """Everything the catalogue can draw from, so every builder has one signature.

    `quarterly` needs rows the positioning pack does not carry; the others need
    the pack. Handing all of them the same record is what lets the catalogue be a
    table of functions rather than a chain of special cases.
    """

    pack: Optional[PositioningPack] = None
    quarterly_rows: Sequence[Mapping[str, Any]] = ()
    scope: Mapping[str, Any] = field(default_factory=dict)


def _from_pack(
    builder: Callable[..., Optional[ChartSpec]]
) -> Callable[[ChartInputs], Optional[ChartSpec]]:
    """Adapt a pack-shaped builder to the catalogue's one-argument signature."""

    def draw(inputs: ChartInputs) -> Optional[ChartSpec]:
        return builder(inputs.pack, scope=inputs.scope) if inputs.pack else None

    return draw


#: key -> the builder that draws it. Adding a chart is a row here plus a row in
#: `_ORDER`; nothing in the selector below changes (OCP).
_CATALOGUE: Mapping[str, Callable[[ChartInputs], Optional[ChartSpec]]] = {
    "premium": _from_pack(premium_chart),
    "contribution": _from_pack(contribution_chart),
    "wallet": _from_pack(wallet_chart),
    "quarterly": lambda inputs: quarterly_chart(
        inputs.quarterly_rows, scope=inputs.scope
    ),
}

#: Which charts matter most, per analytical operation, best first. A key whose
#: data is missing is skipped, so these are preferences and not promises.
#:
#: The default is the performance order: it is the richest question, and an
#: operation with no row here is one the patterns could not name — which is much
#: more likely to be a performance question than a penetration one.
_DEFAULT_ORDER: Tuple[str, ...] = ("quarterly", "contribution", "premium", "wallet")

_ORDER: Mapping[str, Tuple[str, ...]] = {
    PERFORMANCE: ("quarterly", "contribution", "premium", "wallet"),
    # What moved leads; the quarters say when it moved; the sizes say off what base.
    MOVEMENT: ("contribution", "quarterly", "premium"),
    # The reader asked where the carrier stands. Sizes first, standing beside them.
    POSITION: ("premium", "wallet", "contribution"),
    # Headroom is a share question: where the carrier is thin against a real book.
    PENETRATION: ("wallet", "premium", "contribution"),
    # A breakdown asked how premium is spread, which is the premium chart's job.
    BREAKDOWN: ("premium", "contribution", "wallet"),
}


def chart_order(operation: str) -> Tuple[str, ...]:
    """The chart keys this operation wants, best first."""
    return _ORDER.get((operation or "").strip().lower(), _DEFAULT_ORDER)


def build_chart_plan(
    pack: Optional[PositioningPack] = None,
    *,
    quarterly_rows: Sequence[Mapping[str, Any]] = (),
    scope: Mapping[str, Any] = (),
    operation: str = "",
    limit: int = MAX_CHARTS,
) -> List[ChartSpec]:
    """The charts this answer should carry, most informative first.

    Order is the OPERATION's order, not the data's — a movement question leads
    with what moved, a position question with how big each line is. A chart whose
    data is missing is skipped rather than drawn empty, so a thin turn produces
    fewer charts and never a blank one.
    """
    inputs = ChartInputs(pack=pack, quarterly_rows=quarterly_rows, scope=dict(scope or {}))
    drawn = (
        _CATALOGUE[key](inputs) for key in chart_order(operation) if key in _CATALOGUE
    )
    return [spec for spec in drawn if spec is not None][:limit]


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
