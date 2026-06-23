"""PPT export — DeckSpec → native .pptx, optionally following a template."""
from __future__ import annotations

from studio.export.ppt import export_deck, export_document
from studio.export.template import LAYOUT_MAP, TemplateProfile

__all__ = ["export_deck", "export_document", "TemplateProfile", "LAYOUT_MAP"]
