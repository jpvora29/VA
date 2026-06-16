"""Group-by dimension detection — role separation for the query contract.

"across industries", "by product", "per region" name a GROUPING axis, not a
filter value. The contract used to resolve every entity mention as a filter, so
a grouping word could be matched to a stored value and injected as a spurious
WHERE clause (and, with semantic resolution on, "industries" would map onto SIC
classes outright). This detector reads the grammatical signal deterministically
— the same posture as the output-directive detector — and hands the contract:

  - which COLUMNS the query groups across  (-> QueryIntent.group_by), and
  - which dimension NOUNS it consumed       (-> the resolver skips them as filters).

A column may be BOTH a group-by and a filter ("across industries, focus on
manufacturing"): only the bare category noun ("industries") is suppressed; a
specific value ("manufacturing") still resolves.

Noun -> column mapping is registry-driven (column name words + the column's
declared aliases), with a small synonym overlay for grouping words the registry
does not carry ("sector", "vertical", "market"). Bare "for" is deliberately NOT
a grouping preposition — only "for each / for every" group; "for manufacturing"
is a filter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Set

from core.registry import get_flow_registry

# table_family -> flows whose columns define the groupable dimensions. Mirrors
# the contract's `_FLOWS_BY_FAMILY` (kept local — SRP, no cross-import).
_FLOWS_BY_FAMILY = {
    "premium": ("gpr",),
    "survey": ("survey",),
    "both": ("gpr", "survey"),
}

# Grouping synonyms the registry aliases don't carry, keyed by a noun that IS a
# known column alias/name so they attach to whichever column owns that alias.
_NOUN_SYNONYMS = {
    "industry": ("sector", "vertical"),
    "country": ("market", "geography"),
    "product": ("line of business", "lob"),
    "carrier": ("insurer", "competitor"),
}

# Prepositions that introduce a grouping axis. Bare "for" is excluded.
_PREP = (
    r"(?:across|by|per|amongst|among|for\s+each|for\s+every|"
    r"grouped?\s+by|split\s+by|broken\s+down\s+by|breakdown\s+by)"
)


@dataclass(frozen=True)
class GroupBy:
    """The grouping axes detected in a turn, plus the nouns consumed for them."""

    columns: List[str] = field(default_factory=list)
    dimension_terms: Set[str] = field(default_factory=set)


def _variants(noun: str) -> Set[str]:
    """Singular/plural surface forms of a dimension noun ("industry"/"industries")."""
    n = noun.strip().lower()
    if not n:
        return set()
    forms = {n}
    # singular
    if n.endswith("ies"):
        forms.add(n[:-3] + "y")
    elif n.endswith("s") and not n.endswith("ss"):
        forms.add(n[:-1])
    # plural
    if n.endswith("y"):
        forms.add(n[:-1] + "ies")
    elif not n.endswith("s"):
        forms.add(n + "s")
    return {f for f in forms if f}


def _noun_to_column(spec) -> Dict[str, str]:
    """Map every groupable dimension noun (+ variants) to its column."""
    mapping: Dict[str, str] = {}
    for col in (getattr(spec, "columns", None) or {}).values():
        if getattr(col, "role", "") != "entity":
            continue
        nouns = {col.name.replace("_", " ").lower()}
        nouns.update(a.lower() for a in (getattr(col, "aliases", ()) or ()))
        for base in list(nouns):
            nouns.update(_NOUN_SYNONYMS.get(base, ()))
        for noun in nouns:
            for variant in _variants(noun):
                mapping.setdefault(variant, col.name)
    return mapping


def _grouped_on(text: str, noun: str) -> bool:
    """True when `text` groups on `noun` (a grouping preposition precedes it)."""
    pattern = re.compile(
        rf"\b{_PREP}\s+(?:the\s+|each\s+|every\s+|all\s+|a\s+)?{re.escape(noun)}\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def detect_group_by(query: str, table_family: str) -> GroupBy:
    """Detect the GROUP BY axes named in `query` for the routed family.

    Deterministic, zero model calls. Returns the columns to group across and the
    dimension nouns consumed (so the contract resolver can skip them as filters).
    """
    text = query or ""
    if not text.strip():
        return GroupBy()

    registry = get_flow_registry()
    noun_to_col: Dict[str, str] = {}
    for flow in _FLOWS_BY_FAMILY.get((table_family or "").lower(), ()):
        spec = registry.get(flow)
        if spec is not None:
            noun_to_col.update(_noun_to_column(spec))

    columns: List[str] = []
    terms: Set[str] = set()
    for noun, column in noun_to_col.items():
        if _grouped_on(text, noun):
            if column not in columns:
                columns.append(column)
            terms.update(_variants(noun))
    return GroupBy(columns=columns, dimension_terms=terms)
