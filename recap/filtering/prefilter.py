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
import re
from collections import Counter
from typing import List, Optional, Tuple

from recap.schemas.content_units import ContentUnitType, SemanticContentUnit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------

# A unit with this many words or fewer is "header-length" — a real sentence
# describing a business point is almost never this short.
# Raised from 4 → 6: a 4-word cap was incorrectly filtering strategic
# sub-headings like "Client Segmentation Focus" (3 words) and
# "Multinational Development" (2 words) that appear as meaningful category
# labels on strategy slides.
MAX_HEADER_WORDS = 6

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

# ---------------------------------------------------------------------------
# Known Line-of-Business vocabulary
# ---------------------------------------------------------------------------
# Short single-word (or short multi-word) labels that are genuine LoB names
# must never be suppressed by the short_header_like_fragment rule — they are
# the only place LoB context appears on many chart slides.  This set is
# intentionally broad: false positives (keeping a non-LoB word that happens
# to match) have negligible cost; false negatives (dropping a real LoB label)
# strip commercial attribution from every downstream stage.
#
# Match is case-insensitive against the *full stripped text* of the SCU as
# well as *any individual word* within it, so multi-word labels like
# "Financial Lines" and single-word labels like "Marine" both match.
_LOB_VOCABULARY: set[str] = {
    # Core insurance lines
    "marine", "aviation", "energy", "property", "casualty", "liability",
    "motor", "health", "life", "cyber", "construction", "engineering",
    "cargo", "hull", "specie", "war", "terrorism", "kidnap",
    # Financial/professional lines
    "finpro", "financial lines", "financial", "professional", "pi", "d&o",
    "directors", "officers", "fidelity", "crime", "surety", "credit",
    "political", "trade credit", "transactional",
    # Specialty / regional
    "pema", "latam", "apac", "emea", "dach",
    "reinsurance", "facultative", "treaty", "excess", "surplus",
    "accident", "personal accident", "pa",
    # Segment / portfolio labels
    "specialty", "commercial", "corporate", "sme", "mid-market", "midmarket",
    "wholesale", "retail", "multinational", "global", "local",
    "infrastructure", "natural resources", "power", "mining",
    "agriculture", "agri", "forestry",
}


def _is_lob_label(text: str) -> bool:
    """
    Return True if *text* matches a known LoB name — either the whole
    stripped text or any single word within it, case-insensitive.
    This prevents short LoB labels from being dropped by the
    short_header_like_fragment rule.
    """
    t = text.strip().lower()
    if t in _LOB_VOCABULARY:
        return True
    # Also check individual words so "Financial Lines" (2 words) matches
    # "financial lines" in the set.
    words = t.split()
    if len(words) >= 2:
        for size in (2, 3):
            for i in range(len(words) - size + 1):
                phrase = " ".join(words[i:i + size])
                if phrase in _LOB_VOCABULARY:
                    return True
    return False


# ---------------------------------------------------------------------------
# Legal / boilerplate detection
# ---------------------------------------------------------------------------
# Patterns that identify Marsh/MMC standard legal footer text that appears
# on back-cover and disclaimer slides.  These should always be filtered out
# regardless of numeric content (registration numbers contain digits that
# would otherwise trip the numeric early-pass).
_LEGAL_PATTERNS = [
    re.compile(r"registered\s+in\s+england\s+and\s+wales", re.I),
    re.compile(r"registered\s+office\s*:", re.I),
    re.compile(r"authorised\s+and\s+regulated\s+by\s+the\s+financial", re.I),
    re.compile(r"financial\s+conduct\s+authority", re.I),
    re.compile(r"marsh\s+(?:ltd|limited)\b", re.I),
    re.compile(r"all\s+rights\s+reserved", re.I),
    re.compile(r"confidential(?:ity)?\s+notice", re.I),
    re.compile(r"this\s+(?:document|presentation|report)\s+(?:is\s+)?(?:confidential|for\s+information)", re.I),
]


def _is_legal_boilerplate(text: str) -> bool:
    """
    Return True if *text* reads like a legal / disclaimer / registered-office
    footer that should always be suppressed regardless of numeric content.
    """
    for pat in _LEGAL_PATTERNS:
        if pat.search(text):
            return True
    return False


# ---------------------------------------------------------------------------
# Image-only chart sentinel detection
# ---------------------------------------------------------------------------
# The extractor emits a sentinel line "[IMAGE-ONLY CHART: data not
# extractable — do not assert specific values or trend direction]" for any
# chart element that is stored as a raster image with no underlying PPTX
# chart XML.  An SCU whose content consists ONLY of such sentinel line(s)
# — with nothing else — carries zero extractable business data.  Sending it
# through enrichment wastes 2 LLM calls (context + KPI) and 4-5 more in
# classification, returning empty metadata every time.  This guard detects
# that case deterministically and routes the unit to the skip list instead.
#
# Safety: the check is strict — the unit is only skipped when the sentinel
# accounts for ALL non-whitespace content (i.e. there is no accompanying
# prose or numeric context that would make it worth enriching).  A slide
# that mixes an image-only chart with a real narrative paragraph produces a
# mixed-type SCU whose non-sentinel text will NOT be all-sentinel, so it
# passes through normally.
_RE_IMAGE_ONLY_SENTINEL_LINE = re.compile(
    r"^\[IMAGE-ONLY[^\]]*\][^\n]*$", re.M | re.IGNORECASE
)


def _is_image_only_sentinel(text: str) -> bool:
    """
    Return True when *text* contains at least one [IMAGE-ONLY …] sentinel
    AND has no other meaningful content once those sentinel lines are removed.
    """
    stripped_of_sentinels = _RE_IMAGE_ONLY_SENTINEL_LINE.sub("", text).strip()
    # There must be at least one sentinel line present
    has_sentinel = bool(_RE_IMAGE_ONLY_SENTINEL_LINE.search(text))
    return has_sentinel and not stripped_of_sentinels

# ---------------------------------------------------------------------------
# ICG Carrier Exec / contact-table detection
# ---------------------------------------------------------------------------
# Every country-specific slide in an ICG QBR deck contains a standard
# "ICG Carrier Exec's" box that lists the Marsh placement contact and the
# QBE relationship manager by name and title — for example:
#
#   ICG Carrier Exec's
#   Ellen Cameron   Insurer ICG Coordinator, Norway
#   Scott Ormen     CEO
#
# These contact tables:
#   - Are extracted as TABLE DATA SCUs by the extractor.
#   - Contain a country name → enrichment assigns conf 0.70–0.95 (country
#     signal fires) but returns empty LoB, KPI, and performance_direction.
#   - Are correctly rejected by all four umbrella classifiers (no commercial
#     claim) — but only AFTER 2 enrichment + 4 umbrella + 1 action-item =
#     7 LLM calls have already been wasted per slide.
#
# The "ICG Carrier Exec" phrase is a fixed template heading that appears in
# every contact block in the ICG deck format and nowhere else.  Detecting it
# deterministically here costs zero LLM calls and has zero false-positive
# risk — no real business content begins with this exact heading.
#
# Safety: the guard checks BOTH that the heading is present AND that the
# remaining lines contain no numeric or percentage signal.  A contact table
# that somehow also contains GWP figures (unexpected but theoretically
# possible) would be kept so its numeric data is not silently lost.
_RE_ICG_CONTACT_HEADING = re.compile(
    r"ICG\s+Carrier\s+Exec",
    re.IGNORECASE,
)
_RE_NUMERIC_OR_PCT = re.compile(r"[\d]+(?:[.,]\d+)?[%mMkKbB€£$]?|[€£$][\d]")
# TABLE DATA extractor prefix lines that must be excluded from the numeric
# check (they always contain digits as part of the row/col count, e.g.
# "Table (2 rows x 2 cols)").
_RE_TABLE_STRUCTURE_LINE = re.compile(
    r"^\s*(?:\[TABLE DATA\]|\[CHART DATA\]|Table\s*\(\d+\s*rows?\s*x\s*\d+\s*cols?\))",
    re.IGNORECASE,
)


def _is_icg_contact_table(text: str) -> bool:
    """
    Return True when *text* is an ICG Carrier Exec's contact block —
    i.e. it contains the 'ICG Carrier Exec' heading and the remaining
    content is entirely names/roles with no numeric or percentage signal.

    Strips [TABLE DATA] / "Table (N rows x M cols)" header lines before
    the numeric check — those lines always contain digits as part of the
    extractor's row/column count and must not be treated as business data.
    """
    if not _RE_ICG_CONTACT_HEADING.search(text):
        return False
    # Strip the ICG heading line(s) AND extractor-format header lines,
    # then check what remains for any genuine numeric/percentage/currency.
    remaining_lines = [
        line for line in text.splitlines()
        if not _RE_ICG_CONTACT_HEADING.search(line)
        and not _RE_TABLE_STRUCTURE_LINE.match(line)
    ]
    remaining = " ".join(remaining_lines).strip()
    # If any genuine numeric / percentage / currency signal remains in the
    # non-heading content, this is not a pure contact table — keep it.
    if _RE_NUMERIC_OR_PCT.search(remaining):
        return False
    return True


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
    # Legal / boilerplate footer text is always dropped, even if it contains
    # digits (e.g. a company registration number).  This check must come
    # before the numeric early-pass below.
    if _is_legal_boilerplate(scu.content):
        return False, "legal_boilerplate"

    # Image-only chart sentinels — an SCU whose entire content is one or more
    # "[IMAGE-ONLY CHART: …]" placeholder lines (emitted when the extractor
    # cannot read a raster-image chart) carries zero extractable business data.
    # Enriching it wastes 2 context/KPI LLM calls and 4-5 classifier calls
    # while returning empty metadata every time.  Skip it here so those tokens
    # are saved.  (Fix for issue 4.4 — image-only SCUs producing 58% low-conf
    # insights and 74% missing KPI/metric rates on the QBE Q2 2026 run.)
    if _is_image_only_sentinel(scu.content):
        return False, "image_only_sentinel"

    # ICG Carrier Exec's contact tables — standard per-country boilerplate
    # listing the Marsh placement lead and QBE relationship manager by name
    # and title only (no numeric / LoB / performance data).  The enrichment
    # LLM incorrectly assigns high confidence (0.70–0.95) to these because
    # they contain a country name, but all four umbrella classifiers then
    # correctly reject them — wasting 7+ LLM calls per country slide for
    # zero recap contribution.  Detecting them deterministically here with
    # zero LLM cost: the heading "ICG Carrier Exec" is a fixed template
    # phrase that appears in every ICG deck contact block and nowhere else.
    if _is_icg_contact_table(scu.content):
        return False, "contact_table"

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
    # Exception: known Line-of-Business labels (e.g. "Marine", "Finpro",
    # "PEMA", "Financial Lines") must never be dropped here — they are the
    # only place LoB context appears on many chart slides and their loss
    # silently strips commercial attribution from every downstream stage.
    if word_count <= MAX_HEADER_WORDS:
        if _is_lob_label(text):
            return True, ""
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
                # Annotate with the filter reason so the 02b artefact carries
                # a machine-readable audit trail explaining why each unit was
                # dropped without needing a separate lookup structure.
                skipped.append(scu.model_copy(update={"filter_reason": reason or "unknown"}))
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
