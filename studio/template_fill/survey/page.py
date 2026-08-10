"""The Carrier Survey page — detection, slot binding, and the fill payload.

The author's page has two things the generic slot/role path cannot fill:

  * the **score table** — an 8x9 grid of ``x.x`` placeholders whose ROW is a survey
    section and whose COLUMN is a practice, and whose BACKGROUND encodes the score's move
    against last year (the legend the author pasted below it);
  * the **ribbon chart** — a pasted think-cell render, so there is no chart to refill; we
    draw our own PNG and swap the picture's image.

Mirrors :mod:`studio.template_fill.gwp_page`: ``augment`` re-binds the slots, ``values``
computes the texts (plus the ``cell_fills`` and ``pictures`` payloads the fill engine
consumes), and detection is header/geometry driven — never a slide index — so the page
keeps filling if it is moved, restyled or duplicated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from logger import get_logger
from studio.template_fill import roles as R
from studio.template_fill.analyze import Slide, Template
from studio.template_fill.sections import Section, section_of
from studio.template_fill.slots import Slot, classify
from studio.template_fill.survey import bands, facts
from studio.template_fill.survey import ribbon as ribbon_mod

logger = get_logger(__name__)

ROLE_PREFIX = "survey:"

_TOTAL = "total"
_SECTION_HEADER = "section"

# The same normaliser the score lookups use, so a header is recognised on exactly the
# terms a cell is matched on — one definition, in the module that owns the matching.
_norm = facts.norm_label


# ── page anatomy ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SurveyPage:
    """One Carrier Survey page: its score table's axes and its ribbon picture."""

    slide_idx: int
    table_id: int
    rows: Tuple[Tuple[int, str], ...] = ()      # (row index, section label) — no Total
    cols: Tuple[Tuple[int, str], ...] = ()      # (col index, practice label) — no Total
    total_row: Optional[int] = None
    total_col: Optional[int] = None
    ribbon_id: Optional[int] = None


def _score_table(slide: Slide) -> Optional[Tuple[int, List[List[str]]]]:
    """The score table — the one whose top-left header names the section axis."""
    for sh in slide.shapes:
        table = sh.table if sh.kind == "table" else None
        if table and len(table) > 1 and table[0] and _SECTION_HEADER in _norm(table[0][0]):
            return sh.shape_id, table
    return None


def _axis(labels: List[str]) -> Tuple[Tuple[Tuple[int, str], ...], Optional[int]]:
    """Split an axis's labels into ``((index, label) …, the Total index)``.

    Index 0 is the axis's own header cell, never a data label.
    """
    entries: List[Tuple[int, str]] = []
    total: Optional[int] = None
    for i, raw in enumerate(labels):
        if i == 0:
            continue
        label = " ".join((raw or "").split())
        if not label:
            continue
        if _norm(label) == _TOTAL:
            total = i
        else:
            entries.append((i, label))
    return tuple(entries), total


def _ribbon_id(slide: Slide) -> Optional[int]:
    """The ribbon picture — the TALLEST picture on the page.

    The slide carries two: the banding legend (a thin colour strip) and the chart. Height
    separates them by an order of magnitude, so no caption matching is needed.
    """
    pictures = [sh for sh in slide.shapes if sh.kind == "picture"]
    return max(pictures, key=lambda sh: sh.h).shape_id if pictures else None


def _page_of(slide: Slide) -> Optional[SurveyPage]:
    found = _score_table(slide)
    if found is None:
        return None
    table_id, table = found
    rows, total_row = _axis([row[0] if row else "" for row in table])
    cols, total_col = _axis(list(table[0]))
    if not rows or not cols:
        return None
    return SurveyPage(slide_idx=slide.index, table_id=table_id, rows=rows, cols=cols,
                      total_row=total_row, total_col=total_col, ribbon_id=_ribbon_id(slide))


def pages(template: Template) -> List[SurveyPage]:
    """Every Carrier Survey page in ``template``, with its fillable parts located."""
    found = (_page_of(s) for s in template.slides if section_of(s) is Section.SURVEY)
    return [p for p in found if p is not None]


# ── binding ──────────────────────────────────────────────────────────────────


def _role(slide_idx: int, row: int, col: int) -> str:
    return f"{ROLE_PREFIX}{slide_idx}:{row}:{col}"


def _cells(page: SurveyPage) -> List[Tuple[int, int]]:
    """Every data cell on the page: the body, both Total axes, and the corner."""
    rows = [r for r, _ in page.rows] + ([page.total_row] if page.total_row is not None else [])
    cols = [c for c, _ in page.cols] + ([page.total_col] if page.total_col is not None else [])
    return [(r, c) for r in rows for c in cols]


def _token_at(template: Template, page: SurveyPage, row: int, col: int) -> str:
    sh = template.shape(page.slide_idx, page.table_id)
    if sh is None or not sh.table or row >= len(sh.table) or col >= len(sh.table[row]):
        return ""
    return sh.table[row][col]


def augment(template: Template, bindings: List[R.Binding]) -> List[R.Binding]:
    """Bind every Carrier Survey data cell to its ``survey:`` role (idempotent)."""
    by_key = {b.slot.key: b for b in bindings}
    extra: List[R.Binding] = []
    n = 0
    for page in pages(template):
        for row, col in _cells(page):
            where = ["cell", row, col]
            token = _token_at(template, page, row, col)
            role = _role(page.slide_idx, row, col)
            existing = by_key.get(Slot(page.slide_idx, page.table_id, where, "", "text", "").key)
            if existing is not None:
                existing.role, existing.placeholder = role, False
            else:
                extra.append(R.Binding(
                    slot=Slot(page.slide_idx, page.table_id, where, token,
                              classify(token) or "text", ""),
                    role=role, placeholder=False))
            n += 1
    if n:
        logger.info("survey_page: bound %d cell(s) (%d added)", n, len(extra))
    return bindings + extra


# ── values ───────────────────────────────────────────────────────────────────

_COUNTRY_FILTER = "Country"


def _country_of(result) -> Optional[str]:
    """The single country this sub-deck is for — the survey page is always per-country."""
    value = (getattr(result, "resolved_filters", None) or {}).get(_COUNTRY_FILTER)
    values = list(value) if isinstance(value, (list, tuple, set)) else ([value] if value else [])
    named = [str(v) for v in values if v not in (None, "", "all", "All")]
    return named[0] if len(named) == 1 else None


def _reading(grid: facts.ScoreGrid, page: SurveyPage,
             row: int, col: int) -> Tuple[Optional[float], Optional[float]]:
    """``(score, Δ vs prior year)`` for one cell, whichever axis(es) it totals."""
    sections = dict(page.rows)
    practices = dict(page.cols)
    is_total_row = row == page.total_row
    is_total_col = col == page.total_col
    if is_total_row and is_total_col:
        return grid.overall, grid.overall_delta()
    if is_total_row:
        practice = practices[col]
        return grid.practice_total(practice), grid.practice_total_delta(practice)
    if is_total_col:
        section = sections[row]
        return grid.section_total(section), grid.section_total_delta(section)
    section, practice = sections[row], practices[col]
    return grid.score(section, practice), grid.delta(section, practice)


def _table_payload(page: SurveyPage,
                   grid: facts.ScoreGrid) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """``({role: score}, [{r, c, hex}])`` — the numbers and the colours behind them.

    A cell with no score is left out entirely: it keeps the template's own ``x.x`` and
    takes no colour, which reads as "not surveyed" rather than as a real zero.
    """
    texts: Dict[str, Any] = {}
    fills: List[Dict[str, Any]] = []
    for row, col in _cells(page):
        score, delta = _reading(grid, page, row, col)
        if score is None:
            continue
        texts[_role(page.slide_idx, row, col)] = float(score)
        fills.append({"r": row, "c": col, "hex": bands.band_for(delta)})
    _report_unmatched(page, grid)
    return texts, fills


def _report_unmatched(page: SurveyPage, grid: facts.ScoreGrid) -> None:
    """Name any authored axis label the survey book has no value for.

    A page whose template says "FINPRO" against a book that says "Financial Lines" fills
    nothing on that column and looks, on the slide, exactly like a page with no data — the
    cells keep their ``x.x`` and take no band colour. The difference matters: one is a
    warehouse without the survey, the other is two vocabularies that need reconciling, and
    only a log that prints BOTH lists tells them apart.
    """
    known_sections = {facts.norm_label(s) for s in grid.sections}
    known_practices = {facts.norm_label(p) for p in grid.practices}
    for axis, authored, known, theirs in (
        ("row", [label for _, label in page.rows], known_sections, grid.sections),
        ("column", [label for _, label in page.cols], known_practices, grid.practices),
    ):
        missing = [label for label in authored if facts.norm_label(label) not in known]
        if missing:
            logger.warning(
                "survey_page: %d authored %s label(s) are not in the survey book — %s; "
                "the book has %s. Those cells keep the template's placeholder.",
                len(missing), axis, missing, list(theirs))


def _ribbon_png(page: SurveyPage, result, country: str) -> Optional[bytes]:
    """The ribbon image for this page, or ``None`` — a dead renderer costs the CHART only.

    The authored picture then stays, which is a visibly stale chart rather than a broken
    deck; the table above it is filled either way.
    """
    if page.ribbon_id is None or not ribbon_mod.available():
        return None
    spec = facts.load_ribbon(result, country, tuple(label for _, label in page.rows))
    if spec is None or not spec.columns:
        return None
    try:
        return ribbon_mod.render_ribbon_png(spec)
    except Exception as exc:  # noqa: BLE001 — no renderer must not cost us the table
        logger.warning("survey_page: ribbon render failed (%s); keeping the authored picture", exc)
        return None


def values(template: Template, result) -> Dict[str, Any]:
    """``{survey-role: score}`` plus the ``cell_fills`` and ``pictures`` payloads.

    Empty when the template has no survey page, when the sub-deck is not scoped to exactly
    one country, or when that country has no survey book — in every case the slide is
    simply not generated (see :func:`studio.template_fill.assemble.plan_subdecks`).
    """
    found = pages(template)
    if not found:
        return {}
    country = _country_of(result)
    if country is None:
        return {}
    grid = facts.load_grid(result, country)
    if grid is None:
        return {}

    out: Dict[str, Any] = {}
    cell_fills: Dict[str, Any] = {}
    pictures: Dict[str, Any] = {}
    for page in found:
        texts, fills = _table_payload(page, grid)
        out.update(texts)
        if fills:
            cell_fills[f"{page.slide_idx}:{page.table_id}"] = fills
        png = _ribbon_png(page, result, country)
        if png:
            pictures[f"{page.slide_idx}:{page.ribbon_id}"] = png
    if cell_fills:
        out["cell_fills"] = cell_fills
    if pictures:
        out["pictures"] = pictures
    logger.info("survey_page: %s %d — %d cell(s), %d chart(s)",
                country, grid.year, len(out), len(pictures))
    return out
