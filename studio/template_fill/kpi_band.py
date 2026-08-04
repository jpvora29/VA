"""The headline KPI band — the small "Marsh GWP · Carrier GWP · SoW% · Rank" table.

Several pages carry the same three-row band across the top: a header row naming each
measure, a value row of placeholders, and a ``PY (…)`` row of prior-year deltas. It is the
deck's summary line, so it must fill wherever the author puts it.

Recognised by its HEADER TEXT, not by a slide index or a shape id — the curated binding
maps pin cells by shape id, so moving the band onto another page (or adding a "Peer GWP"
column to it) silently unbinds every cell and the page ships ``xx.xB``. Matching the words
the author wrote instead means the band follows its page.

Binds to the scalar roles :func:`studio.template_fill.bindings.resolve_roles` already
produces, so there is no value provider here: recognising the cells is the whole job.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from logger import get_logger
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Slide, Template
from studio.template_fill.slots import Slot

logger = get_logger(__name__)

# Header phrase → (the value role, the prior-year delta role). Ordered: "peer gwp" is
# checked before "carrier gwp"/"gwp" so the confidential benchmark column is never read as
# the carrier's own premium (the same precedence :mod:`studio.template_fill.roles` applies).
_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("peer gwp", R.ROLE_PEER_GWP, R.ROLE_PEER_GWP_YOY),
    ("marsh gwp", R.ROLE_MARSH_GWP, R.ROLE_MARSH_GWP_YOY),
    ("carrier gwp", R.ROLE_CARRIER_GWP, R.ROLE_CARRIER_GWP_YOY),
    ("sow", R.ROLE_SOW_PCT, R.ROLE_SOW_YOY),
    ("rank", R.ROLE_RANK, R.ROLE_RANK_YOY),
)
# What makes it the BAND: it states the whole Marsh book beside the carrier's own. Without
# this, the per-product breakdown grid (… SoW · Rank · Peer GWP …) matches too, and its
# per-row cells would all be rebound to one carrier total.
_REQUIRED = {R.ROLE_MARSH_GWP, R.ROLE_CARRIER_GWP}
# Enough columns to be the band rather than an unrelated table that happens to say "rank".
_MIN_COLUMNS = 3
# The delta row states the prior-year comparison, e.g. "PY (-x.x%▼)".
_PRIOR_ROW = re.compile(r"^\s*py\b", re.I)


def _norm(text: str) -> str:
    """Header text with the year and punctuation stripped: "SoW% 2025" → "sow"."""
    text = re.sub(r"\b(19|20)\d{2}\b", " ", str(text or ""))
    return " ".join(re.sub(r"[^a-z ]+", " ", text.lower()).split())


def _role_pair(header: str) -> Optional[Tuple[str, str]]:
    text = _norm(header)
    for phrase, value_role, delta_role in _COLUMNS:
        if phrase in text:
            return value_role, delta_role
    return None


def _columns(header: List[str]) -> Dict[int, Tuple[str, str]]:
    """``{column index: (value role, delta role)}`` from the band's header row."""
    found: Dict[int, Tuple[str, str]] = {}
    claimed = set()
    for c, cell in enumerate(header):
        pair = _role_pair(cell)
        if pair and pair[0] not in claimed:
            found[c] = pair
            claimed.add(pair[0])
    return found


def detect(slide: Slide) -> List[Tuple[int, List[int], str]]:
    """The band's cells on ``slide`` as ``(shape_id, ['cell', r, c], role)``, or ``[]``.

    Every row under the header is bound: the one that reads "PY (…)" takes the delta roles,
    any other takes the value roles — so a band authored with the rows the other way up, or
    with only one of them, still fills.
    """
    for sh in slide.shapes:
        table = sh.table if sh.kind == "table" else None
        if not table or len(table) < 2:
            continue
        cols = _columns(table[0])
        if len(cols) < _MIN_COLUMNS or not _REQUIRED <= {value for value, _ in cols.values()}:
            continue
        cells = []
        for r, row in enumerate(table[1:], start=1):
            prior = bool(row) and any(_PRIOR_ROW.match(str(cell or "")) for cell in row)
            for c, (value_role, delta_role) in cols.items():
                if c < len(row):
                    cells.append((sh.shape_id, ["cell", r, c], delta_role if prior else value_role))
        return cells
    return []


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Bind every KPI-band cell in ``template`` to its role (idempotent).

    A cell already in ``bindings`` (from a curated map) is re-pointed in place; one the map
    never knew about is added, keeping the template's own text as the token so the value is
    rendered in the shape the author authored.
    """
    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    for slide in template.slides:
        cells = detect(slide)
        for shape_id, where, role in cells:
            existing = by_key.get(Slot(slide.index, shape_id, where, "", "text", "").key)
            if existing is not None:
                existing.role, existing.placeholder = role, False
                continue
            extra.append(R.Binding(
                slot=Slot(slide.index, shape_id, where,
                          _cell_text(template, slide.index, shape_id, where), "text", ""),
                role=role, placeholder=False))
        if cells:
            logger.info("kpi_band: slide %d KPI band -> %d cell(s)", slide.index, len(cells))
    return bindings + extra


def _cell_text(template: Template, slide_idx: int, shape_id: int, where: List) -> str:
    """The template's own text in a cell — the placeholder token to render into."""
    sh: Optional[Shape] = template.shape(slide_idx, shape_id)
    if sh is None or not sh.table:
        return ""
    r, c = int(where[1]), int(where[2])
    return sh.table[r][c] if r < len(sh.table) and c < len(sh.table[r]) else ""
