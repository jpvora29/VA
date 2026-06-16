"""ContextEngine package (skeleton).

The centralized context assembler from the decisions doc: ONE engine, 5 typed
layers (collector -> retriever -> reranker -> compressor -> injection), producing
a typed `ContextBundle` with per-audience views. v1 adds zero extra model calls.

Step 4 lands `engine.py`, `bundle.py`, and the layer modules. Callers use
`from core.context import ContextEngine, ContextBundle`. The valid_values gate
(`gate_enabled`/`gated_valid_values`) from step 3 stays importable from here too.
"""
from __future__ import annotations

from core.context.bundle import ContextBundle
from core.context.engine import ContextEngine, engine_enabled, shadow_mode
from core.context.gate import gate_enabled, gated_valid_values
from core.context.injector import ContextInjector
from core.context.retriever import EntityResolver, ResolvedValues, semantic_enabled

__all__ = [
    "ContextBundle",
    "ContextEngine",
    "ContextInjector",
    "EntityResolver",
    "ResolvedValues",
    "engine_enabled",
    "shadow_mode",
    "semantic_enabled",
    "gate_enabled",
    "gated_valid_values",
]
