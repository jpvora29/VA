"""GPR Industry-page cuts (v1 vertical slice).

Industry == ``SIC_Major_Class`` in the GPR flow (see ``core/registry/flows.yaml``).
Each cut is a thin recipe over the ``core/analytics`` primitive library; none of
them does any math of its own. Importing this module only *registers* the cuts.
"""
from __future__ import annotations

from typing import List

from core.analytics.library import (
    compute_breakdown,
    compute_rank,
    compute_share_of_portfolio,
    compute_share_of_wallet,
    find_whitespace,
)
from core.analytics.types import AnalyticsFact, PrimitiveArgs
from studio.cuts.catalog import CutContext, cut

_INDUSTRY = "SIC_Major_Class"
_FLOW = "gpr"


def _premium_args(ctx: CutContext) -> PrimitiveArgs:
    """Standard premium-by-industry args under the form's filters."""
    return PrimitiveArgs(
        flow=_FLOW,
        metric="premium",
        group_by=(_INDUSTRY,),
        filters=dict(ctx.filters),
    )


def _top(facts: List[AnalyticsFact], n: int) -> List[AnalyticsFact]:
    return sorted(facts, key=lambda f: f.value, reverse=True)[:n]


def _bottom(facts: List[AnalyticsFact], n: int) -> List[AnalyticsFact]:
    nonzero = [f for f in facts if f.value > 0]
    return sorted(nonzero, key=lambda f: f.value)[:n]


@cut("industry_top5", flow=_FLOW, page="industry", label="Top 5 Industries (GWP)")
def industry_top5(ctx: CutContext) -> List[AnalyticsFact]:
    return _top(compute_breakdown(_premium_args(ctx), engine=ctx.engine), 5)


@cut("industry_bottom5", flow=_FLOW, page="industry", label="Bottom 5 Industries (GWP)")
def industry_bottom5(ctx: CutContext) -> List[AnalyticsFact]:
    return _bottom(compute_breakdown(_premium_args(ctx), engine=ctx.engine), 5)


@cut(
    "industry_sop",
    flow=_FLOW,
    page="industry",
    label="Share of Portfolio (Appetite) by Industry",
    requires=("Carrier_Group",),
)
def industry_sop(ctx: CutContext) -> List[AnalyticsFact]:
    return compute_share_of_portfolio(_premium_args(ctx), engine=ctx.engine)


@cut(
    "industry_sow",
    flow=_FLOW,
    page="industry",
    label="Share of Wallet by Industry",
    requires=("Carrier_Group",),
)
def industry_sow(ctx: CutContext) -> List[AnalyticsFact]:
    return compute_share_of_wallet(_premium_args(ctx), engine=ctx.engine)


@cut(
    "industry_rank",
    flow=_FLOW,
    page="industry",
    label="Carrier Rank by Industry",
    requires=("Carrier_Group",),
)
def industry_rank(ctx: CutContext) -> List[AnalyticsFact]:
    return compute_rank(_premium_args(ctx), engine=ctx.engine)


@cut(
    "industry_whitespace",
    flow=_FLOW,
    page="industry",
    label="Whitespace Industries",
    requires=("Carrier_Group",),
    tags=("rule:whitespace",),
)
def industry_whitespace(ctx: CutContext) -> List[AnalyticsFact]:
    # ``material`` (market-GWP floor) comes from rules.yaml at orchestration time;
    # the default here keeps the cut runnable standalone. The rule engine overrides
    # it via ctx.options when wired (DESIGN.md §6).
    material = float(ctx.options.get("whitespace_material", 5_000_000))
    near_zero = float(ctx.options.get("whitespace_near_zero", 0.0))
    return find_whitespace(
        _premium_args(ctx),
        engine=ctx.engine,
        top_n=int(ctx.options.get("whitespace_top_n", 5)),
        near_zero=near_zero,
        material=material,
    )
