"""Central flow registry — declarative per-dataset metadata.

See `core/registry/flows.yaml` for data and `spec.py` / `loader.py` for the
typed access layer. `get_flow_registry()` is the process-wide singleton.
"""
from __future__ import annotations

from core.registry.loader import FlowRegistry, get_flow_registry
from core.registry.spec import ColumnSpec, FlowSpec, MetricSpec

__all__ = [
    "FlowRegistry",
    "get_flow_registry",
    "FlowSpec",
    "ColumnSpec",
    "MetricSpec",
]
