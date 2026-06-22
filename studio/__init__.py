"""Studio — deterministic, form-driven boardroom analysis page.

A separate (non-chatbot) surface that turns selected filters into leadership
artifacts (QBR / executive summary / recap) using **deterministic** computation.
The LLM only narrates already-computed facts; it never produces a number.

This package REUSES the deterministic engine in ``core/analytics`` and the
exporters in ``ui/boardroom`` / ``document_builder``. It is import-isolated from
the chatbot graph: nothing under ``core/graph`` or ``core/agents`` imports
``studio``. See ``studio/DESIGN.md`` for the full design and build sequence.

Layers (each its own subpackage):
  - ``cuts``  — ``@cut`` catalog + per-request scoped registry (only selected run)
  - ``facts`` — per-session fact store indexed for cross-page lookups
  - ``rules`` — declarative ``rules.yaml`` + a small deterministic rule engine
"""
from __future__ import annotations
