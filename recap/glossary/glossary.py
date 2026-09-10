"""
glossary/glossary.py

Stage 4 — Business Glossary.

Loads a company-provided glossary from a JSON or YAML file and provides
dynamic term retrieval: given a content unit's text, return only the
glossary definitions that are relevant to that specific unit.

This avoids passing the entire glossary to every LLM call while ensuring
the LLM has the definitions it needs for accurate interpretation.

Glossary file format (JSON)
---------------------------
{
  "terms": [
    {
      "term": "Share of Wallet",
      "aliases": ["SoW", "wallet share"],
      "definition": "The percentage of a client's total insurance spend ...",
      "category": "metric",
      "lob": ["All"],
      "notes": "Internal company definition — differs from generic usage."
    },
    ...
  ]
}

YAML format is also supported (same structure, .yaml / .yml extension).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class GlossaryTerm:
    """Represents one entry in the business glossary."""

    def __init__(
        self,
        term: str,
        definition: str,
        aliases: Optional[List[str]] = None,
        category: Optional[str] = None,
        lob: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> None:
        self.term = term
        self.definition = definition
        self.aliases: List[str] = aliases or []
        self.category = category
        self.lob: List[str] = lob or []
        self.notes = notes

        # Pre-compile search patterns for all variants
        variants = [re.escape(term)] + [re.escape(a) for a in self.aliases]
        self._pattern = re.compile(
            r"\b(?:" + "|".join(variants) + r")\b",
            re.IGNORECASE,
        )

    def matches(self, text: str) -> bool:
        """Return True if this term (or an alias) appears in the text."""
        return bool(self._pattern.search(text))

    def to_prompt_block(self) -> str:
        """Formatted definition block for injection into LLM prompts."""
        parts = [f"**{self.term}**: {self.definition}"]
        if self.aliases:
            parts.append(f"  Aliases: {', '.join(self.aliases)}")
        if self.notes:
            parts.append(f"  Note: {self.notes}")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return f"GlossaryTerm(term={self.term!r}, category={self.category!r})"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class BusinessGlossary:
    """
    Loads and provides dynamic retrieval of company-specific business terms.

    Usage
    -----
    glossary = BusinessGlossary.from_file("glossary.json")

    # Get definitions relevant to a piece of text
    relevant = glossary.retrieve(text="Share of Wallet increased from 18% to 23%")
    prompt_block = glossary.to_prompt_block(relevant)
    """

    def __init__(self, terms: Optional[List[GlossaryTerm]] = None) -> None:
        self._terms: List[GlossaryTerm] = terms or []
        self._term_index: Dict[str, GlossaryTerm] = {
            t.term.lower(): t for t in self._terms
        }
        logger.info("Glossary loaded: %d terms", len(self._terms))

    # ----------------------------------------------------------------
    # Loading
    # ----------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> "BusinessGlossary":
        """Load glossary from a JSON or YAML file."""
        path = Path(path)
        if not path.exists():
            logger.warning("Glossary file not found: %s — using empty glossary", path)
            return cls()

        try:
            if path.suffix in (".yaml", ".yml"):
                import yaml  # optional dependency
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            else:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as exc:
            logger.error("Failed to load glossary from %s: %s", path, exc)
            return cls()

        terms = cls._parse_terms(data)
        return cls(terms)

    @classmethod
    def from_dict(cls, data: dict) -> "BusinessGlossary":
        """Load glossary from an already-parsed dict."""
        return cls(cls._parse_terms(data))

    @staticmethod
    def _parse_terms(data: dict) -> List[GlossaryTerm]:
        raw_terms = data.get("terms", [])
        terms: List[GlossaryTerm] = []
        for entry in raw_terms:
            term = entry.get("term", "").strip()
            definition = entry.get("definition", "").strip()
            if not term or not definition:
                continue
            terms.append(
                GlossaryTerm(
                    term=term,
                    definition=definition,
                    aliases=entry.get("aliases", []),
                    category=entry.get("category"),
                    lob=entry.get("lob", []),
                    notes=entry.get("notes"),
                )
            )
        return terms

    # ----------------------------------------------------------------
    # Retrieval
    # ----------------------------------------------------------------

    def retrieve(
        self,
        text: str,
        max_terms: int = 10,
    ) -> List[GlossaryTerm]:
        """
        Return the subset of glossary terms that match the given text.

        Parameters
        ----------
        text      : The content unit text (and optionally slide title/context).
        max_terms : Cap on how many terms to return (avoids bloating prompts).

        Returns
        -------
        List of matching GlossaryTerm objects, in definition order.
        """
        if not text:
            return []
        matched = [t for t in self._terms if t.matches(text)]
        return matched[:max_terms]

    def retrieve_for_context(
        self,
        content: str,
        slide_title: Optional[str] = None,
        section: Optional[str] = None,
        max_terms: int = 10,
    ) -> List[GlossaryTerm]:
        """
        Retrieve terms matching content, slide title, and section combined.
        Provides broader context for ambiguous KPIs.
        """
        combined = " ".join(filter(None, [content, slide_title, section]))
        return self.retrieve(combined, max_terms=max_terms)

    def get_term(self, term_name: str) -> Optional[GlossaryTerm]:
        """Look up a specific term by name (case-insensitive)."""
        return self._term_index.get(term_name.lower())

    # ----------------------------------------------------------------
    # Prompt construction
    # ----------------------------------------------------------------

    @staticmethod
    def to_prompt_block(terms: List[GlossaryTerm]) -> str:
        """
        Convert a list of terms into a formatted block for LLM injection.
        Returns a placeholder string if no terms matched.
        """
        if not terms:
            return "(No company-specific glossary terms matched this content.)"
        lines = ["Company glossary definitions for this content:"]
        for t in terms:
            lines.append(t.to_prompt_block())
        return "\n\n".join(lines)

    def matched_term_names(self, text: str) -> List[str]:
        """Return just the term names that match, for metadata tracking."""
        return [t.term for t in self.retrieve(text)]

    # ----------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._terms)

    def __repr__(self) -> str:
        return f"BusinessGlossary(terms={self.size})"
