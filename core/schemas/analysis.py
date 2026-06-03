"""Schemas for the proactive analysis layer (lens planner).

`AnalysisPlan` is the dynamic, dependency-aware set of derived analyses the
planner selects for a query — distinct from `core.schemas.analytical.AnalyticalPlan`,
which is the single-query SQL plan the per-flow planner emits. The analyst agent
turns each `DerivedAnalysis` into one or more `execute_sql` calls following the
referenced lens, then synthesizes across them.
"""
from __future__ import annotations

from typing import List

import dspy
from pydantic import BaseModel, Field

from core.schemas.routing import RoutingContext


class DerivedAnalysis(BaseModel):
    """One analytical move the agent should perform, drawn from a lens."""

    lens: str = Field(
        description="Name of the lens this analysis applies (must be one from the catalog)."
    )
    sub_question: str = Field(
        description="Concrete, self-contained question this step answers."
    )
    depends_on: List[int] = Field(
        default_factory=list,
        description=(
            "0-based indices of earlier derived analyses whose result this step "
            "needs first (e.g. an industry breakdown depends on the step that "
            "identifies the top product). Empty when independent."
        ),
    )
    rationale: str = Field(
        default="",
        description="Why this lens adds value for the user's query.",
    )


class AnalysisPlan(BaseModel):
    """Ordered, dependency-aware set of derived analyses for one query."""

    derived: List[DerivedAnalysis] = Field(
        default_factory=list,
        description="Derived analyses to run, in dependency order.",
    )
    synthesis_focus: str = Field(
        default="",
        description=(
            "What the final synthesized answer should lead with / emphasize, "
            "grounded in the user's original intent."
        ),
    )


class AnalysisPlannerSignature(dspy.Signature):
    """
    [ROLE]
    You are the Analysis Planner for an insurance analytics system. Given a user's
    analytical query, you decide WHICH complementary analytical lenses add genuine
    value and in WHAT order to run them — you do NOT write SQL or answer the query.

    [OBJECTIVE]
    Produce an AnalysisPlan: an ordered, dependency-aware list of derived analyses.
    Each derived analysis names exactly one lens from `lens_catalog` and a concrete
    self-contained sub-question. The FIRST derived analysis must directly answer the
    user's literal question; subsequent ones add the contextual depth a good analyst
    would proactively bring (market context, peer/Marsh benchmark, trend, relevant
    breakdowns, whitespace, opportunity, contradictions).

    [SELECTION RULES]
    - Select ONLY lenses that genuinely apply to THIS query — do not run every lens.
    - Respect each lens's `applies_when`. Skip lenses whose data requirements the
      query/filters cannot satisfy.
    - Set `depends_on` when a step needs an earlier step's result (e.g. an industry
      breakdown of the "top product" depends on the step that finds the top product).
    - Follow the always-on `analyst_principles`.
    - In mode "comprehensive" (pitch reports), be thorough: include every lens the
      evidence can support. In mode "chat", be focused: 2-5 high-value lenses.
    - Never invent filters, metrics, carriers, countries, or years not present in the
      query or routing_context.
    """

    user_query: str = dspy.InputField(desc="The user's analytical question.")
    routing_context: RoutingContext = dspy.InputField(
        desc="Routing + inherited filters (carrier/country/year/metric) and intent."
    )
    lens_catalog: str = dspy.InputField(
        desc="Available lenses: name, description, and applies_when for each."
    )
    analyst_principles: str = dspy.InputField(
        desc="Always-on analytical heuristics to apply to every plan."
    )
    mode: str = dspy.InputField(desc='"chat" (focused) or "comprehensive" (pitch).')
    analysis_plan: AnalysisPlan = dspy.OutputField(
        desc="Ordered, dependency-aware derived analyses + synthesis focus."
    )
