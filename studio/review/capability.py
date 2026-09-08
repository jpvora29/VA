"""What the data behind THIS deck can and cannot support.

The resolver leaves a role out of ``doc["values"]`` when it cannot compute it
(:func:`studio.template_fill.bindings.resolve_roles`), which is what keeps a template
placeholder on screen instead of an invented number. That is the right behaviour and it
is also the whole problem with the old Review tab: the absence is silent.

These probes read the resolved values back and name the absence. Each one is a pure
predicate over the value map — no engine, no re-query — so the Review page costs nothing
and can never disagree with the deck it is describing.

Order matters. The probes run in dependency order and the FIRST unavailable one that
claims a role is the cause reported for it: with no peer benchmark at all, a blank
``peer_gwp_yoy`` is a peer problem, not a prior-year problem.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from studio.review import causes as K
from studio.review.model import Capability

# ── the role families each capability feeds ──────────────────────────────────

PEER_ROLES = ("peer_gwp", "peer_gwp_yoy", "peer_sow", "peer_sow_yoy")
RANK_ROLES = ("rank", "rank_yoy")
SOW_ROLES = ("sow_pct", "sow_yoy")
SURVEY_ROLES = ("survey_score",)
SPOTLIGHT_ROLES = ("spotlight_carrier_yoy", "spotlight_marsh_yoy", "spotlight_name")
CHART_ROLES = ("growth_bubble",)
YOY_ROLES = (
    "carrier_gwp_yoy", "marsh_gwp_yoy", "sow_yoy", "rank_yoy",
    "peer_gwp_yoy", "peer_sow_yoy", "spotlight_carrier_yoy", "spotlight_marsh_yoy",
)

#: Roles that are indexed positionally (``country_name[0]``) rather than named.
_COUNTRY_PREFIX = "country_name["


def _has(values: Mapping[str, Any], *roles: str) -> bool:
    return any(values.get(r) is not None for r in roles)


def _has_country_label(values: Mapping[str, Any]) -> bool:
    return any(str(k).startswith(_COUNTRY_PREFIX) for k in values)


def _has_series(values: Mapping[str, Any]) -> bool:
    payload = values.get("growth_bubble")
    points = payload.get("points") if isinstance(payload, dict) else None
    return bool(points)


def reporting_year(values: Mapping[str, Any]) -> Optional[int]:
    """The year this deck reports on, when one resolved."""
    year = values.get("period_year")
    try:
        return int(year) if year is not None else None
    except (TypeError, ValueError):
        return None


# ── the probes, in dependency order ──────────────────────────────────────────


def _year_capability(values: Mapping[str, Any]) -> Capability:
    year = reporting_year(values)
    return Capability(
        "reporting_year",
        "Reporting year",
        available=year is not None,
        detail=(f"Every figure reports on {year}." if year is not None
                else "No year could be resolved, so no period figure could be computed."),
        cause_id=K.NO_REPORTING_YEAR,
        # Without a year nothing at all resolves, so this owns every unfilled data slot
        # rather than a role family of its own — reporting a dozen separate gaps when
        # there is one would bury the fact that fixes them all.
        owns_everything=True,
    )


def _peer_capability(values: Mapping[str, Any]) -> Capability:
    ok = _has(values, "peer_gwp", "peer_sow")
    return Capability(
        "peer_benchmark", "Peer benchmark", ok,
        ("The confidential top-5 average is available for comparison boxes."
         if ok else "Fewer than five carriers remain in scope, so no peer average is published."),
        roles=PEER_ROLES, cause_id=K.NO_PEER_BENCHMARK,
    )


def _rank_capability(values: Mapping[str, Any]) -> Capability:
    ok = _has(values, "rank")
    return Capability(
        "market_rank", "Market rank", ok,
        ("The subject's place in the market resolved for this scope."
         if ok else "The subject could not be placed against the market in this scope."),
        roles=RANK_ROLES, cause_id=K.NO_MARKET_RANK,
    )


def _sow_capability(values: Mapping[str, Any]) -> Capability:
    ok = _has(values, "sow_pct")
    return Capability(
        "share_of_wallet", "Share of wallet", ok,
        ("The subject's share of the Marsh book resolved for this scope."
         if ok else "The subject's share of the Marsh book could not be computed here."),
        roles=SOW_ROLES, cause_id=K.NO_SHARE_OF_WALLET,
    )


def _survey_capability(values: Mapping[str, Any]) -> Capability:
    ok = _has(values, "survey_score")
    return Capability(
        "survey_score", "Carrier Survey score", ok,
        ("The survey book is part of this run's data basis."
         if ok else "This run is premium-only; the survey book was not included."),
        roles=SURVEY_ROLES, cause_id=K.NO_SURVEY_BOOK,
    )


def _spotlight_capability(values: Mapping[str, Any]) -> Capability:
    ok = _has(values, "spotlight_name")
    return Capability(
        "spotlight", "Featured country / product", ok,
        (f"{values.get('spotlight_name')} is featured in the 'xyz' callouts."
         if ok else "Nothing in scope to single out, so the 'xyz' callouts stay as authored."),
        roles=SPOTLIGHT_ROLES, cause_id=K.NO_SPOTLIGHT,
    )


def _country_capability(values: Mapping[str, Any]) -> Capability:
    ok = _has_country_label(values)
    return Capability(
        "country_breakdown", "Country breakdown", ok,
        ("The 'Country (n)' labels are filled biggest-first."
         if ok else "No premium by country resolved, so the numbered labels stay as authored."),
        # The roles are indexed (``country_name[2]``); ``cause_for_role`` compares the
        # base name, so one entry covers every position.
        roles=("country_name",), cause_id=K.NO_COUNTRY_BREAKDOWN,
    )


def _chart_capability(values: Mapping[str, Any]) -> Capability:
    ok = _has_series(values)
    return Capability(
        "growth_chart", "Growth quadrant", ok,
        ("The quadrant is plotted from this scope."
         if ok else "No series resolved; the chart keeps the template's authored data."),
        roles=CHART_ROLES, cause_id=K.NO_CHART_SERIES,
    )


def _prior_year_capability(values: Mapping[str, Any]) -> Capability:
    """The one the author most often needs told: is there a year to compare against?

    Available when ANY year-on-year role resolved. One is enough, and asking for all of
    them would report a prior year as missing whenever, say, the rank simply did not move
    into the data — a different fact with a different fix.
    """
    ok = _has(values, *YOY_ROLES)
    year = reporting_year(values)
    prior = f"{year - 1}" if year is not None else "the prior year"
    return Capability(
        "prior_year", "Year-on-year comparison", ok,
        (f"{prior} is in scope, so growth and movement figures filled."
         if ok else
         f"No rows for {prior} inside these filters, so every year-on-year figure — "
         "growth, movement, rank change, share change — was left as authored."),
        roles=YOY_ROLES, cause_id=K.NO_PRIOR_YEAR,
    )


#: Probes in dependency order — the root first, then the narrow families, then the
#: comparison that several of them share. See the module docstring.
_PROBES = (
    _year_capability,
    _peer_capability,
    _rank_capability,
    _sow_capability,
    _survey_capability,
    _spotlight_capability,
    _country_capability,
    _chart_capability,
    _prior_year_capability,
)


def probe(values: Mapping[str, Any]) -> Tuple[Capability, ...]:
    """Every capability of the run behind ``values``, available or not."""
    values = values or {}
    return tuple(p(values) for p in _PROBES)


def cause_for_role(role: str, capabilities: Tuple[Capability, ...]) -> str:
    """The cause id to report for a mapped role that did not fill.

    The first unavailable capability that claims the role wins, which is why the probe
    order is the dependency order: a blank peer YoY with no peer benchmark at all is a
    peer problem, and only becomes a prior-year problem once peers resolve.
    """
    base = _base_role(role)
    for cap in capabilities:
        if cap.available:
            continue
        if cap.owns_everything or base in cap.roles:
            return cap.cause_id
    return K.NO_DATA


def _base_role(role: str) -> str:
    """``country_name[2]`` → ``country_name``; anything else unchanged."""
    return str(role or "").split("[", 1)[0]


__all__ = [
    "probe", "cause_for_role", "reporting_year",
    "PEER_ROLES", "RANK_ROLES", "SOW_ROLES", "SURVEY_ROLES", "SPOTLIGHT_ROLES",
    "CHART_ROLES", "YOY_ROLES",
]
