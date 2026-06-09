"""Decision Board package.

A non-LLM Kanban of manually-authored business decisions, rendered as
colour-coded sticky cards. Decisions are ordinary application records (see
``core.store.decisions``) kept deliberately separate from agent/episodic memory.

Public surface:
  * model     — status/priority colour + label metadata
  * render    — board view, sticky cards, detail panel, create/edit modal
  * callbacks — CRUD + view-router callbacks (import for side effects)
"""
from __future__ import annotations

from ui.decisions import model, render  # noqa: F401

__all__ = ["model", "render"]
