"""Query-contract entity resolution — slice 2 of the per-turn contract.

The context filler extracts verbatim entity mentions (`QueryEntities`); this
module resolves them ONCE, deterministically, against each routed flow's valid
values, producing:

  resolved_filters  — {column: [exact stored values]}, e.g.
                      {"Country": ["United Kingdom"], "Carrier_Group": ["ZURICH GROUP"]}
  unresolved_terms  — mentions that matched nothing (surfaced, never dropped:
                      they are the "did you mean…" / zero-row-guard signal)

Every downstream consumer then works from the SAME canonical values — the
rephraser materialises them into the rephrased sentence (so the deterministic
rails' normalizer/planner see exact stored names), and the analyst's schema
identifier seeds its grounded slice with them — instead of each node
re-deriving entity resolution with its own LLM call and its own failure modes.
That per-node divergence is how "UK premium" answered yes on one turn and
"no premium in UK" on the next.

Column mapping comes from the flow registry: `entity_columns` first (declared
kind -> column), then column aliases (e.g. 'industry' -> SIC_Major_Class).
Matching is the shared `match_column_values` (exact-first, fuzzy after) — the
same matcher the MCP tools and schema identifier already use.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from core.registry import get_flow_registry
from core.schemas.routing import QueryEntities, UnresolvedTerm

# QueryEntities attribute -> the registry's entity-kind key. Years are carried
# on the contract for the timeframe slice but never value-resolved (numeric).
_KIND_BY_ATTR = {
    "carriers": "carrier",
    "countries": "country",
    "products": "product",
    "industries": "industry",
    "segments": "segment",
}

# table_family -> the flows whose valid values the mentions resolve against.
_FLOWS_BY_FAMILY = {
    "premium": ("gpr",),
    "survey": ("survey",),
    "both": ("gpr", "survey"),
}

# Max stored values kept per mention. Exact matches return one; concept terms
# ("manufacturing") legitimately fan out to several SIC classes.
_MAX_MATCHES_PER_TERM = 5

# The broker. Carrier-resolved nowhere, named freely everywhere.
_BROKER = "marsh"


def _is_measure_term(spec: Any, term: str) -> bool:
    """True when the term is a metric/measure the registry knows by name or alias.

    The context filler occasionally mis-buckets a measure word ("premium",
    "SoW", "appetite", "share of portfolio") into an ENTITY bucket
    (products/segments). Such a term is a MEASURE, not a filter value — it has
    no stored value to match, so left alone it lands in `unresolved_terms` and
    becomes a spurious "I couldn't find product 'appetite' — did you mean…?"
    clarify card. Skip it here, the same way the broker is skipped above.
    """
    needle = (term or "").strip().lower()
    if not needle:
        return False
    for metric in (getattr(spec, "metrics", None) or {}).values():
        if needle == metric.name.lower() or needle in {
            a.lower() for a in getattr(metric, "aliases", ())
        }:
            return True
    return False


def _column_for(spec: Any, kind: str) -> Optional[str]:
    """Registry column for an entity kind: declared mapping first, alias scan second."""
    column = (getattr(spec, "entity_columns", None) or {}).get(kind)
    if column:
        return column
    for col in (getattr(spec, "columns", None) or {}).values():
        if kind in {a.lower() for a in getattr(col, "aliases", ())}:
            return col.name
    return None


def resolve_entities(
    entities: QueryEntities,
    table_family: str,
    *,
    matcher: Optional[Callable[[str, str, str], List[str]]] = None,
) -> Tuple[Dict[str, List[str]], List[UnresolvedTerm]]:
    """Resolve entity mentions to exact stored values for the routed family.

    `matcher(flow, column, term) -> [values]` defaults to the shared
    `match_column_values`; injectable for tests. Pure lookup — zero LLM calls.
    """
    if matcher is None:
        from core.mcp.tools import match_column_values  # lazy: avoids LLM-layer import

        matcher = match_column_values

    resolved: Dict[str, List[str]] = {}
    unresolved: List[UnresolvedTerm] = []
    flows = _FLOWS_BY_FAMILY.get((table_family or "").lower(), ())
    if not flows or entities is None:
        return resolved, unresolved

    registry = get_flow_registry()
    for flow in flows:
        spec = registry.get(flow)
        if spec is None:
            continue
        for attr, kind in _KIND_BY_ATTR.items():
            terms = [t.strip() for t in (getattr(entities, attr, None) or []) if t and t.strip()]
            if not terms:
                continue
            column = _column_for(spec, kind)
            if not column:
                continue
            for term in terms:
                if kind == "carrier" and term.lower() == _BROKER:
                    continue
                # A measure word mis-bucketed as an entity is not a filter value.
                if _is_measure_term(spec, term):
                    continue
                matches = matcher(flow, column, term) or []
                if matches:
                    bucket = resolved.setdefault(column, [])
                    for value in matches[:_MAX_MATCHES_PER_TERM]:
                        if value not in bucket:
                            bucket.append(value)
                else:
                    unresolved.append(
                        UnresolvedTerm(kind=kind, term=term, column=column, flow=flow)
                    )
    return resolved, unresolved


def resolved_filters_of(routing_context: Any) -> Dict[str, List[str]]:
    """The contract's resolved filters off a RoutingContext model, dict, or None."""
    if routing_context is None:
        return {}
    filters = (
        routing_context.get("resolved_filters")
        if isinstance(routing_context, dict)
        else getattr(routing_context, "resolved_filters", None)
    )
    return dict(filters) if filters else {}


def merge_resolved_values(
    base: Dict[str, List[str]], extra: Dict[str, List[str]]
) -> Dict[str, List[str]]:
    """Union two {column: [values]} maps, preserving order, base first."""
    merged: Dict[str, List[str]] = {col: list(vals) for col, vals in base.items()}
    for col, vals in (extra or {}).items():
        bucket = merged.setdefault(col, [])
        for value in vals:
            if value not in bucket:
                bucket.append(value)
    return merged
