"""Decision Board package.

A non-LLM record of the business decisions an analysis led to, read three ways:
as a status Kanban, as a flat queue, or as a dated review agenda. Decisions are
ordinary application records (see ``core.store.decisions``) kept deliberately
separate from agent/episodic memory.

Public surface:
  * agenda     — pure due-date arithmetic: states, bands, the week ribbon
  * evidence   — the snapshot a decision was taken on, captured from an answer
  * model      — status/priority/view/due colour + label metadata
  * board      — what the board shows for one set of controls
  * queue      — the agenda and list renderers, and one decision row
  * brief      — the selected decision, read beside the queue
  * render     — page shell, Kanban columns, create/edit modal
  * callbacks  — CRUD + view-router callbacks (import for side effects)
"""
from __future__ import annotations

from ui.decisions import agenda, board, brief, evidence, model, queue, render  # noqa: F401

__all__ = ["agenda", "board", "brief", "evidence", "model", "queue", "render"]
