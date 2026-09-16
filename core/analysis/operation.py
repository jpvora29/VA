"""The analytical OPERATION a question asks for, and the sources it restricts to.

The turn contract already separates how deep an answer goes (`analysis_depth`),
how it is presented (`output_directives`) and which table family serves it
(`table_family`). The missing fourth slice is what the question asks the analyst
to DO — assess performance, explain a movement, break something down, look one
value up — because that is what decides which evidence the answer owes the
reader (`core.analysis.requirements`).

Detection is deterministic and layered exactly like `core.agents.common.directives`:
word-boundary patterns over the ORIGINAL question, checked most specific first,
with a conservative fall-back rather than a guess. There is no model call here —
an operation the patterns cannot name falls back to depth, which a model already
decided upstream.

Order matters and is the whole design. "Why did premium fall?" is a movement
explanation, not a performance assessment, even though both contain a premium
noun; "how did Zurich do?" is a performance assessment even though it names no
metric at all. Checking the specific operations before the general one is what
keeps those apart.
"""
from __future__ import annotations

import re
from typing import Sequence, Tuple

from core.analysis.requirements import GPR, SURVEY

LOOKUP = "lookup"
PENETRATION = "penetration_assessment"
PERFORMANCE = "performance_assessment"
MOVEMENT = "movement_explanation"
BREAKDOWN = "breakdown"
PERCEPTION = "perception_assessment"

# "why did it fall", "what drove the decline", "explain the drop", "reason for"
_MOVEMENT_PATTERNS = (
    re.compile(r"\bwhy\b[^.?!]{0,60}\b(?:fall|fell|drop|declin|down|up|rise|rose|grew|grow|increas|decreas|chang)", re.I),
    re.compile(r"\bwhat\s+(?:drove|caused|explains?|is\s+behind|was\s+behind)\b", re.I),
    re.compile(r"\b(?:drivers?|reasons?|causes?)\s+(?:of|for|behind)\b", re.I),
    re.compile(r"\bexplain\b[^.?!]{0,40}\b(?:chang|movement|declin|drop|growth|increase|fall)", re.I),
)

# "break it down by product", "split by industry", "across countries", "by segment"
_BREAKDOWN_PATTERNS = (
    re.compile(r"\b(?:break(?:\s|-)?down|break\s+it\s+down|split)\b", re.I),
    # Plural forms matter: "across industries" is the natural phrasing and
    # "industry" alone does not match it.
    re.compile(
        r"\b(?:by|across|per)\s+(?:each\s+|every\s+|the\s+)?"
        r"(?:products?|industr(?:y|ies)|segments?|countr(?:y|ies)|"
        r"lines?|practices?|attributes?|carriers?|quarters?|years?)\b",
        re.I,
    ),
    re.compile(r"\bcomposition\b|\bmix\b", re.I),
)

# "how did X perform", "how is X doing", "performance review", "how was 2025"
_PERFORMANCE_PATTERNS = (
    re.compile(r"\bperform(?:ance|ed|ing)?\b", re.I),
    re.compile(r"\bhow\s+(?:did|is|are|was|were|has|have)\b[^.?!]{0,60}\b(?:do|doing|done|going|fare|fared)\b", re.I),
    re.compile(r"\b(?:review|assessment|health|state)\s+of\b", re.I),
    re.compile(r"\bhow\s+(?:did|was|were)\b[^.?!]{0,40}\b(?:year|20\d\d|quarter)\b", re.I),
)

# "where is penetration possible", "headroom", "where can we grow", "whitespace"
_PENETRATION_PATTERNS = (
    re.compile(r"\bpenetrat\w*\b", re.I),
    re.compile(r"\bheadroom\b|\bwhite\s?space\b|\bunder[- ]?indexed\b", re.I),
    re.compile(r"\bwhere\s+(?:can|could|should)\b[^.?!]{0,40}\b(?:grow|win|expand|focus)\b", re.I),
    re.compile(r"\b(?:room|scope|potential)\s+to\s+grow\b", re.I),
    re.compile(r"\bwhere\s+is\b[^.?!]{0,40}\bopportunit", re.I),
)

# "what is the NPS", "survey score", "how do brokers rate them"
_PERCEPTION_PATTERNS = (
    re.compile(r"\b(?:nps|net\s+promoter)\b", re.I),
    re.compile(r"\bsurvey\b[^.?!]{0,30}\b(?:score|result|rating|movement|feedback)\b", re.I),
    re.compile(r"\bhow\s+do\s+(?:brokers?|clients?|respondents?)\s+(?:rate|see|view)\b", re.I),
    re.compile(r"\b(?:perception|satisfaction)\b", re.I),
)

# Most specific first. A question matching several operations is named by the
# first row here, which is why this is a tuple and not a dict.
_OPERATION_PATTERNS: Tuple[Tuple[str, Tuple[re.Pattern, ...]], ...] = (
    # Penetration first: "where can we grow in Property" also matches the
    # breakdown patterns, and the growth question is the one being asked.
    (PENETRATION, _PENETRATION_PATTERNS),
    (MOVEMENT, _MOVEMENT_PATTERNS),
    (PERCEPTION, _PERCEPTION_PATTERNS),
    (BREAKDOWN, _BREAKDOWN_PATTERNS),
    (PERFORMANCE, _PERFORMANCE_PATTERNS),
)

# Explicit source restrictions. These OVERRIDE the configured default, so they
# are matched strictly: a passing mention of the word "survey" is not a
# restriction, only a phrase that limits the answer to one dataset is.
_PREMIUM_ONLY = (
    re.compile(r"\b(?:premium|gpr)\s+only\b", re.I),
    re.compile(r"\bonly\s+(?:the\s+)?premium\b", re.I),
    re.compile(r"\bjust\s+(?:the\s+)?premium\b", re.I),
    re.compile(r"\b(?:no|without|skip|exclude|ignore)\s+(?:the\s+)?survey\b", re.I),
    re.compile(r"\bdon'?t\s+(?:use|include)\s+(?:the\s+)?survey\b", re.I),
)

_SURVEY_ONLY = (
    re.compile(r"\bsurvey\s+only\b", re.I),
    re.compile(r"\bonly\s+(?:the\s+)?survey\b", re.I),
    re.compile(r"\bjust\s+(?:the\s+)?survey\b", re.I),
    re.compile(r"\b(?:no|without|skip|exclude|ignore)\s+(?:the\s+)?premium\b", re.I),
)


def _matches(question: str, patterns: Sequence[re.Pattern]) -> bool:
    return any(pattern.search(question) for pattern in patterns)


def detect_operation(question: str, *, depth: str = "") -> str:
    """The analytical operation the question asks for.

    `depth` is the already-classified `analysis_depth`; it decides only the
    fall-back, so an analytical question the patterns cannot name still gets a
    performance contract rather than being demoted to a bare lookup.
    """
    text = question or ""
    for operation, patterns in _OPERATION_PATTERNS:
        if _matches(text, patterns):
            return operation
    return PERFORMANCE if depth == "analytical" else LOOKUP


def detect_source_restriction(question: str) -> Tuple[str, ...]:
    """Datasets the question explicitly limits the answer to, or () for no limit.

    Premium-only is checked first so "premium only, no survey" — which matches
    both families — resolves the way it reads rather than by pattern order
    inside one tuple.
    """
    text = question or ""
    if _matches(text, _PREMIUM_ONLY):
        return (GPR,)
    if _matches(text, _SURVEY_ONLY):
        return (SURVEY,)
    return ()
