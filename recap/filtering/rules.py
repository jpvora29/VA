"""
filtering/rules.py

Fast rule-based noise detection — O(1) per element, no LLM calls.

Returns a FilterDecision for every element. Elements that are
DEFINITELY noise or DEFINITELY content are decided here.
Elements that are ambiguous (confidence < AMBIGUITY_THRESHOLD)
are forwarded to the LLM pass in noise_filter.py.
"""

from __future__ import annotations

import re
from typing import Optional

from recap.schemas.raw_extraction import ElementType, RawElement
from recap.schemas.filtered import FilterDecision, FilterReason

# Confidence below this value triggers an LLM ambiguity pass
AMBIGUITY_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Bare page / slide numbers: "1", "2 / 14", "Slide 3", "Page 4 of 20"
_RE_PAGE_NUM = re.compile(
    r"^(?:slide\s+|page\s+)?\d+(?:\s*/\s*\d+|\s+of\s+\d+)?$",
    re.IGNORECASE,
)

# Copyright / confidentiality / legal
_RE_COPYRIGHT = re.compile(
    r"©|\bcopyright\b|all rights reserved",
    re.IGNORECASE,
)
_RE_CONFIDENTIAL = re.compile(
    r"\bconfidential\b|\bproprietary\b|\bfor internal use\b|"
    r"\bnot for distribution\b|\bdo not distribute\b",
    re.IGNORECASE,
)
_RE_DISCLAIMER = re.compile(
    r"\bdisclaimer\b|\bno warranty\b|\bwithout liability\b|"
    r"\bpast performance\b.{0,60}\bguarantee\b",
    re.IGNORECASE,
)

# Common boilerplate phrases
_RE_BOILERPLATE = re.compile(
    r"^\s*(?:click to edit|insert title|your (?:company|logo) here|"
    r"confidential[-– ]+(?:draft)?|draft|tbc|tbd|placeholder|lorem ipsum)\s*$",
    re.IGNORECASE,
)

# Decorative bullets / symbols used as visual separators
_RE_DECORATIVE_ONLY = re.compile(r"^[\s|•·▪▸►▷◆○●—–\-_=+*×÷~#]+$")

# Agenda / table-of-contents slides
# Matches: "Agenda", "Table of Contents", "Contents", "Overview" as standalone title/shape
_RE_AGENDA_TITLE = re.compile(
    r"^\s*(?:agenda|table\s+of\s+contents?|contents?|overview|index|topics?)\s*$",
    re.IGNORECASE,
)
# Matches agenda-list text: numbered items separated by | or newlines like
# "1 | Topic A | 2 | Topic B" or "1. Intro\n2. Data\n3. Summary"
_RE_AGENDA_LIST = re.compile(
    r"(?:(?:\d+\s*[|.)\-]\s*[A-Za-z].{0,80}){2,})"  # 2+ numbered items
    r"|"
    r"(?:[A-Za-z].{0,60}\s*\|\s*\d+\s*\|\s*[A-Za-z])",  # "Topic | N | Topic" pattern
    re.IGNORECASE | re.DOTALL,
)

# Footer placeholder types
_FOOTER_PH_TYPES = {"FOOTER", "SLIDE_NUMBER", "DATE_AND_TIME"}

# Very short text that might be a page number disguised as content
_RE_STANDALONE_INT = re.compile(r"^\d{1,3}$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_rules(
    element: RawElement,
    client_name: Optional[str] = None,
    company_name: Optional[str] = None,
) -> FilterDecision:
    """
    Apply all rule-based checks to a single element.

    Returns a FilterDecision with:
      - is_noise=True  + high confidence  → definite noise
      - is_noise=False + high confidence  → definite content
      - is_noise=True/False + low conf    → forward to LLM ambiguity pass
    """

    # --- 1. Empty shapes — always noise ---
    text = (element.text or "").strip()
    has_content = bool(
        text
        or element.table
        or element.chart
        or element.alt_text
    )
    if not has_content and element.element_type not in (
        ElementType.IMAGE, ElementType.CHART, ElementType.TABLE
    ):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.EMPTY_SHAPE,
            rule_triggered="empty_shape",
            confidence=1.0,
        )

    # --- 2. Footer placeholder types ---
    if element.is_placeholder and element.placeholder_type in _FOOTER_PH_TYPES:
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.NAVIGATION_ELEMENT,
            rule_triggered="footer_placeholder_type",
            confidence=0.95,
        )

    # --- 3. Images / charts / tables — always content ---
    if element.element_type in (ElementType.IMAGE, ElementType.CHART, ElementType.TABLE):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=False,
            reason=FilterReason.RETAINED,
            rule_triggered="structured_element_always_kept",
            confidence=1.0,
        )

    # From here we work on text content
    if not text:
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.EMPTY_SHAPE,
            rule_triggered="empty_text",
            confidence=1.0,
        )

    # --- 4. Decorative-only text (bullets, dashes, symbols) ---
    if _RE_DECORATIVE_ONLY.match(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.DECORATIVE_TEXT,
            rule_triggered="decorative_only_characters",
            confidence=0.95,
        )

    # --- 5. Boilerplate placeholder text ---
    if _RE_BOILERPLATE.match(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.TEMPLATE_BOILERPLATE,
            rule_triggered="boilerplate_pattern",
            confidence=0.97,
        )

    # --- 5b. Agenda / table-of-contents content ---
    # A shape whose entire text is just "Agenda", "Contents", etc. is navigation.
    # A shape that looks like a numbered agenda list (e.g. "1 | Topic A | 2 | Topic B")
    # is also navigation and should not be classified as business insight content.
    if _RE_AGENDA_TITLE.match(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.NAVIGATION_ELEMENT,
            rule_triggered="agenda_title",
            confidence=0.97,
        )
    if _RE_AGENDA_LIST.search(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.NAVIGATION_ELEMENT,
            rule_triggered="agenda_list_pattern",
            confidence=0.92,
        )

    # --- 6. Copyright / confidentiality / disclaimer ---
    if _RE_COPYRIGHT.search(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.COPYRIGHT_NOTICE,
            rule_triggered="copyright_pattern",
            confidence=0.97,
        )
    if _RE_CONFIDENTIAL.search(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.CONFIDENTIALITY,
            rule_triggered="confidentiality_pattern",
            confidence=0.97,
        )
    if _RE_DISCLAIMER.search(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.LEGAL_DISCLAIMER,
            rule_triggered="disclaimer_pattern",
            confidence=0.90,
        )

    # --- 7. Client / company name in footer position ---
    if _is_footer_position(element):
        if client_name and _name_matches(text, client_name):
            return FilterDecision(
                element_id=element.element_id,
                is_noise=True,
                reason=FilterReason.FOOTER_CLIENT_NAME,
                rule_triggered="footer_client_name",
                confidence=0.92,
            )
        if company_name and _name_matches(text, company_name):
            return FilterDecision(
                element_id=element.element_id,
                is_noise=True,
                reason=FilterReason.FOOTER_COMPANY_NAME,
                rule_triggered="footer_company_name",
                confidence=0.92,
            )

    # --- 8. Page / slide number patterns ---
    if _RE_PAGE_NUM.match(text):
        # Could be a KPI (e.g. "1" as a score) — use lower confidence
        conf = 0.90 if len(text) <= 2 else 0.97
        if conf < AMBIGUITY_THRESHOLD:
            # Forward to LLM
            return FilterDecision(
                element_id=element.element_id,
                is_noise=True,
                reason=FilterReason.PAGE_NUMBER,
                rule_triggered="page_number_pattern_ambiguous",
                confidence=conf,
            )
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.PAGE_NUMBER,
            rule_triggered="page_number_pattern",
            confidence=conf,
        )

    # --- 9. Standalone integer in footer position ---
    if _RE_STANDALONE_INT.match(text) and _is_footer_position(element):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=True,
            reason=FilterReason.SLIDE_NUMBER,
            rule_triggered="standalone_int_footer",
            confidence=0.88,
        )

    # --- 10. Standalone integer NOT in footer — ambiguous, keep ---
    if _RE_STANDALONE_INT.match(text):
        return FilterDecision(
            element_id=element.element_id,
            is_noise=False,
            reason=FilterReason.RETAINED,
            rule_triggered="standalone_int_ambiguous_kept",
            confidence=0.70,   # low → will trigger LLM pass
        )

    # --- 11. Everything else is retained ---
    return FilterDecision(
        element_id=element.element_id,
        is_noise=False,
        reason=FilterReason.RETAINED,
        rule_triggered="default_keep",
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_footer_position(element: RawElement) -> bool:
    """
    Heuristic: element is in the bottom 15% of a standard slide height.
    Standard slide height = 6,858,000 EMU (widescreen 16:9).
    """
    if element.y is None or element.height is None:
        return False
    SLIDE_HEIGHT_EMU = 6_858_000
    bottom_edge = element.y + element.height
    return bottom_edge > SLIDE_HEIGHT_EMU * 0.85


def _name_matches(text: str, name: str) -> bool:
    """Check if text is (approximately) equal to the given name."""
    return text.lower().strip() == name.lower().strip()
