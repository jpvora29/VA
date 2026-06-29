"""Per-product breakdown-grid detection and binding — the 'Carrier breakdown' table.

The generic slot/role path fills one scalar per slot, so a per-product table (one row
per product line: GWP · Var % · SoW · Rank · Rank change · Runway to Top 5) ends up
with the SAME carrier total repeated down every row. This module recognises that grid
by geometry and binds each *cell* to a positional, per-slide role
``grid:<slide_idx>:<row>:<metric>`` so each row carries its own product's numbers.

Detection is generic (header text + column geometry), so it fires only on a slide that
actually has the GWP/Var/SoW/Rank header set — never on unrelated slides. Each breakdown
slide is scoped to one country (``Carrier breakdown – Country (1)``/(2)…), matched
positionally to the carrier's countries so the table agrees with the slide's own label.
"""
from __future__ import annotations

import re
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
    "rank": "rank", "rank change": "rank_change",
}
_METRIC_COLS = ("name", "gwp", "var", "sow", "rank", "rank_change")
_REQUIRED = {"name", "gwp", "var", "sow", "rank"}

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


def _detect(slide: Slide) -> Optional[Dict[str, Any]]:
    """Map the breakdown grid on ``slide`` → cell assignments, or None if not a grid.

    Returns ``{row_count, cells}`` where ``cells`` is a list of
    ``(shape_id, where, metric, row)`` plus synthesised text cells for the static
    product-name and rank-change boxes (which are not ``x``-placeholder slots).
    """
    cols, runway_x, header_y = _headers(slide)
    if not _REQUIRED <= set(cols):
        return None

    # The country subtitle sits above the header and carries a hard-coded "(n)".
    subtitle_id: Optional[int] = None
    for sh in slide.shapes:
        if (sh.kind == "text" and _cy(sh) < header_y and _PAREN_NUM.search(sh.text)
                and re.search(r"country|region|breakdown", sh.text, re.I)):
            subtitle_id = sh.shape_id
            break

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

    return {"row_count": len(anchors), "cells": cells, "subtitle_id": subtitle_id}


def _role(slide_idx: int, row: int, metric: str) -> str:
    return f"grid:{slide_idx}:{row}:{metric}"


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Re-bind breakdown-grid cells to positional per-row roles (idempotent).

    Value slots already in ``bindings`` are remapped in place; the static product-name
    and rank-change boxes are added as new text bindings so they fill too.
    """
    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    for slide in template.slides:
        grid = _detect(slide)
        if not grid:
            continue
        for shape_id, where, metric, row in grid["cells"]:
            slot = Slot(slide.index, shape_id, where, "", "text", "")
            existing = by_key.get(slot.key)
            role = _role(slide.index, row, metric)
            if existing is not None:
                existing.role = role
                existing.placeholder = False
            else:
                sh = template.shape(slide.index, shape_id)
                token = sh.paragraphs[0] if (sh and sh.paragraphs) else ""
                extra.append(R.Binding(
                    slot=Slot(slide.index, shape_id, where, token, "text", ""),
                    role=role, placeholder=False))
        sub_id = grid.get("subtitle_id")
        if sub_id is not None:
            slot = Slot(slide.index, sub_id, ["para", 0], "", "text", "")
            sh = template.shape(slide.index, sub_id)
            token = sh.paragraphs[0] if (sh and sh.paragraphs) else ""
            role = f"grid:{slide.index}:subtitle"
            existing = by_key.get(slot.key)
            if existing is not None:
                existing.role, existing.placeholder = role, False
            else:
                extra.append(R.Binding(
                    slot=Slot(slide.index, sub_id, ["para", 0], token, "text", ""),
                    role=role, placeholder=False))
        logger.info("grids: slide %d breakdown grid -> %d cells, %d rows",
                    slide.index, len(grid["cells"]), grid["row_count"])
    return bindings + extra


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

    Each breakdown slide is scoped to the k-th carrier country; rows beyond the data
    are blanked so no stale ``$xx.xm`` placeholder survives.
    """
    from studio.compute import product_breakdown_rows

    subject = result.subject
    if not subject:
        return {}
    countries = _carrier_countries(result)
    out: Dict[str, Any] = {}
    breakdown_idx = 0
    for slide in template.slides:
        grid = _detect(slide)
        if not grid:
            continue
        n = grid["row_count"]
        country = countries[breakdown_idx] if breakdown_idx < len(countries) else None
        breakdown_idx += 1
        filters = dict(result.resolved_filters)
        if country is not None:
            filters[_COUNTRY_COL] = country

        # Re-resolve the hard-coded "(n)" subtitle to THIS slide's country.
        sub_id = grid.get("subtitle_id")
        if sub_id is not None and country is not None:
            sh = template.shape(slide.index, sub_id)
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
            def val(key, default=""):
                return default if (r is None or r.get(key) is None) else r[key]
            out[_role(slide.index, i, "name")] = val("name")
            out[_role(slide.index, i, "gwp")] = val("gwp")
            out[_role(slide.index, i, "var")] = val("var")
            out[_role(slide.index, i, "sow")] = val("sow")
            out[_role(slide.index, i, "rank")] = val("rank")
            out[_role(slide.index, i, "runway")] = val("runway")
            out[_role(slide.index, i, "rank_change")] = _fmt_rank_change(
                None if r is None else r.get("rank_change"))
    return out
