"""ContextEngine package (skeleton).

The centralized context assembler from the decisions doc: ONE engine, 5 typed
layers (collector -> retriever -> reranker -> compressor -> injection), producing
a typed `ContextBundle` with per-audience views. v1 adds zero extra model calls.

Step 0 lands the package only; `engine.py`, `bundle.py`, and the layer modules
arrive in steps 3-4. Imports are added here as those modules land so callers use
`from core.context import ContextEngine, ContextBundle`.
"""
from __future__ import annotations

__all__: list[str] = []
