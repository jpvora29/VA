"""The "GWP Performance YoY" page — its TTM comparison table, panel totals and bar charts.

The page the author added to the country template carries four things the generic
slot/role path cannot fill, because the author wrote *real example figures* on it rather
than ``x``-placeholders (``Europe -1.0% GWP YoY growth``, ``€106.5m``, ``+6.1%▲``):

  * the **TTM table** — Marsh GWP · carrier GWP share · carrier rank · peer-average GWP ·
    peer-average share, each as current-period / prior-period / YoY-change;
  * the **panel totals** — the prior-year and current-year GWP either side of the
    New/Renewal waterfall, plus that waterfall's own YoY percentage;
  * the **page title** — ``<scope> <yoy>% GWP YoY growth``;
  * the two clustered **bar charts** — GWP by product line and GWP by country, CY vs PY.

Mirrors :mod:`studio.template_fill.grids` and :mod:`studio.template_fill.feedback`:
``augment`` re-binds the slots, ``values`` computes the texts, and both fold into the same
doc the preview and the fill engine already consume. Detection is caption/geometry driven
(never a slide index), so the page keeps filling if it moves or is restyled.

Conditional logic: the country bar chart only makes sense across SEVERAL countries. On a
single-country run it is filled with just that country's own CY/PY bar rather than the
template's authored example countries — see :func:`_country_series`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from logger import get_logger
from studio import compute as C
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template
from studio.template_fill.render import render_example
from studio.template_fill.sections import Section, section_of
from studio.template_fill.slots import Slot, classify

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_PRODUCT_COL = "Product_Line"
_REGION_COL = "Region"
_YEAR_COL = "Year"

ROLE_PREFIX = "gwp:"

# Row-label keyword → the metric that row reports. Ordered: "peer" wins over the plain
# carrier/Marsh readings so a "Peer average … Share %" row is never read as the carrier's.
_ROW_METRICS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("peer", "share"), "peer_sow"),
    (("peer",), "peer_gwp"),
    (("rank",), "rank"),
    (("share",), "sow"),
    (("marsh",), "marsh_gwp"),
)
# Metrics whose YoY change is a percentage-point move, not a percentage change.
_PP_METRICS = {"sow", "peer_sow"}

_YEAR_IN_TEXT = re.compile(r"\b(20\d{2})\b")
_PERIOD_LABEL = re.compile(r"^\s*(CY|PY)\s*$", re.I)
# A currency amount the author typed, e.g. "€106.5m" / "$1,234M" (no x-placeholder).
_EXAMPLE_MONEY = re.compile(r"^[^\dxX]{0,3}\d[\d,]*(?:\.\d+)?\s*[MmBbKk]?$")
_EXAMPLE_PCT = re.compile(r"^[+-]?\d+(?:\.\d+)?\s*%$")
# The page title: "<entity> <pct>% GWP YoY growth".
_TITLE = re.compile(r"^\s*(?P<lead>.*?)\s*(?P<pct>[+-]?\d+(?:\.\d+)?\s*%)(?P<tail>.*)$", re.S)


# ── page anatomy (caption + geometry driven) ─────────────────────────────────


@dataclass(frozen=True)
class TtmTable:
    """The TTM comparison table: which shape, and which column is current vs prior."""

    shape_id: int
    current_col: int
    prior_col: int
    change_col: Optional[int]
    rows: Tuple[Tuple[int, str], ...] = ()      # (row index, metric)


@dataclass(frozen=True)
class Panel:
    """The New/Renewal waterfall panel: the CY / PY total boxes and its YoY box."""

    current_id: Optional[int] = None
    prior_id: Optional[int] = None
    yoy_id: Optional[int] = None


@dataclass(frozen=True)
class Page:
    """Everything fillable on one GWP-performance page."""

    slide_idx: int
    title_id: Optional[int] = None
    table: Optional[TtmTable] = None
    panel: Panel = Panel()
    charts: Tuple[Tuple[int, str], ...] = ()    # (chart shape id, dimension column)


def _cx(sh: Shape) -> float:
    return sh.x + sh.w / 2.0


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _row_metric(label: str) -> Optional[str]:
    low = _norm(label)
    for keywords, metric in _ROW_METRICS:
        if all(k in low for k in keywords):
            return metric
    return None


def _ttm_table(slide: Slide) -> Optional[TtmTable]:
    """The TTM comparison table on ``slide`` — a table whose header names two periods.

    The CURRENT column is the one whose header carries the later year, so a template
    that lists the periods oldest-first still fills the right way round.
    """
    for sh in slide.shapes:
        table = sh.table if sh.kind == "table" else None
        if not table or len(table) < 2 or len(table[0]) < 3:
            continue
        years: List[Tuple[int, int]] = []            # (year, column)
        change_col: Optional[int] = None
        for c, cell in enumerate(table[0]):
            if "change" in _norm(cell):
                change_col = c
                continue
            found = _YEAR_IN_TEXT.findall(cell or "")
            if found:
                years.append((int(found[-1]), c))
        if len(years) < 2:
            continue
        years.sort()
        rows = tuple((r, m) for r, row in enumerate(table)
                     if r and (m := _row_metric(row[0] if row else "")))
        if not rows:
            continue
        return TtmTable(shape_id=sh.shape_id, current_col=years[-1][1], prior_col=years[0][1],
                        change_col=change_col, rows=rows)
    return None


def _panel(slide: Slide) -> Panel:
    """The waterfall panel's CY / PY value boxes and its YoY box, matched by geometry.

    The author labels the two columns ``PY`` and ``CY``; each total is the example money
    box nearest that label horizontally. The panel's YoY box is the only bare-percentage
    box on the page.
    """
    labels = {}
    for sh in slide.shapes:
        m = _PERIOD_LABEL.match(sh.text or "")
        if m:
            labels.setdefault(m.group(1).upper(), sh)
    money = [sh for sh in slide.shapes
             if sh.kind == "text" and _EXAMPLE_MONEY.match((sh.text or "").strip())]
    pcts = [sh for sh in slide.shapes
            if sh.kind == "text" and _EXAMPLE_PCT.match((sh.text or "").strip())]

    def nearest(label: Optional[Shape]) -> Optional[int]:
        if label is None or not money:
            return None
        return min(money, key=lambda s: abs(_cx(s) - _cx(label))).shape_id

    return Panel(current_id=nearest(labels.get("CY")), prior_id=nearest(labels.get("PY")),
                 yoy_id=(pcts[0].shape_id if pcts else None))


def _title_id(slide: Slide) -> Optional[int]:
    """The page-title shape — the topmost text shape whose text matches the title shape."""
    candidates = [sh for sh in slide.shapes
                  if sh.kind == "text" and _TITLE.match(sh.text or "")
                  and "gwp" in (sh.text or "").lower()]
    return min(candidates, key=lambda s: s.y).shape_id if candidates else None


def _classify_charts(slide: Slide, vocab: Dict[str, Sequence[str]]) -> Tuple[Tuple[int, str], ...]:
    """Map each clustered bar chart on ``slide`` to the dimension it breaks GWP down by.

    The signal is the chart's own AUTHORED categories scored against each dimension's
    real value vocabulary — so "Property / Marine / Cyber" reads as a product chart and
    "Germany / France / Spain" as a country chart, whatever order they sit in. When one
    chart matches and exactly one dimension is left over, the remaining chart takes it
    (an author's example categories are often placeholders that match nothing).
    """
    charts = [sh for sh in slide.shapes
              if sh.kind == "chart" and "CLUSTERED" in (sh.chart_type or "").upper()]
    if not charts:
        return ()

    def score(cats: Sequence[str], column: str) -> float:
        known = {_norm(v) for v in vocab.get(column, ())}
        cats = [c for c in cats if str(c).strip()]
        if not known or not cats:
            return 0.0
        return sum(1 for c in cats if _norm(str(c)) in known) / len(cats)

    assigned: Dict[int, str] = {}
    for sh in charts:
        best = max(vocab, key=lambda col: score(sh.chart_categories, col), default=None)
        if best is not None and score(sh.chart_categories, best) >= 0.4:
            assigned[sh.shape_id] = best
    unassigned = [sh for sh in charts if sh.shape_id not in assigned]
    spare = [col for col in vocab if col not in assigned.values()]
    if len(unassigned) == 1 and len(spare) == 1:
        assigned[unassigned[0].shape_id] = spare[0]
    return tuple((sh.shape_id, assigned[sh.shape_id]) for sh in charts if sh.shape_id in assigned)


def _gwp_slides(template: Template) -> List[Slide]:
    return [s for s in template.slides if section_of(s) is Section.GWP_PERFORMANCE]


def pages(template: Template, *, vocab: Optional[Dict[str, Sequence[str]]] = None) -> List[Page]:
    """Every GWP-performance page in ``template``, with its fillable parts located.

    ``vocab`` (``{dimension column: its real values}``) is only needed to work out which
    bar chart breaks GWP down by which dimension; ``augment`` can omit it because charts
    are written by the fill engine, not bound as slots.
    """
    return [
        Page(
            slide_idx=slide.index,
            title_id=_title_id(slide),
            table=_ttm_table(slide),
            panel=_panel(slide),
            charts=_classify_charts(slide, vocab) if vocab else (),
        )
        for slide in _gwp_slides(template)
    ]


# ── binding ──────────────────────────────────────────────────────────────────


def _role(slide_idx: int, *parts: Any) -> str:
    return ROLE_PREFIX + ":".join([str(slide_idx), *(str(p) for p in parts)])


def _slots_of(page: Page) -> List[Tuple[int, List[Any], str]]:
    """``[(shape_id, where, role)]`` for every fillable slot on ``page``."""
    out: List[Tuple[int, List[Any], str]] = []
    if page.title_id is not None:
        out.append((page.title_id, ["para", 0], _role(page.slide_idx, "title")))
    panel = page.panel
    for name, shape_id in (("cy", panel.current_id), ("py", panel.prior_id),
                           ("yoy", panel.yoy_id)):
        if shape_id is not None:
            out.append((shape_id, ["para", 0], _role(page.slide_idx, "panel", name)))
    table = page.table
    if table is not None:
        for col, when in ((table.current_col, "cy"), (table.prior_col, "py")):
            out.append((table.shape_id, ["cell", 0, col], _role(page.slide_idx, "period", when)))
        for row, metric in table.rows:
            for col, when in ((table.current_col, "cy"), (table.prior_col, "py")):
                out.append((table.shape_id, ["cell", row, col], _role(page.slide_idx, metric, when)))
            if table.change_col is not None:
                out.append((table.shape_id, ["cell", row, table.change_col],
                            _role(page.slide_idx, metric, "chg")))
    return out


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Re-bind (or add) every GWP-performance page slot to its ``gwp:`` role (idempotent)."""
    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    n = 0
    for page in pages(template):
        for shape_id, where, role in _slots_of(page):
            token = _token_at(template, page.slide_idx, shape_id, where)
            existing = by_key.get(Slot(page.slide_idx, shape_id, where, "", "text", "").key)
            if existing is not None:
                existing.role, existing.placeholder = role, False
            else:
                extra.append(R.Binding(
                    slot=Slot(page.slide_idx, shape_id, where, token,
                              classify(token) or "text", ""),
                    role=role, placeholder=False))
            n += 1
    if n:
        logger.info("gwp_page: bound %d slot(s) (%d added)", n, len(extra))
    return bindings + extra


def _token_at(template: Template, slide_idx: int, shape_id: int, where: List[Any]) -> str:
    sh = template.shape(slide_idx, shape_id)
    if sh is None:
        return ""
    if where and where[0] == "cell" and sh.table:
        r, c = int(where[1]), int(where[2])
        if r < len(sh.table) and c < len(sh.table[r]):
            return sh.table[r][c]
        return ""
    return sh.paragraphs[0] if sh.paragraphs else ""


# ── facts ────────────────────────────────────────────────────────────────────


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 — a failing metric must not break the fill
        logger.warning("gwp_page: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


@dataclass(frozen=True)
class Reading:
    """One table row's three numbers: current period, prior period, and the change.

    ``current_year`` / ``prior_year`` name the two periods (set on the Marsh reading, which
    is what the table's period headers are relabelled from).
    """

    current: Optional[float] = None
    prior: Optional[float] = None
    change: Optional[float] = None
    current_year: Optional[int] = None
    prior_year: Optional[int] = None


def _readings(result, filters: Dict[str, Any]) -> Dict[str, Reading]:
    """Every metric the page reports, for one filter scope, from the deterministic layer.

    ``carrier_gwp`` is the page's own subject — the "GWP Performance YoY" panel, its YoY box
    and the page title are all the CARRIER's book (as are both bar charts). ``marsh_gwp`` is
    the whole Marsh book, used only by the TTM row the author explicitly labels "Marsh GWP".
    """
    subject = result.subject
    marsh_filters = {k: v for k, v in filters.items() if k != _CARRIER_COL}

    carrier = _safe(C.period_totals, result.flow, filters, result.engine) or {}
    marsh = _safe(C.period_totals, result.flow, marsh_filters, result.engine) or {}
    sow = _safe(C.sow_movement, result.flow, filters, result.engine, subject) or {}
    rank = _safe(C.rank_movement, result.flow, filters, result.engine, subject) or {}
    peer = _safe(C.peer_average_totals, result.flow, filters, result.engine) or {}
    return {
        "carrier_gwp": Reading(carrier.get("current"), carrier.get("prior"), carrier.get("pct"),
                               carrier.get("current_year"), carrier.get("prior_year")),
        "marsh_gwp": Reading(marsh.get("current"), marsh.get("prior"), marsh.get("pct"),
                             marsh.get("current_year"), marsh.get("prior_year")),
        "sow": Reading(sow.get("current"), sow.get("prior"), sow.get("delta")),
        "rank": Reading(rank.get("current"), rank.get("prior"), rank.get("delta")),
        "peer_gwp": Reading(peer.get("current"), peer.get("prior"), peer.get("pct")),
        "peer_sow": Reading(peer.get("sow"), peer.get("sow_prior"),
                            _pp_delta(peer.get("sow"), peer.get("sow_prior"))),
    }


def _pp_delta(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    return None if (current is None or prior is None) else (current - prior)


def _reporting_filters(result) -> Dict[str, Any]:
    """The result's filters with the reporting year pinned (max pin, else latest in scope)."""
    from studio.template_fill.bindings import _latest_year_in_scope

    f = dict(result.resolved_filters or {})
    year = f.get(_YEAR_COL)
    if isinstance(year, (list, tuple, set)):
        year = max(int(y) for y in year) if year else None
    if year is None:
        year = _latest_year_in_scope(result, {k: v for k, v in f.items() if k != _YEAR_COL})
    if year is not None:
        f[_YEAR_COL] = int(year)
    return f


def _scope_label(result) -> str:
    """What the page is about: the pinned country, else the pinned region, else the carrier."""
    f = result.resolved_filters or {}
    for column in (_COUNTRY_COL, _REGION_COL):
        value = f.get(column)
        values = tuple(value) if isinstance(value, (list, tuple, set)) else ((value,) if value else ())
        if len(values) == 1:
            return str(values[0])
    return str(result.subject or "")


# ── bar-chart series ─────────────────────────────────────────────────────────


def _cy_py_by_dim(result, filters: Dict[str, Any], column: str,
                  *, divisor: float = 1e6) -> Optional[Dict[str, Any]]:
    """``{categories, cy, py}`` — premium by ``column`` for the current and prior year.

    Values are scaled by ``divisor`` (millions by default) because the page states its unit
    in the caption — "GWP Performance YoY (€M)" — so the bars must be in that unit, not raw
    currency. Categories are ordered by current-year premium, biggest first, so the chart
    reads like every other breakdown in the deck.
    """
    moves = _safe(C.movement_by_dim, result.flow, column, filters, result.engine, top=12) or []
    moves = [m for m in moves if str(m.get("name") or "").strip()]
    if not moves:
        return None
    moves.sort(key=lambda m: m.get("current") or 0.0, reverse=True)
    return {
        "categories": [str(m["name"]) for m in moves],
        "cy": [float(m.get("current") or 0.0) / divisor for m in moves],
        "py": [float(m.get("prior") or 0.0) / divisor for m in moves],
    }


def _country_series(result, filters: Dict[str, Any],
                    *, divisor: float = 1e6) -> Optional[Dict[str, Any]]:
    """The country bar chart's data — or a single bar when the run covers one country.

    A country-by-country comparison needs several countries. When the run is scoped to one
    (the user pinned a single country), the chart is filled with just that country's own
    CY/PY bar instead of the template's authored example countries, so no invented country
    ever reaches the deck.
    """
    scope = tuple(getattr(result, "scope_countries", ()) or ())
    if len(scope) == 1:
        return _cy_py_by_dim(result, {**filters, _COUNTRY_COL: scope[0]}, _COUNTRY_COL,
                             divisor=divisor)
    wide = dict(filters)
    if scope:
        wide[_COUNTRY_COL] = scope
    return _cy_py_by_dim(result, wide, _COUNTRY_COL, divisor=divisor)


_SERIES_BUILDERS = {
    _PRODUCT_COL: lambda result, filters, divisor: _cy_py_by_dim(
        result, filters, _PRODUCT_COL, divisor=divisor),
    _COUNTRY_COL: lambda result, filters, divisor: _country_series(
        result, filters, divisor=divisor),
}

# The unit a caption declares, e.g. "GWP Performance YoY (€M)" → millions. Millions is the
# default: it is what the shipped templates say, and raw currency would dwarf the axis.
_UNIT_DIVISOR = {"K": 1e3, "M": 1e6, "B": 1e9}
_UNIT_CAPTION = re.compile(r"\(\s*[^\w\s]?\s*([KMB])\s*\)", re.I)


def _chart_divisor(slide: Slide) -> float:
    """The scale the page's own caption asks the bars to be plotted in (default millions)."""
    for sh in slide.shapes:
        if sh.kind != "text":
            continue
        m = _UNIT_CAPTION.search(sh.text or "")
        if m:
            return _UNIT_DIVISOR[m.group(1).upper()]
    return _UNIT_DIVISOR["M"]


def _vocab(result) -> Dict[str, Sequence[str]]:
    """``{dimension column: its real values}`` — the chart-axis classifier's evidence."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    out: Dict[str, Sequence[str]] = {}
    for column in _SERIES_BUILDERS:
        base = {k: v for k, v in (result.resolved_filters or {}).items() if k != column}
        facts = _safe(
            compute_breakdown,
            PrimitiveArgs(flow=result.flow, metric="premium", group_by=(column,), filters=base),
            engine=result.engine,
        ) or []
        out[column] = [str(f.dims.get(column)) for f in facts if f.dims.get(column)]
    return out


# ── value resolution ─────────────────────────────────────────────────────────


def values(template: Template, result) -> Dict[str, Any]:
    """``{gwp-role: text}`` for every GWP-performance page, plus the ``gwp_bars`` payload.

    Numbers are rendered against the author's own example figures (see
    :func:`studio.template_fill.render.render_example`) so a ``€106.5m`` box stays in euros
    and millions and a ``+0.3 pp`` cell stays in percentage points.
    """
    if not _gwp_slides(template):
        return {}
    fy = _reporting_filters(result)
    scope = _scope_label(result)
    readings = _readings(result, fy)
    found = pages(template, vocab=_vocab(result))

    by_index = {s.index: s for s in template.slides}
    out: Dict[str, Any] = {}
    bars: Dict[str, Any] = {}
    for page in found:
        out.update(_table_values(template, page, readings))
        out.update(_panel_values(template, page, readings, scope))
        divisor = _chart_divisor(by_index[page.slide_idx])
        for shape_id, column in page.charts:
            series = _SERIES_BUILDERS[column](result, fy, divisor)
            if series:
                bars[f"{page.slide_idx}:{shape_id}"] = series
    if bars:
        out["gwp_bars"] = bars
    logger.info("gwp_page: resolved %d slot value(s), %d chart(s)", len(out), len(bars))
    return out


def _table_values(template: Template, page: Page,
                  readings: Dict[str, Reading]) -> Dict[str, Any]:
    """The TTM table's cells: raw numbers for the period columns, rendered change text.

    The row LABELS ("QBE GWP rank") are left to the fill engine's carrier substitution,
    which renames any authored carrier to the deck's own subject deck-wide.
    """
    table = page.table
    if table is None:
        return {}
    out: Dict[str, Any] = {}
    periods = readings.get("carrier_gwp", Reading())
    for col, when, year in ((table.current_col, "cy", periods.current_year),
                            (table.prior_col, "py", periods.prior_year)):
        if year is None:
            continue
        token = _token_at(template, page.slide_idx, table.shape_id, ["cell", 0, col])
        out[_role(page.slide_idx, "period", when)] = _YEAR_IN_TEXT.sub(str(year), token)
    for row, metric in table.rows:
        reading = readings.get(metric, Reading())
        if reading.current is not None:
            out[_role(page.slide_idx, metric, "cy")] = reading.current
        if reading.prior is not None:
            out[_role(page.slide_idx, metric, "py")] = reading.prior
        if table.change_col is not None and reading.change is not None:
            token = _token_at(template, page.slide_idx, table.shape_id,
                              ["cell", row, table.change_col])
            out[_role(page.slide_idx, metric, "chg")] = render_example(token, reading.change)
    return out


def _panel_values(template: Template, page: Page, readings: Dict[str, Reading],
                  scope: str) -> Dict[str, Any]:
    """The waterfall panel totals + the page title, rendered against their examples.

    All three report the CARRIER's GWP — the panel is captioned "GWP Performance YoY" on a
    carrier QBR page, so the whole Marsh book would be the wrong number here.
    """
    carrier = readings.get("carrier_gwp", Reading())
    out: Dict[str, Any] = {}
    for name, value in (("cy", carrier.current), ("py", carrier.prior)):
        shape_id = page.panel.current_id if name == "cy" else page.panel.prior_id
        if shape_id is None or value is None:
            continue
        token = _token_at(template, page.slide_idx, shape_id, ["para", 0])
        out[_role(page.slide_idx, "panel", name)] = render_example(token, value)
    if page.panel.yoy_id is not None and carrier.change is not None:
        token = _token_at(template, page.slide_idx, page.panel.yoy_id, ["para", 0])
        out[_role(page.slide_idx, "panel", "yoy")] = render_example(token, carrier.change)
    if page.title_id is not None and carrier.change is not None:
        token = _token_at(template, page.slide_idx, page.title_id, ["para", 0])
        title = _retitle(token, scope, carrier.change)
        if title:
            out[_role(page.slide_idx, "title")] = title
    return out


def _retitle(token: str, scope: str, yoy: float) -> Optional[str]:
    """``Europe -1.0% GWP YoY growth`` → ``<scope> <real yoy>% GWP YoY growth``."""
    m = _TITLE.match(token or "")
    if m is None:
        return None
    pct = render_example(m.group("pct"), yoy)
    lead = scope or m.group("lead")
    return f"{lead} {pct}{m.group('tail')}"
