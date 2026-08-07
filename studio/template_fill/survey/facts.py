"""The deterministic survey queries behind the Carrier Survey page.

Everything the page shows comes from the ``survey`` flow (table ``Carriers``), never the
premium book — a survey score is not a premium figure, and the two use different
taxonomies (``SurveyPractice`` vs ``Product_Line``, ``Carrier`` vs ``Carrier_Group``).
For that reason the page is scoped by COUNTRY, CARRIER and YEAR only: honouring a
``Product_Line`` pin would blank most of a table whose columns ARE the practices.

Two products:

  * :class:`ScoreGrid` — the table. The subject's average score per section × practice at
    the latest surveyed year, the same grid a year earlier, and the row/column/corner
    totals. Totals are their OWN average over the raw rows, not a mean of the displayed
    cells, so a sparse row cannot skew them.
  * :func:`load_ribbon` — the chart. Per section, the subject and its peers ranked by
    average score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from logger import get_logger
from studio.template_fill.survey import ribbon as ribbon_mod

logger = get_logger(__name__)

SURVEY_FLOW = "survey"
SURVEY_TABLE = "Carriers"
CARRIER_COL = "Carrier"
COUNTRY_COL = "SurveyCountry"
PRACTICE_COL = "SurveyPractice"
YEAR_COL = "Survey_Year"
# ``flows.yaml`` names this column ``Sections`` in its column table but ``Section`` in the
# chart defaults, and the live warehouse has not been inspected — so resolve it against
# the real table rather than trusting either. Preference order, first match wins.
SECTION_CANDIDATES: Tuple[str, ...] = ("Sections", "Section")

# The stack the authored ribbon art fits. More rows than this and the score labels stop
# being legible at the picture's frame size.
MAX_RIBBON_ROWS = 9


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — a failing query degrades the page, never breaks it
        logger.warning("survey.facts: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def _breakdown(result, group_by: Tuple[str, ...], filters: Dict[str, Any]):
    """``compute_breakdown`` over the survey flow, returning ``[]`` on any failure."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    return _safe(
        compute_breakdown,
        PrimitiveArgs(flow=SURVEY_FLOW, metric="score", group_by=group_by, filters=filters),
        engine=result.engine,
    ) or []


def section_column(result) -> Optional[str]:
    """Which column actually holds the survey sections, or ``None`` if there is no book."""
    from core.analytics.sql import resolve_engine, table_columns

    columns = _safe(table_columns, _safe(resolve_engine, result.engine), SURVEY_TABLE) or frozenset()
    for candidate in SECTION_CANDIDATES:
        if candidate in columns:
            return candidate
    return None


def _base_filters(result, country: str) -> Dict[str, Any]:
    """Country + carrier — the ONLY premium-side scoping the survey page inherits."""
    return {COUNTRY_COL: str(country), CARRIER_COL: str(result.subject)}


def has_survey_data(result, country: str) -> bool:
    """Whether ``country`` has any survey rows for the subject — the slide's gate.

    Cut by ``YEAR_COL`` (via :func:`_reported_years`) rather than an empty ``group_by``:
    an aggregate with no ``GROUP BY`` always returns exactly one SQL row — NULL, not
    absent, when nothing matches — so an empty-tuple cut can never observe "no data".
    """
    if section_column(result) is None:
        return False
    year, _ = _reported_years(result, country)
    return year is not None


def _reported_years(result, country: str) -> Tuple[Optional[int], Optional[int]]:
    """``(latest surveyed year, the one before it)`` for this country and carrier."""
    facts = _breakdown(result, (YEAR_COL,), _base_filters(result, country))
    years = sorted({int(f.dims[YEAR_COL]) for f in facts if f.dims.get(YEAR_COL) is not None})
    if not years:
        return None, None
    latest = years[-1]
    return latest, (latest - 1 if (latest - 1) in years else None)


# ── the table ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoreGrid:
    """The Carrier Survey table's numbers for one country.

    ``cells`` / ``prior_cells`` are keyed ``(section, practice)``; the totals are keyed by
    the one dimension they collapse to. Every lookup returns ``None`` when the data has no
    such cut — the page then keeps the template's own placeholder rather than inventing a
    number.
    """

    year: int
    prior_year: Optional[int]
    cells: Dict[Tuple[str, str], float]
    prior_cells: Dict[Tuple[str, str], float]
    section_totals: Dict[str, float]
    prior_section_totals: Dict[str, float]
    practice_totals: Dict[str, float]
    prior_practice_totals: Dict[str, float]
    overall: Optional[float] = None
    prior_overall: Optional[float] = None

    def score(self, section: str, practice: str) -> Optional[float]:
        return self.cells.get((section, practice))

    def delta(self, section: str, practice: str) -> Optional[float]:
        return _diff(self.cells.get((section, practice)),
                     self.prior_cells.get((section, practice)))

    def section_total(self, section: str) -> Optional[float]:
        return self.section_totals.get(section)

    def section_total_delta(self, section: str) -> Optional[float]:
        return _diff(self.section_totals.get(section), self.prior_section_totals.get(section))

    def practice_total(self, practice: str) -> Optional[float]:
        return self.practice_totals.get(practice)

    def practice_total_delta(self, practice: str) -> Optional[float]:
        return _diff(self.practice_totals.get(practice), self.prior_practice_totals.get(practice))

    def overall_delta(self) -> Optional[float]:
        return _diff(self.overall, self.prior_overall)


def _diff(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    """The year-on-year change, or ``None`` when either side is missing.

    ``None`` is NOT zero: a cell with no comparable prior year makes no claim about its
    direction, so it prints its number and takes no band colour.
    """
    return None if (current is None or prior is None) else float(current) - float(prior)


def _by_pair(facts, first: str, second: str) -> Dict[Tuple[str, str], float]:
    return {(str(f.dims[first]), str(f.dims[second])): float(f.value)
            for f in facts if f.dims.get(first) is not None and f.dims.get(second) is not None}


def _by_one(facts, column: str) -> Dict[str, float]:
    return {str(f.dims[column]): float(f.value) for f in facts if f.dims.get(column) is not None}


def _one(facts) -> Optional[float]:
    return float(facts[0].value) if facts else None


def load_grid(result, country: str) -> Optional[ScoreGrid]:
    """The table's numbers for ``country``, or ``None`` when it has no survey book.

    Four cuts per year — the body, the two total axes and the corner — because a Total is
    an average over the ROWS in that cut, which no arithmetic on the body can reproduce
    once any cell is missing.
    """
    section = section_column(result)
    if section is None:
        return None
    year, prior_year = _reported_years(result, country)
    if year is None:
        return None

    def cuts(for_year: int):
        filters = {**_base_filters(result, country), YEAR_COL: int(for_year)}
        return (
            _by_pair(_breakdown(result, (section, PRACTICE_COL), filters), section, PRACTICE_COL),
            _by_one(_breakdown(result, (section,), filters), section),
            _by_one(_breakdown(result, (PRACTICE_COL,), filters), PRACTICE_COL),
            _one(_breakdown(result, (), filters)),
        )

    cells, section_totals, practice_totals, overall = cuts(year)
    if not cells:
        return None
    if prior_year is None:
        prior: Tuple[Dict, Dict, Dict, Optional[float]] = ({}, {}, {}, None)
    else:
        prior = cuts(prior_year)

    return ScoreGrid(
        year=year, prior_year=prior_year,
        cells=cells, prior_cells=prior[0],
        section_totals=section_totals, prior_section_totals=prior[1],
        practice_totals=practice_totals, prior_practice_totals=prior[2],
        overall=overall, prior_overall=prior[3],
    )


# ── the ribbon ───────────────────────────────────────────────────────────────


def _peer_carriers(result, country: str) -> Tuple[str, ...]:
    """The carriers the subject is ranked against — the Setup peer selection.

    Order of authority: the custom peers pinned in Setup, else the subject's group from
    the survey flow's own Peers table. An empty result is not an error — the ribbon then
    shows the subject alone, which is honest.
    """
    pinned = tuple(str(p) for p in (result.peers or ()) if str(p).strip())
    if pinned:
        return pinned
    from studio.data import peer_members

    return tuple(_safe(peer_members, SURVEY_FLOW, str(result.subject), country=str(country)) or ())


def _capped(boxes: Sequence[ribbon_mod.RibbonBox]) -> Tuple[ribbon_mod.RibbonBox, ...]:
    """The top :data:`MAX_RIBBON_ROWS` boxes, with the subject kept whatever its rank.

    The authored art fits nine rows. Dropping the subject to fit would defeat the chart,
    so when the cap would cut it the lowest-scoring PEER goes instead.
    """
    if len(boxes) <= MAX_RIBBON_ROWS:
        return tuple(boxes)
    kept = list(boxes[:MAX_RIBBON_ROWS])
    if not any(b.highlight for b in kept):
        subject = next((b for b in boxes if b.highlight), None)
        if subject is not None:
            kept[-1] = subject
            kept.sort(key=lambda b: -b.score)
    return tuple(kept)


def load_ribbon(result, country: str, sections: Sequence[str]) -> Optional[ribbon_mod.RibbonSpec]:
    """The ranking chart's spec: one column per section, in the order ``sections`` gives.

    ``sections`` is the TEMPLATE's authored row order (minus its Total row), so the chart
    reads down the page in the same order as the table above it.
    """
    section = section_column(result)
    if section is None:
        return None
    year, _ = _reported_years(result, country)
    if year is None:
        return None
    subject = str(result.subject)
    wanted = {subject, *(_peer_carriers(result, country))}

    columns = []
    for label in sections:
        filters = {COUNTRY_COL: str(country), YEAR_COL: int(year), section: str(label)}
        facts = _breakdown(result, (CARRIER_COL,), filters)
        scored = [(str(f.dims[CARRIER_COL]), float(f.value))
                  for f in facts if str(f.dims.get(CARRIER_COL)) in wanted]
        if not scored:
            continue
        scored.sort(key=lambda pair: -pair[1])
        boxes = _capped([ribbon_mod.RibbonBox(name, value, highlight=(name == subject))
                         for name, value in scored])
        columns.append(ribbon_mod.RibbonColumn(str(label), boxes))

    return ribbon_mod.RibbonSpec(tuple(columns)) if columns else None
