"""Editable Boardroom builder package.

Public surface:
  * model     — document/page/widget shapes + mutation helpers
  * builder   — digest -> document, plus add page / add library widget
  * themes    — approved colour themes
  * catalog   — widget metadata + the user widget library
  * render    — render a document to Dash (view + edit mode)
  * editor    — the editor + library-picker modals (mounted once in the shell)
  * callbacks — register the edit-mode callbacks (import for side effects)
"""
from __future__ import annotations

from ui.boardroom import builder, catalog, model, themes  # noqa: F401

__all__ = ["builder", "catalog", "model", "themes"]
