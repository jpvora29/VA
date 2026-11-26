"""The "Marsh Portfolio and LC ranking" page — one quadrant panel per country.

The page the author drew: for each country, a scatter of that country's lines of business
placed by how much Marsh premium sits in the line (x, "Size of Marsh Portfolio") against
where the carrier ranks in it (y, "Carrier Rank", best at the top). Behind the points the
author painted a four-colour priority matrix — the red bottom-right corner is a big pool the
carrier is not winning, the green top-right one it already leads — so the page answers
"where is the money, and where do we stand in it" in one read.

We keep that page exactly as authored and fill it with real numbers: the panel's own chart
is REFILLED (its markers, axis lines and painted bands survive untouched), only the
furniture drawn around the author's example points — the faked broken axis and the
hand-placed ``Product (n)`` labels — comes off, because the chart now labels its own.

What IS dynamic is the panel COUNT (:func:`plan_layout`): one country gets the whole page
rather than a quarter of it, two share it side by side at full height, three or four keep
the author's 2x2 grid. More countries than the page has panels spill onto CONTINUATION
pages — :func:`page_count` says how many, and ``values(..., page=n)`` fills page ``n`` with
countries ``n*panels+1`` onwards (the assembler repeats the slide once per extra page).

Mirrors :mod:`studio.template_fill.gwp_page`: detection is section/geometry driven (never a
slide index), ``values`` emits one payload per panel keyed ``slide:shape``, and the fill
engine consumes it alongside the other chart payloads.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Dict, List, Sequence, Tuple

from logger import get_logger
from studio import compute as C
from studio.template_fill.analyze import Slide, Template
from studio.template_fill.sections import Section, section_of

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_PRODUCT_COL = "Product_Line"

# More points than a panel can carry without its labels colliding. The author drew four;
# a full-page single-country panel can hold more, but the 2x2 grid sets the ceiling.
# The ceiling only trims the lines OUTSIDE the top 5: a line the carrier ranks top 5 in is
# what the page exists to show, so it is never cut (see :func:`select_lines`).
_MAX_POINTS = 6

# The deepest rank the panel's own scale draws. The author's rank axis runs 0–11 with a
# tick per rank, and their painted band boundary sits on the top-5 line of THAT scale — so
# the axis never stretches. A deeper rank sits on the floor row and says its real rank in
# its label ("Marine (#23)"), instead of widening the axis to 24 ticks that crush every
# other point into the top of the panel and slide the bands off their ranks.
DEEPEST_DRAWN_RANK = 10
FLOOR_ROW = DEEPEST_DRAWN_RANK + 0.5

# Rank → the band its point falls in. Ordered best first; the split at 5 is the same top-5
# the deck benchmarks every carrier against ("Peer average GWP 1-5"), and the same split the
# author's painted bands sit on.
LEAD = "lead"            # #1–2  — the position to defend
STRONG = "strong"        # #3–5  — inside the top 5
CHASING = "chasing"      # #6–8  — outside it, within reach
BEHIND = "behind"        # #9+   — the ground to make up
_BANDS: Tuple[Tuple[int, str], ...] = ((2, LEAD), (5, STRONG), (8, CHASING))
_TOP_RANK = 5


def band_of(rank: int) -> str:
    """Which rank band a position falls in."""
    for limit, band in _BANDS:
        if rank <= limit:
            return band
    return BEHIND


@dataclass(frozen=True)
class Rect:
    """A panel's frame in absolute EMU."""

    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class Panel:
    """One panel on the page: the chart that holds it and the frame it occupies."""

    slide_idx: int
    shape_id: int
    frame: Rect


@dataclass(frozen=True)
class RankPoint:
    """One line of business: the Marsh pool it holds, the carrier's rank in it, its band."""

    name: str
    size: float
    rank: int
    band: str

    @property
    def row(self) -> float:
        """Where the point sits on the rank axis — its rank, or the floor row past the scale."""
        return float(self.rank) if self.rank <= DEEPEST_DRAWN_RANK else FLOOR_ROW

    @property
    def label(self) -> str:
        """The point's name; a point on the floor row also states the rank it stands for."""
        return self.name if self.rank <= DEEPEST_DRAWN_RANK else f"{self.name} (#{self.rank})"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "size": self.size, "rank": self.rank, "band": self.band,
                "row": self.row, "label": self.label}


# ── page anatomy ─────────────────────────────────────────────────────────────


def _panel_charts(slide: Slide) -> List[Any]:
    """The panel charts on ``slide``, in reading order (top row left-to-right).

    Sorted by BAND rather than raw ``y``: the two panels of a row are authored a hair apart
    vertically, which a plain ``(y, x)`` sort would read as four rows of one.
    """
    charts = [sh for sh in slide.shapes
              if sh.kind == "chart" and "SCATTER" in (sh.chart_type or "").upper()]
    if not charts:
        return []
    band = min(sh.h for sh in charts) or 1
    return sorted(charts, key=lambda sh: (round(sh.y / band), sh.x))


def panels(template: Template) -> List[Panel]:
    """Every panel in ``template``, in the order the countries fill them."""
    return [Panel(slide.index, sh.shape_id, Rect(sh.x, sh.y, sh.w, sh.h))
            for slide in template.slides if section_of(slide) is Section.RANKING
            for sh in _panel_charts(slide)]


def _union(frames: Sequence[Rect]) -> Rect:
    left, top = min(f.x for f in frames), min(f.y for f in frames)
    right = max(f.x + f.w for f in frames)
    bottom = max(f.y + f.h for f in frames)
    return Rect(left, top, right - left, bottom - top)


def plan_layout(frames: Sequence[Rect], live: int) -> List[Rect]:
    """Where the ``live`` panels sit, given the frames the author drew.

    One country deserves the whole page rather than a quarter of it; two share it side by
    side at full height; three or four keep the author's own grid. Derived from the frames
    themselves — the author's column split and margins survive a re-laid-out template.
    """
    if live <= 0 or live > len(frames):
        return list(frames)
    if live == 1:
        return [_union(frames)]
    if live == 2:
        whole = _union(frames)
        return [Rect(f.x, whole.y, f.w, whole.h) for f in frames[:2]]
    return list(frames[:live])


# ── facts ────────────────────────────────────────────────────────────────────


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 — a failing panel must not break the fill
        logger.warning("lc_page: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def _reporting_filters(result) -> Dict[str, Any]:
    """The result's filters with the reporting year pinned and the product pin widened
    back to the RUN's own selection.

    The page is a PORTFOLIO view: its panels rank a country's lines of business against
    each other, so a per-product sub-deck's own single-value pin would leave every panel
    with one point. Widening it to ``scope_products`` — the lines the user picked in Setup —
    keeps the page inside that selection instead of silently ranking the whole book; with
    no selection there is nothing to widen to, so the pin simply comes off.
    """
    from studio.template_fill.bindings import reporting_filters

    filters = reporting_filters(result, drop=(_PRODUCT_COL,))
    selection = tuple(getattr(result, "scope_products", ()) or ())
    if selection:
        filters[_PRODUCT_COL] = selection
    return filters


def _marsh_pool(result, filters: Dict[str, Any]) -> Dict[str, float]:
    """``{line of business: the whole Marsh premium in it}`` — each point's x position."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    base = {k: v for k, v in filters.items() if k != _CARRIER_COL}
    facts = _safe(
        compute_breakdown,
        PrimitiveArgs(flow=result.flow, metric="premium", group_by=(_PRODUCT_COL,),
                      filters=base),
        engine=result.engine,
    ) or []
    return {str(f.dims.get(_PRODUCT_COL)): float(f.value or 0.0)
            for f in facts if f.dims.get(_PRODUCT_COL)}


def select_lines(rows: Sequence[dict[str, Any]], *, cap: int = _MAX_POINTS) -> list[dict[str, Any]]:
    """The lines a panel plots: EVERY line the carrier ranks top 5 in, then its biggest
    other lines up to ``cap``.

    ``rows`` arrive biggest carrier premium first (``product_breakdown_rows``) and carry
    a rank. Taking the first ``cap`` of them used to drop a line the carrier ranks #2 in
    whenever six bigger lines of its own came first — the very point the green corner of
    the page exists to show. Lines with no rank have no height to plot and are skipped.
    """
    ranked = [r for r in rows if r.get("rank") is not None]
    top = [r for r in ranked if int(r["rank"]) <= _TOP_RANK]
    room = max(cap - len(top), 0)
    rest = [r for r in ranked if int(r["rank"]) > _TOP_RANK][:room]
    keep = {id(r) for r in (*top, *rest)}
    return [r for r in ranked if id(r) in keep]


def rank_points(result, filters: Dict[str, Any]) -> List[RankPoint]:
    """One country's lines of business, biggest Marsh pool first.

    Ranked lines only: a point with no rank has no height to plot, and the page is about
    where the carrier stands. Every top-5 line is kept (:func:`select_lines`).
    """
    rows = _safe(C.product_breakdown_rows, result.flow, filters, result.engine,
                 result.subject, top=None) or []
    pool = _marsh_pool(result, filters)
    chosen = select_lines(rows)
    placed = [(str(r["name"]), pool.get(str(r["name"])), int(r["rank"])) for r in chosen]
    placed = [(n, s, k) for n, s, k in placed if s]
    placed.sort(key=lambda row: row[1], reverse=True)
    return [RankPoint(n, s, k, band_of(k)) for n, s, k in placed]


def _countries(result) -> List[str]:
    """Countries by premium, biggest first — the order the ``Country (n)`` panels use."""
    from studio.template_fill.bindings import _country_breakdown

    return [r["name"] for r in _country_breakdown(result) if r.get("name")]


# ── value resolution ─────────────────────────────────────────────────────────


def ranking_slides(template: Template) -> tuple[int, ...]:
    """Indices of the slides that carry ranking panels — the page a continuation repeats."""
    return tuple(dict.fromkeys(p.slide_idx for p in panels(template)))


def page_count(template: Template, result) -> int:
    """How many ranking pages ``result``'s countries need: four panels a page, at least one."""
    capacity = len(panels(template))
    if not capacity:
        return 0
    return max(1, math.ceil(len(_countries(result)) / capacity))


def page_countries(template: Template, result, page: int) -> list[str]:
    """The countries ranking page ``page`` (0-based) carries, biggest book first."""
    capacity = len(panels(template))
    return _countries(result)[page * capacity:(page + 1) * capacity]


def values_for_page(page: int) -> Callable[[Template, Any], dict[str, Any]]:
    """A provider that fills continuation page ``page`` (same signature as :func:`values`)."""
    return partial(values, page=page)


def drop_highlights(template: Template, result) -> dict[str, Any]:
    """Drop the one-cell "Key Highlights" table off the ranking pages.

    A continuation page repeats the ranking slide for the countries the first page had no
    panel for; its highlights would only restate the first page's, so the box comes off.
    """
    drop = [f"{slide.index}:{sh.shape_id}"
            for slide in template.slides if section_of(slide) is Section.RANKING
            for sh in slide.shapes if _is_highlights_table(sh)]
    return {"drop_shapes": drop} if drop else {}


def _is_highlights_table(shape) -> bool:
    table = getattr(shape, "table", None) or []
    return (shape.kind == "table" and len(table) == 1 and len(table[0]) == 1
            and "key highlight" in str(table[0][0]).lower())


def values(template: Template, result, *, page: int = 0) -> dict[str, Any]:
    """``{"lc_ranking": {"slide:shape": panel payload}}`` for EVERY panel on the page.

    A panel beyond the countries in scope gets a payload with no points, which tells the fill
    engine to blank it — and the panels that remain are re-laid-out to take the space back,
    so a two-country deck shows two half-page panels rather than two quarters and a void.
    ``page`` picks which run of countries the panels show (0 = the first four).

    Panel ``i`` always draws country ``i``: its title is the ``Country (i+1)`` label, which
    the fill engine has already written by the time the charts are filled. A country with
    nothing to rank leaves its own panel blank rather than letting the next country's data
    slide in under its name; the live panels then take the planned frames in reading order
    (each carrying its title with it), so the gap is closed all the same.
    """
    found = panels(template)
    if not found:
        return {}
    filters = _reporting_filters(result)
    countries = page_countries(template, result, page)
    drawn = [rank_points(result, {**filters, _COUNTRY_COL: c}) for c in countries]
    live = [i for i, points in enumerate(drawn) if points]
    rects = plan_layout([p.frame for p in found], len(live))
    placed = dict(zip(live, rects))

    out: dict[str, Any] = {}
    for i, panel in enumerate(found):
        points = drawn[i] if i in placed else []
        out[f"{panel.slide_idx}:{panel.shape_id}"] = {
            "country": countries[i] if i in placed else None,
            "points": [p.to_dict() for p in points],
            "rect": placed.get(i, panel.frame).to_dict(),
        }
    logger.info("lc_page: page %d — %d of %d panel(s) filled, laid out %d-up",
                page + 1, len(live), len(found), max(len(live), 1))
    return {"lc_ranking": out}
