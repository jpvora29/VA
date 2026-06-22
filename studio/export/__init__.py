"""PPT export — DeckSpec → native .pptx, optionally following a template."""
from __future__ import annotations

from studio.export.ppt import export_deck
from studio.export.template import LAYOUT_MAP, TemplateProfile

__all__ = ["export_deck", "TemplateProfile", "LAYOUT_MAP"]
