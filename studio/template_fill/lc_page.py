"""The "Marsh Portfolio and LC ranking" page — one quadrant scatter per country.

Each panel plots, for one country, every line of business as a point:

  * **x** — the size of the *Marsh* portfolio in that country × line (the pool available);
  * **y** — the *carrier's* rank in it (axis reversed, so #1 sits at the top).

Two thresholds cut the panel into four quadrants: the top-5 rank line the template already
draws, and the MEDIAN portfolio size of the lines plotted (so the split stays meaningful
whatever a country's scale). The quadrant a point lands in is the page's whole message —
a large Marsh pool the carrier does not lead is the gap worth talking about — so it is
carried on the marker itself; :mod:`studio.template_fill.fill` paints it and strips the
template's painted bands.

Mirrors :mod:`studio.template_fill.gwp_page`: detection is section/geometry driven (never a
slide index), ``values`` emits one payload per panel keyed ``slide:shape``, and the fill
engine consumes it alongside the other chart payloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio import compute as C
from studio.template_fill.analyze import Slide, Template
from studio.template_fill.sections import Section, section_of

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_PRODUCT_COL = "Product_Line"
_YEAR_COL = "Year"

# The rank that separates a led book from a chased one — the same top-5 the deck benchmarks
# every carrier against ("Peer average GWP 1-5"), and the line the template already draws.
RANK_CUT = 5
# More lines than a small panel can label without collapsing into overlapping text.
_MAX_POINTS = 8


@dataclass(frozen=True)
class Panel:
    """One quadrant scatter on the page, and the country it reports."""

    slide_idx: int
    shape_id: int


@dataclass(frozen=True)
class QuadrantPoint:
    """One line of business: the Marsh pool, the carrier's rank in it, and the verdict."""

    name: str
    size: float
    rank: int
    quadrant: str

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "size": self.size, "rank": self.rank,
                "quadrant": self.quadrant}


# Quadrant names say what the position MEANS, so the palette (a rendering concern) stays in
# the fill engine and this module stays about the book.
LEAD = "lead"         # top-5 rank, large pool — the position to defend
SOLID = "solid"       # top-5 rank, small pool — won, but not much at stake
MINOR = "minor"       # outside the top 5, small pool — least material
GAP = "gap"           # outside the top 5, large pool — the opportunity


def quadrant_of(size: float, rank: int, *, size_cut: float, rank_cut: int = RANK_CUT) -> str:
    """Which quadrant a point falls in. Ties count as the stronger/larger side."""
    large = size >= size_cut
    if rank <= rank_cut:
        return LEAD if large else SOLID
    return GAP if large else MINOR


# ── page anatomy ─────────────────────────────────────────────────────────────


def _scatters(slide: Slide) -> List[Any]:
    """The panel scatters on ``slide``, in reading order (top row left-to-right).

    Sorted by band rather than raw ``y``: the two panels of a row are authored a hair
    apart vertically, which a plain ``(y, x)`` sort would read as four rows of one.
    """
    charts = [sh for sh in slide.shapes
              if sh.kind == "chart" and "SCATTER" in (sh.chart_type or "").upper()]
    if not charts:
        return []
    band = min(sh.h for sh in charts) or 1.0
    return sorted(charts, key=lambda sh: (round(sh.y / band), sh.x))


def panels(template: Template) -> List[Panel]:
    """Every quadrant-scatter panel in ``template``, in the order the countries fill them."""
    return [Panel(slide.index, sh.shape_id)
            for slide in template.slides if section_of(slide) is Section.RANKING
            for sh in _scatters(slide)]


# ── facts ────────────────────────────────────────────────────────────────────


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 — a failing panel must not break the fill
        logger.warning("lc_page: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def _reporting_filters(result) -> Dict[str, Any]:
    """The result's filters with the reporting year pinned, and the product pin dropped.

    The page is a PORTFOLIO view: its panels break a country down BY line of business, so a
    per-product sub-deck's own pin would collapse every panel to a single point. Same rule
    the overall block already applies (:func:`studio.template_fill.bindings.scope_overall`).
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
    """``{line of business: the whole Marsh premium in it}`` — the x axis of the panel."""
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


def points(result, filters: Dict[str, Any]) -> List[QuadrantPoint]:
    """Every line of business in one country, placed against both thresholds.

    Ranked lines only: a point needs a rank to have a vertical position at all.
    """
    rows = _safe(C.product_breakdown_rows, result.flow, filters, result.engine,
                 result.subject, top=_MAX_POINTS) or []
    pool = _marsh_pool(result, filters)
    placed = [(str(r["name"]), pool.get(str(r["name"])), r.get("rank")) for r in rows]
    placed = [(n, s, int(k)) for n, s, k in placed if s and k is not None]
    if not placed:
        return []
    cut = median(s for _, s, _ in placed)
    return [QuadrantPoint(n, s, k, quadrant_of(s, k, size_cut=cut)) for n, s, k in placed]


def _countries(result) -> List[str]:
    """Countries by premium, biggest first — the order the ``Country (n)`` panels use."""
    from studio.template_fill.bindings import _country_breakdown

    return [r["name"] for r in _country_breakdown(result) if r.get("name")]


# ── value resolution ─────────────────────────────────────────────────────────


def values(template: Template, result) -> Dict[str, Any]:
    """``{"lc_quadrant": {"slide:shape": panel payload}}`` for EVERY panel on the page.

    A panel beyond the countries in scope gets a payload with no points, which tells the
    fill engine to blank it — a deck with three countries must not ship a fourth panel of
    the template's authored example book under a title that has been rubbed out.
    """
    found = panels(template)
    if not found:
        return {}
    filters = _reporting_filters(result)
    countries = _countries(result)
    out: Dict[str, Any] = {}
    for i, panel in enumerate(found):
        country = countries[i] if i < len(countries) else None
        placed = points(result, {**filters, _COUNTRY_COL: country}) if country else []
        out[f"{panel.slide_idx}:{panel.shape_id}"] = {
            "country": country,
            "points": [p.to_dict() for p in placed],
            "rank_cut": RANK_CUT,
            "size_cut": median(p.size for p in placed) if placed else 0.0,
        }
    filled = sum(1 for p in out.values() if p["points"])
    logger.info("lc_page: resolved %d of %d quadrant panel(s)", filled, len(found))
    return {"lc_quadrant": out}
