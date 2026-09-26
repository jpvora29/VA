"""Survey scores by practice, for the premium pages' commentary.

On the GPR + Survey basis the Carrier Survey page reports the scores, but the premium
pages around it could not mention them — so "Casualty premium fell" and "Casualty is where
the survey score slipped" were never said in the same breath, which is exactly how an ICL
would say it. This reads the practice totals (and their year-on-year movement) for the
sub-deck's one market and pairs each practice with the premium line it describes.

A practice is the survey's own vocabulary ("FINPRO"), so :data:`PRACTICE_ALIASES` names
the premium line it corresponds to. Only a single-market scope is read: a survey is
answered per country, and averaging practices across countries would describe no market
anyone was surveyed in.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from logger import get_logger

logger = get_logger(__name__)

#: survey practice (normalised) -> the premium line it describes (normalised).
PRACTICE_ALIASES: Mapping[str, str] = {
    "finpro": "financial lines",
    "fin pro": "financial lines",
    "financial & professional": "financial lines",
    "ce/cm": "construction",
    "marine & energy": "marine",
}


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def line_for(practice: str) -> str:
    """The premium line a survey practice describes (its own name when no alias applies)."""
    key = _norm(practice)
    return PRACTICE_ALIASES.get(key, key)


def _one_country(filters: Mapping[str, Any]) -> Optional[str]:
    value = filters.get("Country")
    values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    values = [v for v in values if v]
    return str(values[0]) if len(values) == 1 else None


def load(result, filters: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """``[{practice, line, score, prior, delta, year, prior_year, country}]`` — or ``[]``.

    Empty off the survey basis, for a multi-market scope, and wherever the survey book
    holds nothing for the subject. Best-effort: a survey that cannot be read costs the
    commentary a family of facts, never the deck.
    """
    from studio.template_fill.survey import facts as survey_facts
    from studio.template_fill.survey.kpi import on_survey_basis

    country = _one_country(filters)
    if country is None or not on_survey_basis(result):
        return []
    try:
        grid = survey_facts.load_grid(result, country)
    except Exception as exc:  # noqa: BLE001
        logger.warning("survey lines: could not read the survey for %s: %s", country, exc)
        return []
    if grid is None:
        return []
    rows = []
    for practice in grid.practices:
        score = grid.practice_total(practice)
        if score is None:
            continue
        prior = grid.prior_practice_totals.get(survey_facts.norm_label(practice))
        rows.append({"practice": practice, "line": line_for(practice), "score": score,
                     "prior": prior, "delta": grid.practice_total_delta(practice),
                     "year": grid.year, "prior_year": grid.prior_year, "country": country})
    return rows
