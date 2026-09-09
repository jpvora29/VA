"""The whole "what drove the movement" analysis, as one readable sequence.

Three questions, asked in the order an analyst asks them, each answered by its
own module:

    what moved          core.answers.contribution  -> which slices, by how much
    what KIND of move   core.answers.shape         -> concentrated? offsetting?
    what is odd         core.answers.unusual       -> out of character vs itself

Keeping them separate matters because they fail separately and are true
separately. The decomposition needs two periods and a dimension; the shape needs
a decomposition; the unusual reading needs three periods and gets nothing from
two. A panel built on one blob would have to hedge all three at once — this
returns exactly what the rows can support and says nothing about the rest.

The payload is a plain dict so it can ride in the transcript. Every key the panel
read before is still there and means the same thing; `headline` now carries the
SHAPE-aware sentence, which is the point of the whole exercise.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from core.answers import shape as shape_mod
from core.answers import unusual as unusual_mod
from core.answers.contribution import Contribution, decompose


def _payload(
    contribution: Contribution,
    profile: shape_mod.Profile,
    unusual: Sequence[unusual_mod.Unusual],
) -> Dict[str, Any]:
    """One dict carrying all three readings, keyed as the panel expects."""
    payload = contribution.as_dict()
    payload.update(
        {
            # The lead sentence: what this movement IS, before any bar.
            "headline": profile.lead,
            "shape": profile.shape,
            "profile": profile.as_dict(),
            "unusual": [u.as_dict() for u in unusual],
            "period_word": unusual_mod.period_word(contribution.period_column),
        }
    )
    return payload


def analyse(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Everything the drivers panel shows, from the rows behind an answer.

    Returns the honest note instead when the rows cannot support a
    decomposition — `drivers` is empty in that case, and that is how the caller
    tells whether the analysis is worth showing.
    """
    contribution = decompose(rows)
    if not contribution.is_supported:
        return contribution.as_dict()

    profile = shape_mod.classify(contribution)
    unusual = unusual_mod.find_unusual(rows, contribution, already_told=profile.leaders)
    return _payload(contribution, profile, unusual)


def is_supported(payload: Mapping[str, Any] | None) -> bool:
    """Whether an analysis found anything to show."""
    return bool((payload or {}).get("drivers"))


def leaders_of(payload: Mapping[str, Any] | None) -> List[str]:
    """The slices the lead sentence names, so the panel can highlight those rows."""
    profile = (payload or {}).get("profile") or {}
    return [str(name) for name in (profile.get("leaders") or [])]
