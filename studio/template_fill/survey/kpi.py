"""The "Overall Carrier Survey" KPI tile on the summary page — filled, or taken off.

The tile reports a broker-survey score, which lives in a different book from every other
figure on the page. So it is generated on the SURVEY DATA BASIS only (Setup → "Premium +
survey"): a premium-basis run was not asked about the survey book, and a run whose
warehouse has no survey rows has nothing to say — in both cases the tile comes off the
slide whole rather than shipping the template's own ``x.x``.

Recognised by its CAPTION, the same way :mod:`studio.template_fill.kpi_band` recognises the
band by its header text, so the tile follows its page if the author moves it — and so a
template that carries no such tile (the product and country decks) is simply left alone.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from logger import get_logger
from studio.compute import DATA_BASIS_WITH_SURVEY
from studio.template_fill import roles as R
from studio.template_fill.analyze import Shape, Template
from studio.template_fill.survey import facts as survey_facts

logger = get_logger(__name__)

# "Overall Carrier Survey", "Overall survey score" — the caption the author writes over the
# score. Deliberately requires "overall": the Carrier Survey PAGE is titled "Carrier Survey",
# and that title is not a KPI tile.
_CAPTION = re.compile(r"overall\s+(?:carrier\s+)?survey", re.I)


def _caption_of(shape: Shape) -> str:
    return " ".join(shape.paragraphs or ())


def tiles(template: Template) -> List[str]:
    """``["<slide>:<shape>"]`` for every survey-score tile in ``template`` (usually one)."""
    return [f"{slide.index}:{sh.shape_id}"
            for slide in template.slides for sh in slide.shapes
            if sh.kind == "text" and _CAPTION.search(_caption_of(sh))]


def on_survey_basis(result) -> bool:
    """Whether the run was asked for the survey book at all (Setup → DATA BASIS)."""
    return str(getattr(result, "data_basis", "") or "") == DATA_BASIS_WITH_SURVEY


def _score(result) -> Optional[float]:
    """The subject's overall survey score for the run's own country scope."""
    from studio.template_fill.bindings import selected_countries

    return survey_facts.load_overall_score(result, selected_countries(result))


def values(template: Template, result) -> Dict[str, Any]:
    """Fill the tile with the overall score, or ask the fill engine to drop it.

    One of two payloads, never both: the score under its role, or the tile's shape key
    under ``drop_shapes`` (:func:`studio.template_fill.fill._drop_shapes`).
    """
    found = tiles(template)
    if not found:
        return {}
    score = _score(result) if on_survey_basis(result) else None
    if score is None:
        logger.info("survey.kpi: no survey score in scope — dropping %d tile(s)", len(found))
        return {"drop_shapes": found}
    return {R.ROLE_SURVEY_SCORE: float(score)}
