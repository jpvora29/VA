"""ContextInjector — node → per-audience view (decisions doc, Phase 0 Fix 2).

This is the genuinely-named *Context Injector* from the architecture doc: the one
place that decides which `ContextBundle` view a given node receives. The old
`injection.py` (now `gate.py`) was misnamed — it is the valid-values cardinality
gate, not an injector.

`inject_for(node_name, bundle) -> view` is a single dictionary dispatch over
`_VIEW_BY_NODE` (OCP: add a node by adding a row, never an `if/elif`). This is
also the **before-model hook** the analyst/rails runtimes consume (§1, Phase 4):
each node asks the injector for its slice instead of reaching into the bundle.

The dispatch table is injectable (DI) so a runtime can register extra node views
without editing this module.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from core.context.bundle import ContextBundle

# node name -> the bundle view it is allowed to see. The single source of truth
# for the node→view mapping (replaces per-caller `bundle.for_x()` choices).
NodeView = Callable[[ContextBundle], Any]

_VIEW_BY_NODE: Dict[str, NodeView] = {
    "router": ContextBundle.for_routing,
    "planner": ContextBundle.for_planner,
    "sql": ContextBundle.for_sql,
    "solver": ContextBundle.for_solver,
    "response": ContextBundle.for_response,
}


class ContextInjector:
    """Injects the right per-audience view into each node's prompt.

    The view map is injected (defaults to the production `_VIEW_BY_NODE`) so tests
    and alternate runtimes can supply their own node→view table.
    """

    def __init__(self, *, view_by_node: Dict[str, NodeView] = _VIEW_BY_NODE) -> None:
        self._view_by_node = dict(view_by_node)

    def supports(self, node_name: str) -> bool:
        """True when this injector knows how to slice the bundle for `node_name`."""
        return node_name in self._view_by_node

    def inject_for(self, node_name: str, bundle: ContextBundle) -> Any:
        """Return the bundle view `node_name` is entitled to see.

        Raises `KeyError` for an unregistered node — a missing mapping is a wiring
        bug, not something to paper over with a silent default.
        """
        try:
            view = self._view_by_node[node_name]
        except KeyError:
            raise KeyError(
                f"No context view registered for node {node_name!r}; "
                f"known nodes: {sorted(self._view_by_node)}"
            ) from None
        return view(bundle)
