"""NodeHooks — one before/after-model contract across both runtimes (Phase 4).

Architecture doc §1 Layer 4: every model-calling node, whichever runtime it runs
in, shares ONE hook contract:

  * ``before_model(ctx)`` — inject the right per-audience context view from the
    ContextEngine (via :class:`ContextInjector`). This is the seam Phase 0 built;
    it stays shadow until the engine is cut over, so with no bundle it is a no-op.
  * ``after_model(result, …)`` — log a trace span, run the output validator for
    the node's kind, and return the result untouched (advisory, never mutating).

Two implementations, same contract (DIP/OCP):

  * **Analyst** (LangChain ``create_agent``) keeps its ``AgentMiddleware`` — the
    ``SolverObservabilityMiddleware`` in ``core.agents.analyst.middleware`` is the
    LangChain implementation of this contract (its ``after_model`` already does
    token accounting + tracing).
  * **Rails** (DSPy + LangGraph) get the thin :func:`with_node_hooks` decorator —
    no rail rewrite: it wraps a predictor so the same before/after run around the
    existing ``forward``.

After-model validators are chosen by a dispatch dict (``_AFTER_MODEL_VALIDATORS``)
keyed by node kind — add a kind by adding a row, never an ``if/elif``. ``validate_sql``
wraps the SAME ``assert_read_only`` guard the analyst's ``run_sql`` tool already
enforces, so the check is genuinely shared, not re-implemented per runtime.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from core.context.injector import ContextInjector
from core.observability import log_event
from logger import get_logger

logger = get_logger(__name__)


# ── after-model validators (dispatch dict) ───────────────────────────────────

# An after-model validator inspects ONE model output and returns a human-readable
# error string, or None when the output is acceptable. These are advisory: the
# hook logs the result for auditing; the authoritative guard still lives on the
# execution path (e.g. the SQL execute node's EXPLAIN + fixer loop).
AfterModelValidator = Callable[[Any], Optional[str]]


def _sql_text(output: Any) -> str:
    """Pull the SQL string off a raw string or a Prediction-like result."""
    if isinstance(output, str):
        return output
    return str(getattr(output, "sql_query", "") or "")


def validate_sql(output: Any) -> Optional[str]:
    """Read-only sanity check on a generated SQL string (shared with run_sql)."""
    from core.agents.common.sql_validation import assert_read_only

    return assert_read_only(_sql_text(output))


def _chart_spec(output: Any) -> Dict[str, Any]:
    """Normalize a ChartOutput model / dict into a plain spec dict."""
    if isinstance(output, dict):
        return output
    dump = getattr(output, "model_dump", None)
    if callable(dump):
        try:
            return dump() or {}
        except Exception:  # noqa: BLE001 - defensive: any odd model shape
            return {}
    return {}


def validate_chart(output: Any) -> Optional[str]:
    """Structural check on a chart spec: a real chart needs a measure and an axis.

    Deterministic and DataFrame-free (the full role-aware repair stays in
    ``ChartSpecCritic`` at render time). Returns None for ``chart_type == 'none'``.
    """
    spec = _chart_spec(output)
    chart = str(spec.get("chart_type") or "none").strip().lower()
    if chart in ("", "none"):
        return None
    if not spec.get("y"):
        return "chart spec is missing a y (measure) field"
    if chart != "scatter" and not spec.get("x"):
        return "chart spec is missing an x field"
    return None


_AFTER_MODEL_VALIDATORS: Dict[str, AfterModelValidator] = {
    "sql": validate_sql,
    "chart": validate_chart,
}


def run_after_model_validator(kind: Optional[str], output: Any) -> Optional[str]:
    """Dispatch to the validator for ``kind``; None for an unregistered kind."""
    validator = _AFTER_MODEL_VALIDATORS.get(kind or "")
    return validator(output) if validator else None


# ── the hook contract ────────────────────────────────────────────────────────


@dataclass
class NodeContext:
    """What ``before_model`` needs to inject a node's context view.

    ``bundle`` is the ContextEngine output for the turn; it is None until the
    engine is wired in (shadow), in which case injection is skipped. ``view`` is
    set by ``before_model`` to the injected per-audience slice when available.
    """

    node: str
    flow: str = ""
    query: str = ""
    bundle: Any = None
    view: Any = None


class NodeHooks(Protocol):
    """The shared before/after-model contract (two runtime implementations)."""

    def before_model(self, ctx: NodeContext) -> NodeContext: ...

    def after_model(self, result: Any, *, node: str, kind: Optional[str] = None) -> Any: ...


class StandardNodeHooks:
    """Default hooks for the DSPy rails.

    Collaborators are injected (DI): the ``ContextInjector`` that maps a node to
    its bundle view, and the validator dispatch table. Both have production
    defaults so callers wire nothing in the common case.
    """

    def __init__(
        self,
        *,
        injector: ContextInjector | None = None,
        validators: Dict[str, AfterModelValidator] = _AFTER_MODEL_VALIDATORS,
    ) -> None:
        self._injector = injector or ContextInjector()
        self._validators = validators

    def before_model(self, ctx: NodeContext) -> NodeContext:
        """Inject the node's per-audience view when a bundle is available.

        Shadow-safe: with no bundle (the default until engine cutover) this is a
        no-op. Injection failures never propagate into model generation.
        """
        if ctx.bundle is None or not self._injector.supports(ctx.node):
            return ctx
        try:
            ctx.view = self._injector.inject_for(ctx.node, ctx.bundle)
            log_event(
                logger, "node_context_injected", logging.DEBUG, node=ctx.node, flow=ctx.flow
            )
        except Exception as exc:  # noqa: BLE001 - injection is best-effort
            log_event(
                logger,
                "node_context_inject_error",
                logging.WARNING,
                node=ctx.node,
                error=str(exc),
            )
        return ctx

    def after_model(self, result: Any, *, node: str, kind: Optional[str] = None) -> Any:
        """Trace the model step and run the kind's validator (advisory).

        Returns ``result`` unchanged — the hook observes and audits, it never
        rewrites the model output or raises into the caller.
        """
        try:
            error = run_after_model_validator(kind, result)
            log_event(
                logger,
                "node_after_model",
                logging.DEBUG,
                node=node,
                kind=kind or "",
                valid=error is None,
                validation_error=error or "",
            )
        except Exception as exc:  # noqa: BLE001 - tracing/validation must never break a turn
            log_event(
                logger, "node_after_model_error", logging.WARNING, node=node, error=str(exc)
            )
        return result


# A single shared default so rails don't each construct their own.
_DEFAULT_NODE_HOOKS = StandardNodeHooks()


def with_node_hooks(
    predictor: Callable[..., Any],
    *,
    hooks: NodeHooks = _DEFAULT_NODE_HOOKS,
    node: str,
    kind: Optional[str] = None,
    bundle_provider: Optional[Callable[[], Any]] = None,
) -> Callable[..., Any]:
    """Wrap a DSPy predictor so the NodeHooks run around its call (no rewrite).

    The returned callable runs ``before_model`` (context-injection seam), invokes
    ``predictor`` with the original args, runs ``after_model`` (trace + validate),
    and returns the predictor's result unchanged. ``bundle_provider`` lazily
    supplies the turn's ContextBundle when the engine is wired in; until then it
    is None and ``before_model`` is a no-op.
    """

    def hooked(*args: Any, **kwargs: Any) -> Any:
        hooks.before_model(
            NodeContext(node=node, bundle=bundle_provider() if bundle_provider else None)
        )
        result = predictor(*args, **kwargs)
        return hooks.after_model(result, node=node, kind=kind)

    return hooked
