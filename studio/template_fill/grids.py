"""Per-product breakdown-grid detection and binding — the 'Carrier breakdown' table.

The generic slot/role path fills one scalar per slot, so a per-product grid (one row
per product line: GWP · Var % · SoW · Rank · Rank change · Peer GWP · Runway to Top 5)
ends up with the SAME carrier total repeated down every row. This module recognises that
grid and binds each *cell* to a positional, per-slide role
``grid:<slide_idx>:<row>:<metric>`` so each row carries its own product's numbers.

Two authoring shapes are supported, tried in that order by :func:`_detect`:

  * a real PowerPoint **table** (the current templates) — columns come straight from the
    header row, so the mapping is exact;
  * loose **text placeholders** laid out as a grid (the earlier templates) — columns and
    rows are recovered from geometry.

Either way detection is generic (it fires only on a slide that actually has the
GWP/Var/SoW/Rank header set — never on unrelated slides), so a template edit that
reorders columns, adds a column, or converts the grid to a table keeps working. Each
breakdown slide is scoped to one country (``Carrier breakdown – Country (1)``/(2)…),
matched positionally to the carrier's countries so the table agrees with its own label.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template
from studio.template_fill.slots import Slot, classify

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"

# Normalised header text → metric key. "rank" must be exact so "rank change" is its own.
_HEADER_METRIC = {
    "product": "name", "gwp": "gwp", "var %": "var", "var": "var", "sow": "sow",
    "rank": "rank", "rank change": "rank_change", "peer gwp": "peer_gwp",
}
_METRIC_COLS = ("name", "gwp", "var", "sow", "rank", "rank_change")
_REQUIRED = {"name", "gwp", "var", "sow", "rank"}
# Every metric a grid row can carry — the keys ``grid_values`` emits and ``augment`` binds.
_ROW_METRICS = ("name", "gwp", "var", "sow", "rank", "rank_change", "peer_gwp", "runway")


@dataclass(frozen=True)
class Grid:
    """One breakdown grid: how many product rows, and where each cell lives.

    ``cells`` are ``(shape_id, where, metric, row)`` — ``where`` is a ``['cell', r, c]``
    for a table grid or a ``['para', 0]`` for a placeholder grid, so the same binding and
    fill code serves both authoring shapes.
    """

    row_count: int
    cells: Tuple[Tuple[int, List[Any], str, int], ...] = ()
    subtitle_id: Optional[int] = None
    runway_chart_id: Optional[int] = None

# A subtitle like "Carrier breakdown – Country (1)" — its (n) is hard-coded on EVERY
# breakdown slide, so it must be re-resolved per slide to the slide's own country.
_PAREN_NUM = re.compile(r"\(\s*\d+\s*\)")
_COUNTRY_TOKEN = re.compile(r"(?:Country\s*/\s*)?(?:Country|Region)\s*\(\s*\d+\s*\)", re.I)
_CARRIER_TOKEN = re.compile(r"Carriers?(?:['’]s)?")


def _cx(sh: Shape) -> float:
    return sh.x + sh.w / 2.0


def _cy(sh: Shape) -> float:
    return sh.y + sh.h / 2.0


def _is_slot(sh: Shape) -> bool:
    return bool(sh.paragraphs) and classify(sh.paragraphs[0]) is not None


def _headers(slide: Slide) -> Tuple[Dict[str, float], Optional[float], float]:
    """Column-x by metric, the runway header x (if any), and the header row's y."""
    cols: Dict[str, float] = {}
    runway_x: Optional[float] = None
    header_y = 0.0
    for sh in slide.shapes:
        if sh.kind != "text" or not sh.text.strip():
            continue
        t = " ".join(sh.text.split()).strip().lower()
        if "runway" in t:
            runway_x, header_y = _cx(sh), max(header_y, _cy(sh))
            continue
        metric = _HEADER_METRIC.get(t)
        if metric and metric not in cols:
            cols[metric] = _cx(sh)
            header_y = max(header_y, _cy(sh))
    return cols, runway_x, header_y


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _subtitle_id(slide: Slide, above_y: float) -> Optional[int]:
    """The hard-coded ``… – Country (n)`` subtitle sitting above the grid, if any."""
    for sh in slide.shapes:
        if (sh.kind == "text" and _cy(sh) < above_y and _PAREN_NUM.search(sh.text)
                and re.search(r"country|region|breakdown", sh.text, re.I)):
            return sh.shape_id
    return None


def _table_columns(header: List[str]) -> Tuple[Dict[str, int], Optional[int]]:
    """``{metric: column index}`` from a grid table's header row, plus the runway column."""
    cols: Dict[str, int] = {}
    runway_col: Optional[int] = None
    for c, cell in enumerate(header):
        text = _norm(cell)
        if "runway" in text:
            runway_col = c
            continue
        metric = _HEADER_METRIC.get(text)
        if metric and metric not in cols:
            cols[metric] = c
    return cols, runway_col


def _runway_label_ids(slide: Slide) -> List[int]:
    """Shape ids of the runway bar value labels, top to bottom.

    On a TABLE grid the rows live inside the table, so any *shape-level* money
    placeholder left on the slide is a runway bar label (the runway is drawn as a bar
    chart picture with its values as free text boxes, one per product row).
    """
    labels = [sh for sh in slide.shapes
              if sh.kind == "text" and sh.paragraphs
              and classify(sh.paragraphs[0]) == "money"]
    return [sh.shape_id for sh in sorted(labels, key=_cy)]


def _covers(outer: Shape, inner: Shape) -> bool:
    return (outer.x <= _cx(inner) <= outer.x + outer.w
            and outer.y <= _cy(inner) <= outer.y + outer.h)


def _runway_chart_id(slide: Slide, label_ids: List[int]) -> Optional[int]:
    """The picture the runway bars are drawn on — the one every value label sits over.

    Identified through the labels rather than by position: they are the shapes already
    known to belong to the runway, one per product row, and they are drawn ON the bars.
    """
    wanted = set(label_ids)
    labels = [sh for sh in slide.shapes if sh.shape_id in wanted]
    if not labels:
        return None
    for sh in slide.shapes:
        if sh.kind == "picture" and all(_covers(sh, label) for label in labels):
            return sh.shape_id
    return None


def _detect_table(slide: Slide) -> Optional[Grid]:
    """The breakdown grid authored as a real PowerPoint table, or None."""
    for sh in slide.shapes:
        table = sh.table if sh.kind == "table" else None
        if not table or len(table) < 2:
            continue
        cols, runway_col = _table_columns(table[0])
        if not _REQUIRED <= set(cols):
            continue

        data_rows = list(range(1, len(table)))
        cells: List[Tuple[int, List[Any], str, int]] = []
        for row, r in enumerate(data_rows):
            for metric, c in cols.items():
                if c < len(table[r]):
                    cells.append((sh.shape_id, ["cell", r, c], metric, row))

        # The runway column is authored empty (its values are free text boxes over the
        # bar picture); bind those, positionally, when the column exists at all.
        chart_id = None
        if runway_col is not None:
            label_ids = _runway_label_ids(slide)
            for row, shape_id in enumerate(label_ids[:len(data_rows)]):
                cells.append((shape_id, ["para", 0], "runway", row))
            chart_id = _runway_chart_id(slide, label_ids)

        return Grid(row_count=len(data_rows), cells=tuple(cells),
                    subtitle_id=_subtitle_id(slide, sh.y), runway_chart_id=chart_id)
    return None


def _detect(slide: Slide) -> Optional[Grid]:
    """The breakdown grid on ``slide`` (table first, then a placeholder layout), or None."""
    return _detect_table(slide) or _detect_placeholders(slide)


def _detect_placeholders(slide: Slide) -> Optional[Grid]:
    """The breakdown grid authored as loose text placeholders, recovered by geometry.

    Returns a :class:`Grid` whose ``cells`` include synthesised entries for the static
    product-name and rank-change boxes (which are not ``x``-placeholder slots).
    """
    cols, runway_x, header_y = _headers(slide)
    if not _REQUIRED <= set(cols):
        return None

    spacing = abs(cols["gwp"] - cols["name"]) or 1.0
    col_tol = spacing * 0.6
    region = [s for s in slide.shapes if s.kind == "text" and _cy(s) > header_y + spacing * 0.1
              and s.text.strip()]

    # Row anchors = the y of each GWP-column value slot (exactly one per row).
    gwp_x = cols["gwp"]
    anchors = sorted(_cy(s) for s in region if _is_slot(s) and abs(_cx(s) - gwp_x) < col_tol)
    if not anchors:
        return None
    row_tol = (min(b - a for a, b in zip(anchors, anchors[1:])) / 2.0) if len(anchors) > 1 else spacing

    def row_of(sh: Shape) -> Optional[int]:
        cy = _cy(sh)
        best = min(range(len(anchors)), key=lambda i: abs(anchors[i] - cy))
        return best if abs(anchors[best] - cy) <= row_tol else None

    cells: List[Tuple[int, List[Any], str, int]] = []
    runway_thresh = cols.get("rank_change", cols["rank"]) + spacing * 0.4

    for sh in region:
        cy_row = row_of(sh)
        if cy_row is None:
            continue
        slot = _is_slot(sh)
        # Runway value box: a money slot sitting to the right of the rank columns.
        if slot and _cx(sh) > runway_thresh:
            cells.append((sh.shape_id, ["para", 0], "runway", cy_row))
            continue
        metric = min(_METRIC_COLS, key=lambda m: abs(cols.get(m, 1e18) - _cx(sh)))
        if abs(cols.get(metric, 1e18) - _cx(sh)) > col_tol:
            continue
        # Value columns must be real placeholder slots; name/rank_change are static text.
        if metric in ("gwp", "var", "sow", "rank") and not slot:
            continue
        if metric in ("name", "rank_change") and slot:
            continue
        cells.append((sh.shape_id, ["para", 0], metric, cy_row))

    return Grid(row_count=len(anchors), cells=tuple(cells),
                subtitle_id=_subtitle_id(slide, header_y))


def _role(slide_idx: int, row: int, metric: str) -> str:
    return f"grid:{slide_idx}:{row}:{metric}"


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Re-bind breakdown-grid cells to positional per-row roles (idempotent).

    Value slots already in ``bindings`` are remapped in place; the static product-name
    and rank-change boxes are added as new text bindings so they fill too.
    """
    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []

    def bind(slide_idx: int, shape_id: int, where: List[Any], role: str) -> None:
        """Point ``slide/shape/where`` at ``role`` — remapping an existing binding or
        adding one, keeping the template's own text as the token."""
        existing = by_key.get(Slot(slide_idx, shape_id, where, "", "text", "").key)
        if existing is not None:
            existing.role, existing.placeholder = role, False
            return
        extra.append(R.Binding(
            slot=Slot(slide_idx, shape_id, where, _token_at(template, slide_idx, shape_id, where),
                      "text", ""),
            role=role, placeholder=False))

    for slide in template.slides:
        grid = _detect(slide)
        if grid is None:
            continue
        for shape_id, where, metric, row in grid.cells:
            bind(slide.index, shape_id, where, _role(slide.index, row, metric))
        if grid.subtitle_id is not None:
            bind(slide.index, grid.subtitle_id, ["para", 0], f"grid:{slide.index}:subtitle")
        logger.info("grids: slide %d breakdown grid -> %d cells, %d rows",
                    slide.index, len(grid.cells), grid.row_count)
    return bindings + extra


def _token_at(template: Template, slide_idx: int, shape_id: int, where: List[Any]) -> str:
    """The template's own text at a cell/paragraph — the placeholder token to render into."""
    sh = template.shape(slide_idx, shape_id)
    if sh is None:
        return ""
    if where and where[0] == "cell" and sh.table:
        r, c = int(where[1]), int(where[2])
        if r < len(sh.table) and c < len(sh.table[r]):
            return sh.table[r][c]
        return ""
    return sh.paragraphs[0] if sh.paragraphs else ""


# ── value resolution ─────────────────────────────────────────────────────────


def _carrier_countries(result) -> List[str]:
    """The carrier's countries, biggest premium first — same order as the country labels."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    facts = compute_breakdown(
        PrimitiveArgs(flow=result.flow, metric="premium", group_by=(_COUNTRY_COL,),
                      filters=result.resolved_filters),
        engine=result.engine,
    )
    facts = sorted(facts, key=lambda f: f.value or 0.0, reverse=True)
    return [str(f.dims.get(_COUNTRY_COL)) for f in facts]


def _fmt_rank_change(rc: Optional[int]) -> str:
    if rc is None:
        return ""
    if rc > 0:
        return f"+{rc}↑"
    if rc < 0:
        return f"{rc}↓"
    return "0►"


def grid_values(template: Template, result) -> Dict[str, Any]:
    """Per-slide, per-row breakdown values keyed identically to ``augment``.

    Each breakdown slide is scoped to the k-th carrier country and to the deck's REPORTING
    YEAR — the same year every other page reports on. Without that year ``product_breakdown_rows``
    sums every year in the book into one "GWP" (so the column disagreed with the GWP-performance
    page), and has no prior year to compare against (so Var % and Rank change stayed empty).
    Rows beyond the data are blanked so no stale ``$xx.xm`` placeholder survives.
    """
    from studio.compute import product_breakdown_rows
    from studio.template_fill.bindings import reporting_filters

    subject = result.subject
    if not subject:
        return {}
    countries = _carrier_countries(result)
    reporting = reporting_filters(result)
    out: Dict[str, Any] = {}
    breakdown_idx = 0
    for slide in template.slides:
        grid = _detect(slide)
        if grid is None:
            continue
        n = grid.row_count
        country = countries[breakdown_idx] if breakdown_idx < len(countries) else None
        breakdown_idx += 1
        filters = dict(reporting)
        if country is not None:
            filters[_COUNTRY_COL] = country

        # Re-resolve the hard-coded "(n)" subtitle to THIS slide's country.
        if grid.subtitle_id is not None and country is not None:
            sh = template.shape(slide.index, grid.subtitle_id)
            token = sh.paragraphs[0] if (sh and sh.paragraphs) else ""
            text = _COUNTRY_TOKEN.sub(country, token)
            text = _CARRIER_TOKEN.sub(str(subject), text)
            out[f"grid:{slide.index}:subtitle"] = text
        try:
            rows = product_breakdown_rows(result.flow, filters, result.engine, subject, top=n)
        except Exception as exc:  # noqa: BLE001 — a failing slide must not break the doc
            logger.warning("grids: product rows failed on slide %d: %s", slide.index, exc)
            rows = []
        for i in range(n):
            r = rows[i] if i < len(rows) else None
            for metric in _ROW_METRICS:
                value = None if r is None else r.get(metric)
                out[_role(slide.index, i, metric)] = "" if value is None else value
            out[_role(slide.index, i, "rank_change")] = _fmt_rank_change(
                None if r is None else r.get("rank_change"))
        _trim_runway_chart(out, slide.index, grid, len(rows))
    return out


def _trim_runway_chart(out: Dict[str, Any], slide_idx: int, grid: Grid, live: int) -> None:
    """Cut the runway bars belonging to rows this country has no product for.

    The runway is drawn as ONE picture of bars, laid out top-to-bottom against the grid's
    rows. Blanking a row's value label leaves its bar behind — a bar under no product,
    which reads as a runway the carrier does not have. Cropping the picture to the live
    rows takes the bars off with the rows; with no rows at all the whole picture goes.
    """
    if grid.runway_chart_id is None or live >= grid.row_count:
        return
    crops = out.setdefault("picture_crops", {})
    crops[f"{slide_idx}:{grid.runway_chart_id}"] = {"bottom": 1.0 - live / grid.row_count}
