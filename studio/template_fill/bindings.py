"""Role → value resolution — fill the vocabulary from real analytics.

Pure orchestration over the existing deterministic compute layer (``studio.compute``
+ ``studio.page.format``) — no new analytics and no LLM numbers. Produces a flat
``dict[role -> rendered string]`` (plus a ``growth_bubble`` structured payload for the
scatter/bubble chart). Roles it cannot resolve are simply absent, so the fill engine
leaves their slots as the template's placeholder. Keyed by the role vocabulary in
``roles.py`` — entirely independent of any particular template.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from logger import get_logger
from studio import compute as C

logger = get_logger(__name__)

_CARRIER_COL = "Carrier_Group"
_COUNTRY_COL = "Country"
_YEAR_COL = "Year"


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 — a failing metric must not break the fill
        logger.warning("bindings: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


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


def _growth_bubble(result) -> Optional[Dict[str, Any]]:
    """Per-LoB carrier-vs-Marsh YoY growth (+ bubble size) for the growth-rate chart."""
    f = result.resolved_filters
    base = {k: v for k, v in f.items() if k != _CARRIER_COL}
    carrier_moves = _safe(C.movement_by_dim, result.flow, "Product_Line", f, result.engine, top=12) or []
    marsh_moves = _safe(C.movement_by_dim, result.flow, "Product_Line", base, result.engine, top=99) or []
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
    return {"points": points} if points else None


def resolve_roles(result) -> Dict[str, Any]:
    """Map the role vocabulary to values from ``result``.

    Numeric roles return RAW numbers; the slot's own placeholder token decides the
    final format (``template_fill.render.render_token``) so each value matches the
    box it lands in. Text/structured roles (names, the growth bubble) stay as-is.
    """
    out: Dict[str, Any] = {}
    f = result.resolved_filters
    subject = result.subject

    if subject:
        out["subject_name"] = str(subject)

    year = f.get(_YEAR_COL)
    if isinstance(year, (list, tuple, set)):
        year = max(int(y) for y in year) if year else None
    if year is not None:
        out["period_year"] = int(year)

    # Carrier (subject) total + YoY, and the whole Marsh book total + YoY (raw).
    carrier_tot = _safe(C.period_totals, result.flow, f, result.engine)
    if carrier_tot:
        out["carrier_gwp"] = carrier_tot["current"]
        if carrier_tot.get("pct") is not None:
            out["carrier_gwp_yoy"] = carrier_tot["pct"]

    base = {k: v for k, v in f.items() if k != _CARRIER_COL}
    marsh_tot = _safe(C.period_totals, result.flow, base, result.engine)
    if marsh_tot:
        out["marsh_gwp"] = marsh_tot["current"]
        if marsh_tot.get("pct") is not None:
            out["marsh_gwp_yoy"] = marsh_tot["pct"]

    # Share of wallet (current + YoY delta).
    sow = _safe(C.sow_movement, result.flow, f, result.engine, subject)
    if sow:
        out["sow_pct"] = sow["current"]
        if sow.get("delta") is not None:
            out["sow_yoy"] = sow["delta"]

    # Market rank (current + improvement).
    rankm = _safe(C.rank_movement, result.flow, f, result.engine, subject)
    if rankm:
        out["rank"] = int(rankm["current"])
        if rankm.get("delta") is not None:
            out["rank_yoy"] = int(rankm["delta"])

    # Country labels (positional).
    for i, row in enumerate(_country_breakdown(result)):
        out[f"country_name[{i}]"] = row["name"]

    bubble = _growth_bubble(result)
    if bubble:
        out["growth_bubble"] = bubble

    return out
