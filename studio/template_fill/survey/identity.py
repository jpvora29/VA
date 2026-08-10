"""Who the subject IS in the survey book — and who its peers are there.

The two books name carriers differently and always will. The premium book groups them
(``Carrier_Group``: "Zurich"); the survey book records the entity that was surveyed
(``Carrier``: "Zurich Insurance Company Ltd"). A deck is driven from the premium side, so
its subject is a group name, and asking the survey book for it verbatim either finds
nothing — an empty page — or, worse, finds a DIFFERENT carrier's rows and reports them
under this carrier's name.

So the survey identity is resolved on the survey book's own terms, in one place, in this
order:

  1. what Setup pinned (the author saw both vocabularies and chose);
  2. an exact match, ignoring case and punctuation;
  3. a confident fuzzy match against the carriers surveyed IN SCOPE;
  4. nothing — and the page is not generated.

Step 4 is the point of the module. A survey page reporting scores that belong to another
carrier is worse than no survey page, and only an explicit "no match" can prevent it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

# How alike two names must be before we will call them the same carrier. rapidfuzz's
# token_set_ratio ignores word order and extra words, so "Zurich" scores 100 against
# "Zurich Insurance Company Ltd" while "AXA XL" scores far below this against "AIG".
# Deliberately high: the cost of a false match is a page of someone else's scores.
_MATCH_FLOOR = 90

# Corporate-form noise that says nothing about WHICH carrier this is.
_NOISE = re.compile(
    r"\b(insurance|assurance|reinsurance|company|companies|co|corporation|corp|group|"
    r"holdings?|limited|ltd|plc|inc|sa|se|ag|nv|bv|pte|pty|llc|lp|branch)\b", re.I)


def _key(name: Any) -> str:
    """A carrier name reduced to its identifying words, for the exact-match pass."""
    flat = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    return " ".join(_NOISE.sub(" ", flat).split())


def _carriers(result, countries: Sequence[str] = ()) -> Tuple[str, ...]:
    """Every carrier the survey book holds, narrowed to ``countries`` when given."""
    from studio.template_fill.survey import facts

    filters: Dict[str, Any] = {}
    scope = tuple(str(c) for c in countries if str(c).strip())
    if scope:
        filters[facts.COUNTRY_COL] = scope
    rows = facts._breakdown(result, (facts.CARRIER_COL,), filters)
    names = {str(f.dims[facts.CARRIER_COL]) for f in rows
             if f.dims.get(facts.CARRIER_COL) is not None}
    return tuple(sorted(names))


def _best_match(name: str, candidates: Sequence[str]) -> Optional[str]:
    """The candidate that is the same carrier as ``name``, or ``None``.

    Exact on the identifying words first, so "Zurich" finds "Zurich Insurance Company Ltd"
    without any scoring at all; fuzzy only decides what punctuation and spelling cannot.
    """
    if not name or not candidates:
        return None
    wanted = _key(name)
    if not wanted:
        return None
    exact = [c for c in candidates if _key(c) == wanted]
    if exact:
        return exact[0]
    from rapidfuzz import fuzz, process

    hit = process.extractOne(wanted, [_key(c) for c in candidates],
                             scorer=fuzz.token_set_ratio, score_cutoff=_MATCH_FLOOR)
    return candidates[hit[2]] if hit else None


def carrier_options(result, countries: Sequence[str] = ()) -> Tuple[str, ...]:
    """Every carrier Setup can offer for this scope — the survey book's own names."""
    return _carriers(result, countries)


def resolve_carrier(result, countries: Sequence[str] = ()) -> Optional[str]:
    """The subject's name IN THE SURVEY BOOK, or ``None`` when it is not surveyed here.

    ``None`` is a real answer: the carrier has no survey presence in this scope, and the
    page must not be built rather than built from whoever matched loosely.
    """
    pinned = str(getattr(result, "survey_carrier", "") or "").strip()
    candidates = _carriers(result, countries)
    if pinned:
        # Still resolved against the book, so a pin made under one country selection does
        # not silently report nothing under another.
        return _best_match(pinned, candidates) or pinned
    subject = str(getattr(result, "subject", "") or "").strip()
    match = _best_match(subject, candidates)
    if match is None:
        logger.warning("survey.identity: %r is not in the survey book for %s — the survey "
                       "page is not generated. The book holds: %s",
                       subject, list(countries) or "any country", list(candidates)[:20])
    elif match != subject:
        logger.info("survey.identity: premium %r resolved to survey carrier %r",
                    subject, match)
    return match


def resolve_peers(result, subject: str, countries: Sequence[str] = ()) -> Tuple[str, ...]:
    """The peer set in the SURVEY book's vocabulary, from whichever source Setup used.

    A peer list pinned on the premium side names carrier GROUPS, which the survey book has
    never heard of — matched here rather than dropped, so a Setup peer selection means the
    same thing on both pages.
    """
    candidates = [c for c in _carriers(result, countries) if c != subject]
    pinned = tuple(str(p) for p in (getattr(result, "survey_peers", None) or ()) if str(p).strip())
    if not pinned:
        pinned = tuple(str(p) for p in (getattr(result, "peers", None) or ()) if str(p).strip())
    if not pinned:
        return ()
    matched: List[str] = []
    for name in pinned:
        hit = _best_match(name, candidates)
        if hit is not None and hit not in matched:
            matched.append(hit)
    missing = [p for p in pinned if _best_match(p, candidates) is None]
    if missing:
        logger.info("survey.identity: %d pinned peer(s) are not in the survey book: %s",
                    len(missing), missing)
    return tuple(matched)
