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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    """Every fillable cell: the body, both Total axes, the corner, and the axis HEADERS.

    The headers are fillable because the axes belong to the CARRIER, not to the template —
    a deck for a carrier surveyed on four practices must say those four, not the seven the
    template was drawn with (see :func:`assign_axis`).
    """
    rows = [r for r, _ in page.rows] + ([page.total_row] if page.total_row is not None else [])
    cols = [c for c, _ in page.cols] + ([page.total_col] if page.total_col is not None else [])
    headers = [(r, 0) for r, _ in page.rows] + [(0, c) for c, _ in page.cols]
    return [(r, c) for r in rows for c in cols] + headers


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


# ── the carrier's own axes ───────────────────────────────────────────────────


def assign_axis(authored: Sequence[str], available: Sequence[str]) -> List[Optional[str]]:
    """Which book label each authored slot shows — ``None`` for a slot to blank.

    The page's axes are the SUBJECT's: the sections and practices this carrier is actually
    surveyed on, in this country. The template supplies the slots (and its own order, which
    an author chose for a reason); the book supplies what goes in them.

    The labels the template already names come first, IN ITS ORDER — a carrier surveyed on
    the familiar seven practices gets the familiar page, unmoved — then whatever the book
    has beyond them. They are laid into the slots from the start, so the filled part of the
    table is contiguous: a hole in the middle of a row of scores reads as a rendering fault,
    where a shorter table just reads as a shorter table.

    Trailing slots the book cannot fill come back as ``None``. The caller removes those
    rows and columns outright, rather than shipping an authored practice this carrier does
    not write over a column of ``x.x`` — which is what made the page read as broken.
    """
    known = {facts.norm_label(label): label for label in available if str(label).strip()}
    ordered = [known.pop(facts.norm_label(label))
               for label in authored if facts.norm_label(label) in known]
    ordered += sorted(known.values())
    return [ordered[i] if i < len(ordered) else None for i in range(len(authored))]


# ── values ───────────────────────────────────────────────────────────────────

def _country_of(result) -> Optional[str]:
    """The single country this sub-deck is for — the survey page is always per-country.

    The run's OWN selection, read the same way every other page reads it
    (:func:`studio.template_fill.survey.scope.selected_countries`), so the survey slide
    reports the market the author picked and not a wider cut of the book.
    """
    from studio.template_fill.survey import scope as scope_mod

    named = scope_mod.selected_countries(result)
    return named[0] if len(named) == 1 else None


@dataclass(frozen=True)
class Axes:
    """What each authored slot on the page reports — the CARRIER's sections and practices.

    ``sections`` / ``practices`` are indexed by slot, ``None`` where the book has nothing to
    put in that slot and it is therefore blanked.
    """

    sections: Tuple[Optional[str], ...] = ()
    practices: Tuple[Optional[str], ...] = ()

    def section(self, row: int, page: "SurveyPage") -> Optional[str]:
        return _at(self.sections, [r for r, _ in page.rows], row)

    def practice(self, col: int, page: "SurveyPage") -> Optional[str]:
        return _at(self.practices, [c for c, _ in page.cols], col)


def _at(labels: Sequence[Optional[str]], slots: Sequence[int], index: int) -> Optional[str]:
    return labels[slots.index(index)] if index in slots else None


def axes_for(page: SurveyPage, book) -> Axes:
    """The page's axes, taken from what the subject is actually surveyed on.

    ``book`` is anything carrying the vocabulary — a :class:`facts.SurveyAxes` before the
    numbers are loaded, or the :class:`facts.ScoreGrid` afterwards.
    """
    return Axes(
        sections=tuple(assign_axis([label for _, label in page.rows], book.sections)),
        practices=tuple(assign_axis([label for _, label in page.cols], book.practices)),
    )


def shown(labels: Sequence[Optional[str]]) -> Tuple[str, ...]:
    """The book labels an axis actually shows — the slots the carrier's book could fill."""
    return tuple(label for label in labels if label)


def _reading(grid: facts.ScoreGrid, page: SurveyPage, axes: Axes,
             row: int, col: int) -> Tuple[Optional[float], Optional[float]]:
    """``(score, Δ vs prior year)`` for one cell, whichever axis(es) it totals."""
    is_total_row = row == page.total_row
    is_total_col = col == page.total_col
    if is_total_row and is_total_col:
        return grid.overall, grid.overall_delta()
    section, practice = axes.section(row, page), axes.practice(col, page)
    if is_total_row:
        return ((grid.practice_total(practice), grid.practice_total_delta(practice))
                if practice else (None, None))
    if is_total_col:
        return ((grid.section_total(section), grid.section_total_delta(section))
                if section else (None, None))
    if section is None or practice is None:
        return None, None
    return grid.score(section, practice), grid.delta(section, practice)


def _table_payload(page: SurveyPage, axes: Axes,
                   grid: facts.ScoreGrid) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """``({role: score-or-label}, [{r, c, hex}])`` — the axes, the numbers, the colours.

    Every cell of the table is written, including the axis headers: the page reports the
    sections and practices THIS carrier is surveyed on, so a slot the book cannot fill is
    BLANKED. Leaving it would ship an authored practice the carrier does not write, over a
    row of ``x.x`` — which is what made a partly-surveyed carrier's page read as broken.

    A cell only carries a fill when its move against the previous survey puts it in a band
    (:mod:`studio.template_fill.survey.bands`). No band means no claim about direction, and
    the cell keeps the template's own styling — emitting ``hex: None`` instead told the fill
    engine to CLEAR it, which is how a book with nothing to compare against ended up
    stripping the whole table's background.
    """
    texts: Dict[str, Any] = {}
    fills: List[Dict[str, Any]] = []
    for row, col in _cells(page):
        header = _header_label(page, axes, row, col)
        if header is not None:
            texts[_role(page.slide_idx, row, col)] = header
            continue
        score, delta = _reading(grid, page, axes, row, col)
        texts[_role(page.slide_idx, row, col)] = "" if score is None else float(score)
        band = bands.band_for(delta) if score is not None else None
        if band:
            fills.append({"r": row, "c": col, "hex": band})
    return texts, fills


def _trim(page: SurveyPage, axes: Axes) -> Dict[str, List[int]]:
    """The rows and columns to take off the table — the slots the book could not fill."""
    return {
        "rows": [r for (r, _), label in zip(page.rows, axes.sections) if label is None],
        "cols": [c for (c, _), label in zip(page.cols, axes.practices) if label is None],
    }


def _header_label(page: SurveyPage, axes: Axes, row: int, col: int) -> Optional[str]:
    """The text for an axis-header cell (``""`` to blank it), or ``None`` if not a header."""
    if col == 0 and row in [r for r, _ in page.rows]:
        return axes.section(row, page) or ""
    if row == 0 and col in [c for c, _ in page.cols]:
        return axes.practice(col, page) or ""
    return None


def _report_axes(page: SurveyPage, axes: Axes, book: facts.SurveyAxes) -> None:
    """Say what the page ended up reporting on, and what it had to drop.

    A page filled from a carrier's own book can differ from the authored one in both
    directions — practices the template never had, authored ones this carrier is not
    surveyed on — and on the slide both look like "it didn't work". The log is what
    distinguishes a vocabulary problem from an absent survey.

    Reads the carrier's WHOLE vocabulary (:func:`facts.load_axes`), not the grid's: the grid
    only knows the axes the page had room for, so it could never report the ones it left out.
    """
    for axis, slots, authored, theirs in (
        ("section", axes.sections, [label for _, label in page.rows], book.sections),
        ("practice", axes.practices, [label for _, label in page.cols], book.practices),
    ):
        shown = [s for s in slots if s]
        dropped = [a for a in authored
                   if facts.norm_label(a) not in {facts.norm_label(s) for s in shown}]
        spare = len(theirs) - len(shown)
        logger.info("survey_page: %d %s slot(s) filled from the book %s%s%s",
                    len(shown), axis, list(theirs),
                    f"; blanked authored {dropped}" if dropped else "",
                    f"; {spare} more in the book than the page has room for" if spare > 0 else "")


def _ribbon_png(page: SurveyPage, result, country: str,
                sections: Sequence[str]) -> Optional[bytes]:
    """The ribbon image for this page, or ``None`` — a dead renderer costs the CHART only.

    The authored picture then stays, which is a visibly stale chart rather than a broken
    deck; the table above it is filled either way. ``sections`` is the table's OWN row
    order after :func:`axes_for`, so the chart reads down the page beside it.
    """
    if page.ribbon_id is None or not ribbon_mod.available():
        return None
    spec = facts.load_ribbon(result, country, tuple(sections))
    if spec is None or not spec.columns:
        return None
    try:
        return ribbon_mod.render_ribbon_png(spec)
    except Exception as exc:  # noqa: BLE001 — no renderer must not cost us the table
        logger.warning("survey_page: ribbon render failed (%s); keeping the authored picture", exc)
        return None


def values(template: Template, result) -> Dict[str, Any]:
    """``{survey-role: score}`` plus the ``cell_fills`` and ``pictures`` payloads.

    Two passes over the book, because the page's axes decide what its totals mean. First
    :func:`facts.load_axes` says what the carrier is surveyed on; the template's slots are
    laid over that (:func:`axes_for`); only then are the numbers loaded, RESTRICTED to the
    axes that survived. That is what makes the Total column the average of the row printed
    beside it, on a page whose surplus rows and columns have been trimmed away.

    Empty when the template has no survey page, when the sub-deck is not scoped to exactly
    one country, or when that country has no survey book for this run's carrier and year —
    in every case the slide is simply not generated (see
    :func:`studio.template_fill.assemble.plan_subdecks`).
    """
    found = pages(template)
    if not found:
        return {}
    country = _country_of(result)
    if country is None:
        return {}
    book = facts.load_axes(result, country)
    if book is None:
        return {}

    out: Dict[str, Any] = {}
    cell_fills: Dict[str, Any] = {}
    pictures: Dict[str, Any] = {}
    trims: Dict[str, Any] = {}
    year = book.year
    for page in found:
        axes = axes_for(page, book)
        grid = facts.load_grid(result, country, sections=shown(axes.sections),
                               practices=shown(axes.practices))
        if grid is None:
            continue
        year = grid.year
        texts, fills = _table_payload(page, axes, grid)
        _report_axes(page, axes, book)
        out.update(texts)
        if fills:
            cell_fills[f"{page.slide_idx}:{page.table_id}"] = fills
        trim = _trim(page, axes)
        if trim["rows"] or trim["cols"]:
            trims[f"{page.slide_idx}:{page.table_id}"] = trim
        # The chart's columns are the table's OWN rows, so the two read together.
        png = _ribbon_png(page, result, country, shown(axes.sections))
        if png:
            pictures[f"{page.slide_idx}:{page.ribbon_id}"] = png
    if cell_fills:
        out["cell_fills"] = cell_fills
    if pictures:
        out["pictures"] = pictures
    if trims:
        out["drop_table_lines"] = trims
    logger.info("survey_page: %s %d — %d cell(s), %d chart(s)",
                country, year, len(out), len(pictures))
    return out
