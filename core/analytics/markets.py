"""Two scope decisions the position table depends on, made explicitly.

**Who the table is about.** The table only carries carrier columns (carrier
premium, share of wallet, share of portfolio, rank) when it has ONE subject
carrier. It used to take the carrier filter only when it held exactly one value,
so "How is Generali performing…" — where the name matched two stored spellings,
or was only mentioned and never resolved into a filter — silently fell back to
the MARKET table: Marsh premium and nothing about Generali.

**Which markets it covers.** A question naming three countries was answered with
one table summing all three, which is a number nobody asked for. Each country
now gets its own scope, and the caller builds one table per market.

Pure functions over dicts, with the value matcher injected, so both decisions
are testable without a warehouse.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

#: More markets than this in one answer is a ranking, not a set of positions.
MAX_MARKETS = 4

Matcher = Callable[[str, str, str], List[str]]


def entity_column(flow: str, entity: str) -> Optional[str]:
    """The column a flow stores an entity in ("carrier" -> "Carrier_Group")."""
    from core.registry import get_flow_registry

    spec = get_flow_registry().get(flow)
    return (getattr(spec, "entity_columns", {}) or {}).get(entity) if spec else None


def values_of(scope: Mapping[str, Any], column: Optional[str]) -> List[str]:
    """A filter's values as a list of non-empty strings."""
    if not column:
        return []
    value = scope.get(column)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)] if str(value).strip() else []


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def best_match(candidates: Sequence[str], mentions: Sequence[str]) -> str:
    """The candidate the user most plausibly meant.

    Prefers a candidate containing a mention as a whole word, then the shortest
    (the group name over a subsidiary: "GENERALI" over "GENERALI GLOBAL
    CORPORATE"), and is stable otherwise.
    """
    if not candidates:
        return ""
    said = [_norm(m) for m in mentions if _norm(m)]

    def score(value: str) -> Tuple[int, int]:
        text = _norm(value)
        hit = any(re.search(r"(?<!\w)" + re.escape(m) + r"(?!\w)", text) for m in said)
        return (0 if hit else 1, len(text))

    return min(candidates, key=score)


def resolve_subject(
    scope: Mapping[str, Any],
    mentions: Sequence[str] = (),
    *,
    flow: str = "gpr",
    matcher: Optional[Matcher] = None,
) -> Tuple[str, Dict[str, Any]]:
    """(subject carrier, scope narrowed to it). ("", scope) for a market question.

    1. One carrier in the scope: that is the subject.
    2. Several: the one the user named (see `best_match`), and the scope is
       narrowed to it so the premium, the share and the rank all describe the
       same entity.
    3. None in the scope but one MENTIONED: matched against the stored values and
       added to the scope — a carrier the question names is never dropped.
    """
    out = dict(scope or {})
    column = entity_column(flow, "carrier")
    values = values_of(out, column)
    if len(values) == 1:
        return values[0], out
    if len(values) > 1:
        chosen = best_match(values, mentions)
        out[column] = chosen
        return chosen, out
    if column and mentions and matcher is not None:
        for mention in mentions:
            try:
                found = matcher(flow, column, str(mention))
            except Exception:  # noqa: BLE001 - a lookup failure keeps the market view
                found = []
            if found:
                chosen = best_match(found, [mention])
                out[column] = chosen
                return chosen, out
    return "", out


def market_scopes(
    scope: Mapping[str, Any], *, flow: str = "gpr", limit: int = MAX_MARKETS
) -> List[Tuple[str, Dict[str, Any]]]:
    """One (market name, scope) per country the scope names; one unnamed scope otherwise.

    A single country — or none — is ONE scope with an empty name, so a
    single-market question renders exactly as before.
    """
    column = entity_column(flow, "country")
    countries = values_of(scope or {}, column)
    if len(countries) < 2:
        return [("", dict(scope or {}))]
    return [(country, {**dict(scope), column: country}) for country in countries[:limit]]


def carrier_mentions(routing_context: Any) -> List[str]:
    """The carrier names the question itself used, from the context filler."""
    entities = getattr(routing_context, "entities", None)
    if entities is None and isinstance(routing_context, Mapping):
        entities = routing_context.get("entities")
    carriers = getattr(entities, "carriers", None)
    if carriers is None and isinstance(entities, Mapping):
        carriers = entities.get("carriers")
    return [str(c) for c in (carriers or []) if str(c).strip()]


def build_market_positions(
    scope: Mapping[str, Any],
    *,
    dimension: str,
    subject: str,
    flow: str = "gpr",
    engine: Any = None,
    on_error: Optional[Callable[[str, Exception], None]] = None,
    build: Optional[Callable[..., Any]] = None,
) -> List[Tuple[str, Any, Dict[str, Any]]]:
    """One (market, positioning pack, market scope) per market; empty packs dropped.

    The single place a position table is built per market, used by the graph's
    positioning node and by the offline fixture alike. `build` is the pack
    builder (injected; defaults to `build_positioning_comparison`).
    """
    if build is None:
        from core.analytics.positioning import build_positioning_comparison as build

    out: List[Tuple[str, Any, Dict[str, Any]]] = []
    for market, market_scope in market_scopes(scope, flow=flow):
        try:
            kwargs = dict(dimension=dimension, filters=market_scope, subject=subject)
            if engine is not None:
                kwargs.update(flow=flow, engine=engine)
            pack = build(**kwargs)
        except Exception as exc:  # noqa: BLE001 - one market must not sink the rest
            if on_error is not None:
                on_error(market, exc)
            continue
        if pack:
            out.append((market, pack, market_scope))
    return out
