"""
filtering/prefilter.py

Stage 3.5 — Cheap Content-Unit Pre-Filter (no LLM calls).

filtering/rules.py + noise_filter.py operate on individual RawElements and
decide noise vs. content *before* grouping. Some elements that are not noise
in isolation (a bare section header, a repeated slide title, a one-word
label like "Attendees" or "Performance") still end up as their own
SemanticContentUnit after grouping, because they sit far enough from other
shapes that spatial clustering can't merge them with real content.

Every SCU that reaches enrichment/classification costs at minimum:
  - 2 enrichment LLM calls   (context pass + KPI pass)
  - 4 umbrella LLM calls     (one per umbrella, concurrent)
  - 1 action-item LLM call
  - up to 4 more sub-category calls if any umbrella fires
i.e. 7-11 LLM calls for a content unit that is, semantically, just a label.

This module re-uses the same rule-based philosophy as filtering/rules.py
(fast, deterministic, auditable, no LLM) but operates one stage later, on
SemanticContentUnits, to catch exactly this class of unit before it is
ever sent to enrichment. Structured data (tables, charts, KPI cards) is
NEVER skipped here — only short, punctuation-free, digit-free text
fragments that read like standalone headers/labels rather than sentences.

Caption safety net
-------------------
A short header is sometimes the ONLY place a chart/table/bare-value SCU's
name lives (e.g. a lone "€11m+" card sitting under a "GWP Growth in
Germany" caption, or a chart_insight with no title in its own content).
Dropping the caption would silently strip meaning from a unit we always
keep. So after the context-free is_substantive() pass, a second,
slide-local pass re-checks every header-like skip candidate against the
SPATIALLY nearest SCU(s) on the same slide — using bounding-box centroid
distance, not reading_order.

The nearest-neighbour search is restricted to candidates that actually
matter for this check: never-skip structured types and bare numeric
value fragments. It is NOT "find the single nearest SCU of any type and
then check its type" — on real slides (e.g. a full-width banner sitting
between a caption and the chart it labels) an unrelated text unit can be
marginally closer in raw centroid distance than the structured unit the
caption is actually pairing with (seen on real data: an unrelated banner
at 2.454in vs. the correct chart at 2.484in — a 0.03in margin that a
single-nearest-of-any-type search gets wrong). Searching only among
structured/bare-value candidates avoids this false negative entirely
and is also cheaper.

Reading order was tried first and rejected: on real decks (e.g. a
zig-zag KPI-card grid), the caption immediately below a value is often
several positions away in reading order even though it sits right next
to it on the slide, so reading-order adjacency silently missed real
caption/value pairs that spatial distance catches correctly. This can
occasionally keep a caption that turns out not to be load-bearing
(e.g. a list of industry-sector labels next to an unrelated KPI card)
— that is an acceptable false-negative on the cost side; it never
causes silent data loss.

Usage
-----
prefilter = ContentPreFilter()
eligible, skipped = prefilter.filter(all_scus)
# eligible -> pass to EnrichmentLLM as before
# skipped  -> never enriched/classified; kept only for the audit artefact
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import List, Optional, Tuple

from recap.schemas.content_units import ContentUnitType, SemanticContentUnit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------

# A unit with this many words or fewer is "header-length" — a real sentence
# describing a business point is almost never this short.
MAX_HEADER_WORDS = 4

# Content-unit types that always carry structured/quantitative data and
# must never be skipped, regardless of length (mirrors rules.py's
# "structured elements always kept" rule for images/charts/tables).
_NEVER_SKIP_TYPES = {
    ContentUnitType.KPI_CARD,
    ContentUnitType.CHART_INSIGHT,
    ContentUnitType.TABLE_BLOCK,
    ContentUnitType.TABLE_ROW,
    ContentUnitType.ACTION_ITEM,
    ContentUnitType.NARRATIVE,
}

# Sentence-ending punctuation. A unit whose text ends in one of these reads
# like a real sentence/clause, not a bare label, so it's never skipped even
# if short (e.g. "Portfolio grew." is 2 words but is a real statement).
_SENTENCE_END_CHARS = (".", "!", "?")

def _is_bare_value_fragment(scu: SemanticContentUnit) -> bool:
    """
    True if this SCU is essentially just a number/percentage/currency
    value with little or no descriptive text of its own (e.g. "€11m+",
    "65%") — the kind of fragment that relies entirely on a neighbouring
    caption to be meaningful.
    """
    if not (scu.has_numeric_value or scu.has_percentage or scu.has_currency):
        return False
    word_count = len(scu.content.strip().split())
    return word_count <= MAX_HEADER_WORDS


def _centroid(scu: SemanticContentUnit) -> Optional[Tuple[float, float]]:
    """Bounding-box centroid (EMU) for a SCU, or None if no bounds recorded."""
    if scu.bounding_x is None or scu.bounding_y is None:
        return None
    w = scu.bounding_width or 0
    h = scu.bounding_height or 0
    return (scu.bounding_x + w / 2.0, scu.bounding_y + h / 2.0)


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Core decision function
# ---------------------------------------------------------------------------

def is_substantive(scu: SemanticContentUnit) -> Tuple[bool, str]:
    """
    Decide whether a SemanticContentUnit is worth sending through the
    (expensive) enrichment + classification stages.

    Returns
    -------
    (True, "")            — send to enrichment as normal.
    (False, reason)        — skip; reason is a short machine-readable tag
                              recorded on the audit artefact.
    """
    # Structured/quantitative content is always kept.
    if scu.content_unit_type in _NEVER_SKIP_TYPES:
        return True, ""

    # Any unit carrying a numeric, percentage, currency, or trend signal
    # may be an orphaned KPI value — always keep it; dropping it would be
    # a silent data-loss regression, not a cost optimisation.
    if scu.has_numeric_value or scu.has_percentage or scu.has_currency or scu.has_trend_indicator:
        return True, ""

    text = scu.content.strip()
    if not text:
        return False, "empty_content"

    # Multi-line content is very unlikely to be a bare header/label —
    # only single-line fragments are candidates for skipping.
    if "\n" in text:
        return True, ""

    # A unit whose text ends like a sentence is a real statement, not a
    # label, even if short — always keep it.
    if text.endswith(_SENTENCE_END_CHARS):
        return True, ""

    word_count = len(text.split())

    # Exact duplicate of the slide title carries zero incremental
    # information beyond what's already known from slide context.
    if scu.slide_title and text.lower() == scu.slide_title.strip().lower():
        return False, "duplicate_of_slide_title"

    # Short, punctuation-free, digit-free single-line fragment — reads
    # like a bare section header/label (e.g. "Attendees", "Performance",
    # "Leadership Introductions", "The Vision") rather than a business
    # statement with a subject and a claim.
    if word_count <= MAX_HEADER_WORDS:
        return False, "short_header_like_fragment"

    return True, ""


# ---------------------------------------------------------------------------
# Batch filter with logging/audit support
# ---------------------------------------------------------------------------

class ContentPreFilter:
    """
    Applies is_substantive() to a full list of SemanticContentUnits and
    splits them into (eligible, skipped), logging aggregate stats so the
    LLM-call savings are visible in normal pipeline logs.
    """

    def filter(
        self, scus: List[SemanticContentUnit]
    ) -> Tuple[List[SemanticContentUnit], List[SemanticContentUnit]]:
        eligible: List[SemanticContentUnit] = []
        skipped: List[SemanticContentUnit] = []
        reasons: Counter = Counter()
        restored = 0

        # Pass 1: context-free heuristic decision per SCU.
        decisions: List[Tuple[SemanticContentUnit, bool, str]] = [
            (scu, *is_substantive(scu)) for scu in scus
        ]

        # Pass 2: caption safety net. A header-like skip is restored if there
        # is a nearby structured/mixed-never-skip SCU or bare numeric fragment
        # on the same slide that would otherwise lose its only naming context.
        # The nearest-neighbour search is restricted to those candidate types
        # ONLY (never "nearest SCU of any type") — see module docstring for
        # why an unrestricted nearest-of-any-type search silently picks the
        # wrong neighbour on real slide layouts.
        # Grouped by slide so neighbours never cross slide boundaries.
        by_slide: dict = {}
        for scu, keep, reason in decisions:
            by_slide.setdefault(scu.slide_number, []).append((scu, keep, reason))

        final_keep: dict = {}
        final_reason: dict = {}
        for slide_items in by_slide.values():
            # Precompute candidate neighbours for this slide: never-skip
            # structured types, or bare numeric/pct/currency fragments.
            candidates = [
                other for other, _, _ in slide_items
                if other.content_unit_type in _NEVER_SKIP_TYPES
                or _is_bare_value_fragment(other)
            ]

            for scu, keep, reason in slide_items:
                if keep or reason != "short_header_like_fragment":
                    final_keep[scu.content_unit_id] = keep
                    final_reason[scu.content_unit_id] = reason
                    continue

                own_centroid = _centroid(scu)
                nearest = None
                nearest_dist = None
                if own_centroid is not None:
                    for other in candidates:
                        if other.content_unit_id == scu.content_unit_id:
                            continue
                        other_centroid = _centroid(other)
                        if other_centroid is None:
                            continue
                        dist = _distance(own_centroid, other_centroid)
                        if nearest_dist is None or dist < nearest_dist:
                            nearest_dist = dist
                            nearest = other

                if nearest is not None:
                    final_keep[scu.content_unit_id] = True
                    final_reason[scu.content_unit_id] = ""
                    restored += 1
                else:
                    final_keep[scu.content_unit_id] = False
                    final_reason[scu.content_unit_id] = reason

        for scu, _, _ in decisions:
            keep = final_keep[scu.content_unit_id]
            reason = final_reason[scu.content_unit_id]
            if keep:
                eligible.append(scu)
            else:
                skipped.append(scu)
                reasons[reason] += 1

        if restored:
            logger.info(
                "Stage 3.5: Pre-filter restored %d header-like unit(s) "
                "that caption a neighbouring structured/bare-value SCU",
                restored,
            )

        if skipped:
            # Each skipped unit avoids at minimum 2 enrichment + 4 umbrella
            # + 1 action-item = 7 LLM calls (more if sub-categories would
            # have fired). This is a conservative floor for the log line.
            logger.info(
                "Stage 3.5: Pre-filter skipped %d/%d content units "
                "(≈%d+ LLM calls saved) — reasons: %s",
                len(skipped),
                len(scus),
                len(skipped) * 7,
                dict(reasons),
            )
        else:
            logger.info("Stage 3.5: Pre-filter skipped 0/%d content units", len(scus))

        return eligible, skipped
