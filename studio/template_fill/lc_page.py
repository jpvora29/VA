"""The "Marsh Portfolio and LC ranking" page — one pool-bar panel per country.

Each panel ranks the lines of business in one country by the size of the *Marsh* portfolio
in them, and colours each bar by where the *carrier* ranks in that pool: the greens are the
top-5 positions, the reds are the ones being chased. Every bar is labelled with both
numbers, so the page answers "where is the money, and where do we stand in it" in one read.

The template authors this as a 2×2 grid of hand-drawn quadrant scatters. A scatter needs
area, and the authored panel is a 3.4:1 letterbox, so rank collapses into overlapping bands
of dots; a bar takes its labels from the category axis and cannot collide. The panel COUNT
adapts too — one country gets the whole page rather than a quarter of it, two share it side
by side, three or four keep the author's grid (:func:`plan_layout`).

Mirrors :mod:`studio.template_fill.gwp_page`: detection is section/geometry driven (never a
slide index), ``values`` emits one payload per panel keyed ``slide:shape``, and the fill
engine consumes it alongside the other chart payloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from logger import get_logger
from studio import compute as C
from studio.template_fill.analyze import Slide, Template
from studio.template_fill.render import _money
from studio.template_fill.sections import Section, section_of

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_PRODUCT_COL = "Product_Line"
_YEAR_COL = "Year"

# More lines than a panel can carry as readable rows.
_MAX_POINTS = 8

# Rank → the band its bar is coloured by. Ordered best first; the split at 5 is the same
# top-5 the deck benchmarks every carrier against ("Peer average GWP 1-5"), so the greens
# are exactly the positions the rest of the deck calls a top-5 position.
LEAD = "lead"            # #1–2  — the position to defend
STRONG = "strong"        # #3–5  — inside the top 5
CHASING = "chasing"      # #6–8  — outside it, within reach
BEHIND = "behind"        # #9+   — the ground to make up
_BANDS: Tuple[Tuple[int, str], ...] = ((2, LEAD), (5, STRONG), (8, CHASING))


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
class PoolBar:
    """One line of business: the Marsh pool, the carrier's rank in it, and its band."""

    name: str
    size: float
    rank: int
    band: str

    @property
    def label(self) -> str:
        """What the bar says: the pool it represents, and the position held in it."""
        return f"{_money(self.size)}  ·  #{self.rank}"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "size": self.size, "rank": self.rank,
                "band": self.band, "label": self.label}


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
    """The result's filters with the reporting year pinned, and the product pin dropped.

    The page is a PORTFOLIO view: its panels rank a country's lines of business against
    each other, so a per-product sub-deck's own pin would leave every panel a single bar.
    Same rule the overall block already applies
    (:func:`studio.template_fill.bindings.scope_overall`).
    """
    from studio.template_fill.bindings import _latest_year_in_scope

    f = {k: v for k, v in (result.resolved_filters or {}).items() if k != _PRODUCT_COL}
    year = f.get(_YEAR_COL)
    if isinstance(year, (list, tuple, set)):
        year = max(int(y) for y in year) if year else None
    if year is None:
        year = _latest_year_in_scope(result, {k: v for k, v in f.items() if k != _YEAR_COL})
    if year is not None:
        f[_YEAR_COL] = int(year)
    return f


def _marsh_pool(result, filters: Dict[str, Any]) -> Dict[str, float]:
    """``{line of business: the whole Marsh premium in it}`` — the length of each bar."""
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


def bars(result, filters: Dict[str, Any]) -> List[PoolBar]:
    """One country's lines of business, biggest Marsh pool first.

    Ranked lines only: a bar with no rank has no colour to carry, and the page is about
    where the carrier stands.
    """
    rows = _safe(C.product_breakdown_rows, result.flow, filters, result.engine,
                 result.subject, top=_MAX_POINTS) or []
    pool = _marsh_pool(result, filters)
    placed = [(str(r["name"]), pool.get(str(r["name"])), r.get("rank")) for r in rows]
    placed = [(n, s, int(k)) for n, s, k in placed if s and k is not None]
    placed.sort(key=lambda row: row[1], reverse=True)
    return [PoolBar(n, s, k, band_of(k)) for n, s, k in placed]


def _countries(result) -> List[str]:
    """Countries by premium, biggest first — the order the ``Country (n)`` panels use."""
    from studio.template_fill.bindings import _country_breakdown

    return [r["name"] for r in _country_breakdown(result) if r.get("name")]


# ── value resolution ─────────────────────────────────────────────────────────


def values(template: Template, result) -> Dict[str, Any]:
    """``{"lc_ranking": {"slide:shape": panel payload}}`` for EVERY panel on the page.

    A panel beyond the countries in scope gets a payload with no bars, which tells the fill
    engine to blank it — and the panels that remain are re-laid-out to take the space back,
    so a two-country deck shows two half-page panels rather than two quarters and a void.
    """
    found = panels(template)
    if not found:
        return {}
    filters = _reporting_filters(result)
    countries = _countries(result)[:len(found)]
    drawn = [bars(result, {**filters, _COUNTRY_COL: c}) for c in countries]
    drawn = [d for d in drawn if d]
    rects = plan_layout([p.frame for p in found], len(drawn))

    out: Dict[str, Any] = {}
    for i, panel in enumerate(found):
        live = drawn[i] if i < len(drawn) else []
        out[f"{panel.slide_idx}:{panel.shape_id}"] = {
            "country": countries[i] if i < len(drawn) else None,
            "bars": [b.to_dict() for b in live],
            "rect": (rects[i] if i < len(rects) else panel.frame).to_dict(),
        }
    logger.info("lc_page: %d of %d panel(s) filled, laid out %d-up",
                len(drawn), len(found), max(len(drawn), 1))
    return {"lc_ranking": out}
