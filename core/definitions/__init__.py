"""ICG business definitions — what the derived numbers MEAN.

``core/data/valid_values.py`` defines columns; this defines the concepts an analyst
reasons in (share of wallet, rank, headroom, capture rate, appetite). See
``terms.yaml`` for the data and ``spec.py`` / ``loader.py`` for the typed access layer.
``get_glossary()`` is the process-wide singleton.
"""
from __future__ import annotations

from core.definitions.loader import Glossary, get_glossary, load_glossary
from core.definitions.spec import UNITS, Term

__all__ = ["Glossary", "Term", "UNITS", "get_glossary", "load_glossary"]
