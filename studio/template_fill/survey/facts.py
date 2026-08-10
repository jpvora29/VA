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

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


# ── label matching ───────────────────────────────────────────────────────────
#
# The page's axes are the TEMPLATE's authored labels; the numbers are keyed by the
# WAREHOUSE's own values. The two are typed by different people years apart, so they agree
# on the term and disagree on the typography — "Claims – Claims Professionals" against
# "Claims - Claims Professionals", "FINPRO" against "FinPro", a trailing space out of a
# spreadsheet. Matching the raw strings left every such cell on its ``x.x``, which reads as
# "not surveyed" when the score is right there in the book.
#
# Typography only: case, whitespace, dash flavour, and "&" for "and". A label that means
# something else still does not match, and must not — a QBR cell showing the wrong
# practice's score is worse than one showing none.
# Written as escapes on purpose — the dash variants are indistinguishable in most editors.
_DASHES = re.compile("[‐-―−]")


def norm_label(text: Any) -> str:
    """A survey label reduced to what it SAYS, so typography cannot break a match."""
    flat = _DASHES.sub("-", str(text or ""))
    flat = flat.replace("&", " and ")
    return " ".join(flat.split()).strip().lower()


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
    """Which column actually holds the survey sections, or ``None`` if there is no book.

    A candidate has to satisfy BOTH the warehouse and the flow registry: the physical table
    is what the SQL runs against, and ``core.analytics.sql.safe_column`` refuses any
    identifier the flow does not declare. Picking a column that only one of them knows is
    what turns a missing declaration into an opaque "compute_breakdown failed" on every cut
    of the page, so a name only one side knows is reported here instead.
    """
    from core.analytics.sql import flow_spec, resolve_engine, table_columns

    columns = _safe(table_columns, _safe(resolve_engine, result.engine), SURVEY_TABLE) or frozenset()
    spec = _safe(flow_spec, SURVEY_FLOW)
    declared = set(spec.columns) if spec is not None else set()
    for candidate in SECTION_CANDIDATES:
        if candidate in columns and candidate in declared:
            return candidate
    undeclared = [c for c in SECTION_CANDIDATES if c in columns]
    if undeclared:
        logger.warning("survey.facts: table %s has %s but flows.yaml does not declare it — "
                       "the survey page cannot be built", SURVEY_TABLE, undeclared)
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
    return _years_for(result, _base_filters(result, country))


def _years_for(result, filters: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """``(latest surveyed year, the one before it)`` for an arbitrary survey cut."""
    facts = _breakdown(result, (YEAR_COL,), filters)
    years = sorted({int(f.dims[YEAR_COL]) for f in facts if f.dims.get(YEAR_COL) is not None})
    if not years:
        return None, None
    latest = years[-1]
    return latest, (latest - 1 if (latest - 1) in years else None)


def load_overall_score(result, countries: Sequence[str] = ()) -> Optional[float]:
    """The subject's average survey score at its latest surveyed year — the overall KPI.

    Scoped by ``countries`` when the run pins any, so the tile reports on the same book the
    rest of the page does; carrier-wide otherwise. ``None`` whenever the survey book has
    nothing to say for that scope — there is no premium-side number that could stand in for
    a survey score, so the caller takes the tile off the page instead.
    """
    if section_column(result) is None:
        return None
    filters: Dict[str, Any] = {CARRIER_COL: str(result.subject)}
    scope = tuple(str(c) for c in countries if str(c).strip())
    if scope:
        filters[COUNTRY_COL] = scope
    year, _ = _years_for(result, filters)
    if year is None:
        return None
    return _one(_breakdown(result, (), {**filters, YEAR_COL: int(year)}))


# ── the table ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoreGrid:
    """The Carrier Survey table's numbers for one country.

    ``cells`` / ``prior_cells`` are keyed ``(section, practice)``; the totals are keyed by
    the one dimension they collapse to. Every key is :func:`norm_label`-normalised, and so
    is every lookup, so the template's authored wording finds the warehouse's own value
    whatever the typography. Every lookup returns ``None`` when the data has no such cut —
    the page then keeps the template's own placeholder rather than inventing a number.

    ``sections`` / ``practices`` are the data's OWN labels, kept so a page that cannot match
    its axes can report WHICH vocabulary it was matching against.
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
    sections: Tuple[str, ...] = ()
    practices: Tuple[str, ...] = ()

    def score(self, section: str, practice: str) -> Optional[float]:
        return self.cells.get(_pair(section, practice))

    def delta(self, section: str, practice: str) -> Optional[float]:
        key = _pair(section, practice)
        return _diff(self.cells.get(key), self.prior_cells.get(key))

    def section_total(self, section: str) -> Optional[float]:
        return self.section_totals.get(norm_label(section))

    def section_total_delta(self, section: str) -> Optional[float]:
        key = norm_label(section)
        return _diff(self.section_totals.get(key), self.prior_section_totals.get(key))

    def practice_total(self, practice: str) -> Optional[float]:
        return self.practice_totals.get(norm_label(practice))

    def practice_total_delta(self, practice: str) -> Optional[float]:
        key = norm_label(practice)
        return _diff(self.practice_totals.get(key), self.prior_practice_totals.get(key))

    def overall_delta(self) -> Optional[float]:
        return _diff(self.overall, self.prior_overall)


def _pair(section: str, practice: str) -> Tuple[str, str]:
    return norm_label(section), norm_label(practice)


def _diff(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    """The year-on-year change, or ``None`` when either side is missing.

    ``None`` is NOT zero: a cell with no comparable prior year makes no claim about its
    direction, so it prints its number and takes no band colour.
    """
    return None if (current is None or prior is None) else float(current) - float(prior)


def _by_pair(facts, first: str, second: str) -> Dict[Tuple[str, str], float]:
    """Keyed by NORMALISED labels — the caller looks these up with the template's wording."""
    return {_pair(f.dims[first], f.dims[second]): float(f.value)
            for f in facts if f.dims.get(first) is not None and f.dims.get(second) is not None}


def _by_one(facts, column: str) -> Dict[str, float]:
    return {norm_label(f.dims[column]): float(f.value)
            for f in facts if f.dims.get(column) is not None}


def _labels(facts, column: str) -> Tuple[str, ...]:
    """The data's OWN labels for a cut, in order — what a mismatch report has to show."""
    seen = {str(f.dims[column]) for f in facts if f.dims.get(column) is not None}
    return tuple(sorted(seen))


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

    body = _breakdown(result, (section, PRACTICE_COL),
                      {**_base_filters(result, country), YEAR_COL: int(year)})

    def cuts(for_year: int):
        filters = {**_base_filters(result, country), YEAR_COL: int(for_year)}
        pairs = (body if for_year == year
                 else _breakdown(result, (section, PRACTICE_COL), filters))
        return (
            _by_pair(pairs, section, PRACTICE_COL),
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
        sections=_labels(body, section), practices=_labels(body, PRACTICE_COL),
    )


# ── the ribbon ───────────────────────────────────────────────────────────────


def _surveyed_carriers(result, country: str) -> Tuple[str, ...]:
    """Every carrier the survey book scores in ``country``, best first, minus the subject."""
    facts = _breakdown(result, (CARRIER_COL,), {COUNTRY_COL: str(country)})
    ranked = sorted(((str(f.dims[CARRIER_COL]), float(f.value or 0.0))
                     for f in facts if f.dims.get(CARRIER_COL) is not None),
                    key=lambda pair: -pair[1])
    return tuple(name for name, _ in ranked if name != str(result.subject))


def _peer_carriers(result, country: str) -> Tuple[str, ...]:
    """The carriers the subject is ranked against, in order of authority.

    The peers pinned in Setup, else the subject's group from the survey flow's own Peers
    table, else EVERY OTHER CARRIER the survey book scores in this country.

    That last fallback exists because a chart of one carrier is not a ranking. A Peers table
    that has no row for this carrier and country — a different key column, a market it was
    never mapped in — used to leave the page with a single blue box and nothing to compare
    it to. Ranking against the whole surveyed field is a weaker statement than a curated
    peer group, but it is a true one, and it is what the reader came to the page for.
    Disclosure-safe either way: the ribbon draws peers as unnamed grey boxes carrying a
    score (``flows.yaml`` sets ``peer_names_allowed: false`` for this flow).
    """
    pinned = tuple(str(p) for p in (result.peers or ()) if str(p).strip())
    if pinned:
        return pinned
    from studio.data import peer_members

    group = tuple(_safe(peer_members, SURVEY_FLOW, str(result.subject),
                        country=str(country), engine=result.engine) or ())
    if group:
        return group
    field = _surveyed_carriers(result, country)
    if field:
        logger.info("survey.facts: no Peers row for %s in %s — ranking against the %d "
                    "carrier(s) the survey book scores there",
                    result.subject, country, len(field))
    return field


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

    One query for the whole country-year, bucketed by section HERE rather than one filtered
    query per authored label: the label has to match the warehouse's own wording, and a SQL
    equality cannot be told to ignore a dash flavour or a stray capital (see
    :func:`norm_label`). Cheaper too — one scan instead of one per row.
    """
    section = section_column(result)
    if section is None:
        return None
    year, _ = _reported_years(result, country)
    if year is None:
        return None
    subject = str(result.subject)
    wanted = {subject, *(_peer_carriers(result, country))}

    scored: Dict[str, List[Tuple[str, float]]] = {}
    for fact in _breakdown(result, (section, CARRIER_COL),
                           {COUNTRY_COL: str(country), YEAR_COL: int(year)}):
        carrier = str(fact.dims.get(CARRIER_COL))
        if fact.dims.get(section) is None or carrier not in wanted or fact.value is None:
            continue
        scored.setdefault(norm_label(fact.dims[section]), []).append((carrier, float(fact.value)))

    columns = []
    for label in sections:
        ranked = sorted(scored.get(norm_label(label), []), key=lambda pair: -pair[1])
        if not ranked:
            continue
        boxes = _capped([ribbon_mod.RibbonBox(name, value, highlight=(name == subject))
                         for name, value in ranked])
        columns.append(ribbon_mod.RibbonColumn(str(label), boxes))

    return ribbon_mod.RibbonSpec(tuple(columns)) if columns else None
