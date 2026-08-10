"""Role → value resolution — fill the vocabulary from real analytics.

Pure orchestration over the existing deterministic compute layer (``studio.compute``
+ ``studio.page.format``) — no new analytics and no LLM numbers. Produces a flat
``dict[role -> rendered string]`` (plus a ``growth_bubble`` structured payload for the
scatter/bubble chart). Roles it cannot resolve are simply absent, so the fill engine
leaves their slots as the template's placeholder. Keyed by the role vocabulary in
``roles.py`` — entirely independent of any particular template.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from logger import get_logger
from studio import compute as C

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_PRODUCT_COL = "Product_Line"
_YEAR_COL = "Year"


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 — a failing metric must not break the fill
        logger.warning("bindings: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def _latest_year_in_scope(result, base: Dict[str, Any]) -> Optional[int]:
    """The most recent Year present for ``base`` — the reporting year to fall back on.

    The corner KPIs (Marsh/Carrier GWP, rank, SoW) are period comparisons that need a
    reference year. When the user pins no year we still want the values to populate, so
    we resolve the latest year available in scope and report on that.
    """
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    facts = _safe(
        compute_breakdown,
        PrimitiveArgs(flow=result.flow, metric="premium", group_by=(_YEAR_COL,), filters=base),
        engine=result.engine,
    ) or []
    years = [int(f.dims.get(_YEAR_COL)) for f in facts
             if str(f.dims.get(_YEAR_COL) or "").strip().isdigit()]
    return max(years) if years else None


def reporting_filters(result, *, drop: Iterable[str] = ()) -> Dict[str, Any]:
    """``result``'s filters with the reporting year pinned — what every page reports on.

    The deterministic compute layer is year-anchored: ``compute.period_totals``,
    ``rank_movement``, ``sow_movement``, ``peer_average_totals`` and
    ``product_breakdown_rows`` all need a reference year to know what "current" and "prior"
    mean, and return nothing (or silently sum EVERY year into one current value) without
    one. So a run that leaves the year filter on "All" must still resolve a year: the max of
    a multi-select pin, else the latest year present in scope.

    ``drop`` removes columns the page must not be narrowed by — e.g. a portfolio page that
    ranks lines of business against each other drops the product pin, or it would have a
    single line to rank.
    """
    dropped = set(drop)
    f = {k: v for k, v in (getattr(result, "resolved_filters", None) or {}).items()
         if k not in dropped}
    year = f.get(_YEAR_COL)
    if isinstance(year, (list, tuple, set)):
        year = max(int(y) for y in year) if year else None
    if year is None:
        year = _latest_year_in_scope(result, {k: v for k, v in f.items() if k != _YEAR_COL})
    if year is not None:
        f[_YEAR_COL] = int(year)
    return f


def _country_breakdown(result) -> List[Dict[str, Any]]:
    """Subject's premium by country, biggest first — feeds the Country (n) labels."""
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    facts = _safe(
        compute_breakdown,
        PrimitiveArgs(flow=result.flow, metric="premium", group_by=(_COUNTRY_COL,),
                      filters=result.resolved_filters),
        engine=result.engine,
    ) or []
    rows = [{"name": str(f.dims.get(_COUNTRY_COL)), "premium": f.value} for f in facts]
    rows.sort(key=lambda r: r["premium"] or 0.0, reverse=True)
    return rows


def _spotlight(result, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The single entity to feature in the "… Country xyz YoY change" highlights.

    Significance = largest current premium in scope. When several countries are in scope the
    spotlight is the top COUNTRY; when exactly one country is in scope the country dimension is
    fixed, so we drill down and spotlight the top PRODUCT instead. Returns the entity name plus
    its carrier and Marsh YoY (both scoped to that entity), or ``None`` if it can't resolve.

    ``filters`` must carry the REPORTING YEAR (:func:`reporting_filters`): both YoY numbers
    are period comparisons, and ``period_totals`` returns nothing at all without a year — so
    passing the raw selection left the two callouts on their ``+xx.x%`` placeholder whenever
    the user had not pinned a year.
    """
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    f = filters
    pinned = f.get(_COUNTRY_COL)
    n_countries = len(set(pinned)) if isinstance(pinned, (list, tuple, set)) else (1 if pinned else 0)
    dim = _PRODUCT_COL if n_countries == 1 else _COUNTRY_COL

    facts = _safe(
        compute_breakdown,
        PrimitiveArgs(flow=result.flow, metric="premium", group_by=(dim,), filters=f),
        engine=result.engine,
    ) or []
    facts = [x for x in facts if x.dims.get(dim) is not None]
    if not facts:
        return None
    top = str(max(facts, key=lambda x: x.value or 0.0).dims.get(dim))

    scoped = {**f, dim: top}
    carrier = _safe(C.period_totals, result.flow, scoped, result.engine) or {}
    marsh = _safe(C.period_totals, result.flow,
                  {k: v for k, v in scoped.items() if k != _CARRIER_COL}, result.engine) or {}
    return {"name": top, "carrier_yoy": carrier.get("pct"), "marsh_yoy": marsh.get("pct")}


def _growth_bubble(result, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Per-LoB carrier-vs-Marsh YoY growth (+ bubble size) for the growth-rate chart.

    ``filters`` must carry the REPORTING YEAR (:func:`reporting_filters`): both axes are
    period comparisons, and ``movement_by_dim`` returns nothing at all without a year — so
    reading the raw selection left every unpinned-year run with an empty payload, and the
    chart kept the template's own example bubbles under the carrier's name.

    Only the lines of business in scope are plotted: the filters carry the user's product
    selection, so a run pinned to two lines shows those two.

    ALWAYS returns a payload, even with no points — that is what tells the fill engine the
    chart was considered and must be cleared rather than left showing authored examples.
    """
    base = {k: v for k, v in filters.items() if k != _CARRIER_COL}
    carrier_moves = _safe(C.movement_by_dim, result.flow, _PRODUCT_COL, filters,
                          result.engine, top=12) or []
    marsh_moves = _safe(C.movement_by_dim, result.flow, _PRODUCT_COL, base,
                        result.engine, top=99) or []
    marsh_by = {m["name"]: m for m in marsh_moves}
    points = []
    for cm in carrier_moves:
        mm = marsh_by.get(cm["name"])
        points.append({
            "lob": cm["name"],
            "carrier_yoy": cm.get("pct"),
            "marsh_yoy": (mm.get("pct") if mm else None),
            "size": cm.get("current") or 0.0,
        })
    return {"points": points}


def resolve_roles(result) -> Dict[str, Any]:
    """Map the role vocabulary to values from ``result``.

    Numeric roles return RAW numbers; the slot's own placeholder token decides the
    final format (``template_fill.render.render_token``) so each value matches the
    box it lands in. Text/structured roles (names, the growth bubble) stay as-is.
    """
    out: Dict[str, Any] = {}
    subject = result.subject

    if subject:
        out["subject_name"] = str(subject)

    # Every value below is a period comparison, so they all report on the SAME resolved
    # reporting year — the pinned year, else the latest in scope.
    fy = reporting_filters(result)
    year = fy.get(_YEAR_COL)
    if year is not None:
        out["period_year"] = int(year)

    # Carrier (subject) total + YoY, and the whole Marsh book total + YoY (raw).
    carrier_tot = _safe(C.period_totals, result.flow, fy, result.engine)
    if carrier_tot:
        out["carrier_gwp"] = carrier_tot["current"]
        if carrier_tot.get("pct") is not None:
            out["carrier_gwp_yoy"] = carrier_tot["pct"]

    base = {k: v for k, v in fy.items() if k != _CARRIER_COL}
    marsh_tot = _safe(C.period_totals, result.flow, base, result.engine)
    if marsh_tot:
        out["marsh_gwp"] = marsh_tot["current"]
        if marsh_tot.get("pct") is not None:
            out["marsh_gwp_yoy"] = marsh_tot["pct"]

    # Share of wallet (current + YoY delta).
    sow = _safe(C.sow_movement, result.flow, fy, result.engine, subject)
    if sow:
        out["sow_pct"] = sow["current"]
        if sow.get("delta") is not None:
            out["sow_yoy"] = sow["delta"]

    # Market rank (current + improvement).
    rankm = _safe(C.rank_movement, result.flow, fy, result.engine, subject)
    if rankm:
        out["rank"] = int(rankm["current"])
        if rankm.get("delta") is not None:
            out["rank_yoy"] = int(rankm["delta"])

    # NOTE: the overall survey-score tile is NOT resolved here — it is sourced from the
    # survey book and gated on the run's data basis, so it belongs to the module that owns
    # the tile (:mod:`studio.template_fill.survey.kpi`).

    # Confidential peer benchmark: the top-5 carriers' AVERAGE premium and share of wallet.
    # Never a named competitor — the templates head these "Peer GWP" / "Peer SoW".
    peer = _safe(C.peer_average_totals, result.flow, fy, result.engine) or {}
    for role, key in (("peer_gwp", "current"), ("peer_gwp_yoy", "pct"),
                      ("peer_sow", "sow"), ("peer_sow_yoy", "sow_delta")):
        if peer.get(key) is not None:
            out[role] = peer[key]

    # Country labels (positional).
    for i, row in enumerate(_country_breakdown(result)):
        out[f"country_name[{i}]"] = row["name"]

    # Spotlight YoY (a significant single country, or a product when one country is in scope)
    # for the "… Country xyz YoY change" highlights — distinct from the blended overall YoY.
    spot = _spotlight(result, fy)
    if spot:
        out["spotlight_name"] = spot["name"]
        if spot.get("carrier_yoy") is not None:
            out["spotlight_carrier_yoy"] = spot["carrier_yoy"]
        if spot.get("marsh_yoy") is not None:
            out["spotlight_marsh_yoy"] = spot["marsh_yoy"]

    # Reports on the same resolved year as everything above it, and on the same product
    # scope — so the growth quadrant answers the selection the deck was asked for.
    out["growth_bubble"] = _growth_bubble(result, fy)

    return out


# ── per-entity resolution (split-template model) ─────────────────────────────
# The split templates fill one sub-deck per selected product / country. Each sub-deck
# wants the SAME role vocabulary as ``overall``, but computed for a single entity — so
# we re-scope the result's filters to that one value and reuse ``resolve_roles`` wholesale
# (no new analytics; the deterministic compute layer does the slicing via its filters).


def _selected(result, column: str) -> Tuple[Any, ...]:
    """The values pinned for ``column`` as a tuple (``()`` when unfiltered → caller decides)."""
    val = (getattr(result, "resolved_filters", None) or {}).get(column)
    if val is None:
        return ()
    return tuple(val) if isinstance(val, (list, tuple, set)) else (val,)


def selected_products(result) -> Tuple[Any, ...]:
    """Product-lines the user pinned (drives how many product sub-decks to build)."""
    return _selected(result, _PRODUCT_COL)


def selected_countries(result) -> Tuple[Any, ...]:
    """Countries the user pinned (drives how many country sub-decks to build)."""
    return _selected(result, _COUNTRY_COL)


def carrier_countries(result) -> Tuple[str, ...]:
    """Every country the carrier writes in, biggest premium first.

    The fallback set of country sub-decks when the user pins no country — same ordering as
    the ``country_name[i]`` labels.
    """
    return tuple(row["name"] for row in _country_breakdown(result) if row.get("name"))


def _rescope(result, column: str, value: Any):
    """A shallow copy of ``result`` with ``column`` pinned to a single ``value``."""
    filters = {**(getattr(result, "resolved_filters", None) or {}), column: value}
    return replace(result, resolved_filters=filters)


def scope_to_product(result, product: Any):
    """``result`` re-scoped to a single product line (for a ``product`` sub-deck)."""
    return _rescope(result, _PRODUCT_COL, product)


def scope_to_country(result, country: Any):
    """``result`` re-scoped to a single country (for a ``country`` sub-deck)."""
    return _rescope(result, _COUNTRY_COL, country)


def resolve_roles_for_product(result, product: Any) -> Dict[str, Any]:
    """Role → value map scoped to a single product line (for one ``product`` sub-deck).

    Adds ``product_name`` so the fill engine can rewrite the template's authored example
    product word (e.g. "Marine Feedback") to the product this deck is actually about.
    """
    out = resolve_roles(scope_to_product(result, product))
    out["product_name"] = str(product)
    return out


def resolve_roles_for_country(result, country: Any) -> Dict[str, Any]:
    """Role → value map scoped to a single country (for one ``country`` sub-deck)."""
    return resolve_roles(scope_to_country(result, country))


def carrier_vocab(result) -> Tuple[str, ...]:
    """Every carrier name in scope — the words a deck may need rewritten to its subject.

    Templates are authored with an example carrier baked into row labels ("QBE GWP rank",
    "QBE GWP Share %"). Rewriting those to the deck's subject keeps the label honest AND
    upholds the no-named-peer rule: no other carrier's name may survive into carrier-facing
    output. Ignores the pinned ``Carrier_Group`` filter so the full vocabulary is returned.
    """
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    base = {k: v for k, v in (getattr(result, "resolved_filters", None) or {}).items()
            if k != _CARRIER_COL}
    facts = _safe(
        compute_breakdown,
        PrimitiveArgs(flow=result.flow, metric="premium", group_by=(_CARRIER_COL,), filters=base),
        engine=result.engine,
    ) or []
    return tuple(str(f.dims.get(_CARRIER_COL)) for f in facts if f.dims.get(_CARRIER_COL))


def product_vocab(result) -> Tuple[str, ...]:
    """Every product-line value in scope — the words a product deck may need rewritten.

    The product templates are authored with example products ("Marine" on the feedback
    slides, "Energy" on the ranking slide); a per-product deck rewrites all of them to the
    one product it is for. Ignores the pinned ``Product_Line`` filter so the full vocabulary
    is returned regardless of selection.
    """
    from core.analytics.library import compute_breakdown
    from core.analytics.types import PrimitiveArgs

    base = {k: v for k, v in (getattr(result, "resolved_filters", None) or {}).items()
            if k != _PRODUCT_COL}
    facts = _safe(
        compute_breakdown,
        PrimitiveArgs(flow=result.flow, metric="premium", group_by=(_PRODUCT_COL,), filters=base),
        engine=result.engine,
    ) or []
    return tuple(str(f.dims.get(_PRODUCT_COL)) for f in facts if f.dims.get(_PRODUCT_COL))
