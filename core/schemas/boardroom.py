"""Schemas for the inline Boardroom dashboard digest.

When Boardroom Mode is active for a turn, `core.agents.boardroom.boardroom_node`
runs *after* the route's insight writer and distills the already-written
commentary + SQL rows into a structured `BoardroomDigest`: a handful of KPI
cards, a one-line headline, and grouped commentary points. The UI renders that
digest as a single inline dashboard card (KPIs on top, commentary rail on the
left, charts on the right) instead of plain markdown.

The digest is *presentation* metadata — it never re-runs analysis. It only
reshapes the numbers and narrative the deterministic/analyst rails already
produced, so it cannot contradict the underlying answer.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

import dspy
from pydantic import BaseModel, Field

Tone = Literal["good", "warn", "danger", "neutral"]


class KpiCard(BaseModel):
    """A single headline metric tile."""

    label: str = Field(description="Short metric name, e.g. 'Gross Premium' or 'GPR Rank'.")
    value: str = Field(
        description="The formatted headline value exactly as it should display, e.g. '$57.6M', '#14', '7.1'."
    )
    delta: str = Field(
        default="",
        description="Short change/context note, e.g. '-9.2% YoY', '+0.3 vs prior', 'near peer avg'. Empty when there is no comparison.",
    )
    tone: Tone = Field(
        default="neutral",
        description="Sentiment of the metric from the carrier's perspective: 'good' (favourable), 'warn' (caution), 'danger' (adverse), 'neutral'.",
    )
    icon: str = Field(
        default="bi bi-graph-up",
        description="A Bootstrap-icon class that fits the metric (e.g. 'bi bi-currency-dollar', 'bi bi-trophy', 'bi bi-stars', 'bi bi-pie-chart').",
    )


class CommentarySection(BaseModel):
    """A titled cluster of commentary bullet points for the left rail."""

    heading: str = Field(description="Short section heading, e.g. 'What changed' or 'Drivers'.")
    points: List[str] = Field(
        default_factory=list,
        description="2-4 concise, board-ready bullet points. Each is a full sentence, no markdown.",
    )


class RiskItem(BaseModel):
    """A single risk/watch item rendered as a labelled severity bar."""

    label: str = Field(description="Short risk name, e.g. 'Rank decline'.")
    severity: str = Field(description="One of 'High', 'Med', 'Low'.")
    tone: Tone = Field(default="warn", description="Bar colour tone matching the severity.")


class InsightCard(BaseModel):
    """A polished, single-takeaway executive callout (not a bare metric tile)."""

    headline: str = Field(
        description="A punchy, self-contained takeaway, e.g. 'Rank dropped 4 places', "
        "'Property drives 62% of premium', 'Cyber whitespace exists'.",
    )
    detail: str = Field(
        default="",
        description="One short supporting sentence giving the so-what. May be empty.",
    )
    icon: str = Field(
        default="bi bi-lightbulb",
        description="A Bootstrap-icon class fitting the insight (e.g. 'bi bi-arrow-down-right', 'bi bi-pie-chart', 'bi bi-binoculars').",
    )
    tone: Tone = Field(
        default="neutral",
        description="Sentiment from the carrier's perspective: good/warn/danger/neutral.",
    )


class Battlecard(BaseModel):
    """An auto-generated competitive profile for one carrier."""

    carrier: str = Field(description="Carrier / carrier group name.")
    peer_position: str = Field(
        default="",
        description="One-line standing vs peers, e.g. '#14 of 18, below peer average on premium'.",
    )
    strengths: List[str] = Field(
        default_factory=list, description="1-3 grounded strengths from the analysis."
    )
    weaknesses: List[str] = Field(
        default_factory=list, description="1-3 grounded weaknesses from the analysis."
    )
    product_gaps: List[str] = Field(
        default_factory=list,
        description="0-3 lines of products/segments where the carrier is under-represented or absent (whitespace).",
    )
    broker_perception: str = Field(
        default="",
        description="One line on broker/survey perception if the analysis covers it; else empty.",
    )


class ComparisonMetric(BaseModel):
    """One metric row in a side-by-side comparison, aligned across subjects."""

    label: str = Field(description="Metric name, e.g. 'Gross Premium' or 'Rank'.")
    values: List[str] = Field(
        default_factory=list,
        description="Formatted value per subject, in the SAME order as ComparisonView.subjects.",
    )
    tones: List[Tone] = Field(
        default_factory=list,
        description="Optional sentiment tone per subject (same order/length as values). May be empty.",
    )


class ComparisonView(BaseModel):
    """A side-by-side comparison of two or more subjects (carrier vs peers, etc.)."""

    subjects: List[str] = Field(
        default_factory=list,
        description="The entities being compared, e.g. ['Zurich', 'Peer Avg', 'AXA']. 2-5 items.",
    )
    metrics: List[ComparisonMetric] = Field(
        default_factory=list,
        description="Metric rows; each carries one value per subject in subject order.",
    )
    highlight: int = Field(
        default=0,
        description="Index of the primary subject (the carrier in focus) to visually emphasise.",
    )


# ─────────── Query-dependent advanced widgets (populate only when relevant) ───────────


class TimelineEvent(BaseModel):
    """One dated movement in the carrier's history."""

    period: str = Field(description="Year or year-quarter, e.g. '2022' or '2023 Q2'.")
    title: str = Field(description="Short event title, e.g. 'Premium +12%' or 'Rank #10 → #14'.")
    detail: str = Field(default="", description="One short supporting line. May be empty.")
    category: Literal["premium", "rank", "score", "product", "other"] = Field(
        default="other", description="Which kind of movement this is."
    )
    tone: Tone = Field(default="neutral")


class MapCell(BaseModel):
    """One product×country cell in the opportunity heatmap."""

    row: str = Field(description="Product / segment label (heatmap row).")
    col: str = Field(description="Country / market label (heatmap column).")
    intensity: int = Field(
        default=0, ge=0, le=100,
        description="Whitespace/growth-priority intensity 0-100 (higher = bigger opportunity).",
    )
    tone: Tone = Field(default="neutral", description="Cell sentiment (good=priority, warn=watch).")
    note: str = Field(default="", description="Optional short hover note.")


class OpportunityMap(BaseModel):
    """A country×product whitespace / growth-priority heatmap."""

    rows: List[str] = Field(default_factory=list, description="Row labels (products/segments).")
    cols: List[str] = Field(default_factory=list, description="Column labels (countries/markets).")
    cells: List[MapCell] = Field(default_factory=list, description="Populated cells (sparse ok).")
    legend: str = Field(default="", description="Short legend, e.g. 'Darker = higher growth priority'.")


class Opportunity(BaseModel):
    """One detected whitespace where the carrier trails Marsh/peer activity."""

    area: str = Field(description="Opportunity area, e.g. 'Cyber — Canada' or 'Construction segment'.")
    dimension: Literal["product", "segment", "industry", "country", "other"] = Field(
        default="product"
    )
    carrier_level: str = Field(default="", description="The carrier's current presence/premium.")
    peer_level: str = Field(default="", description="Marsh/peer activity level for context.")
    gap_score: int = Field(
        default=0, ge=0, le=100,
        description="Size of the opportunity 0-100 (carrier low + peer/Marsh high = high).",
    )
    recommendation: str = Field(default="", description="One-line suggested move.")
    tone: Tone = Field(default="good")


class PositioningPoint(BaseModel):
    """One carrier plotted on the premium-strength vs broker-perception matrix."""

    label: str = Field(description="Carrier name.")
    premium_strength: int = Field(default=50, ge=0, le=100, description="X axis 0-100.")
    broker_perception: int = Field(default=50, ge=0, le=100, description="Y axis 0-100.")
    is_subject: bool = Field(default=False, description="True for the carrier in focus.")
    tone: Tone = Field(default="neutral")


class PositioningMatrix(BaseModel):
    """2x2: premium strength (x) vs broker perception (y)."""

    points: List[PositioningPoint] = Field(default_factory=list)
    note: str = Field(default="", description="Optional one-line read of the positioning.")


class BoardroomDigest(BaseModel):
    """Structured dashboard view of a single answer."""

    title: str = Field(description="Dashboard title — usually the carrier or subject, e.g. 'Zurich — Canada'.")
    subtitle: str = Field(
        default="",
        description="One-line context, e.g. '2024 premium performance vs peer set'.",
    )
    headline: str = Field(
        default="",
        description="A single punchy sentence stating the bottom line of the answer.",
    )
    kpis: List[KpiCard] = Field(
        default_factory=list,
        description="3-5 KPI cards covering the most decision-relevant numbers in the answer.",
    )
    insights: List[InsightCard] = Field(
        default_factory=list,
        description=(
            "2-4 polished executive insight cards — punchy, narrative takeaways (NOT bare "
            "metric tiles), e.g. 'Rank dropped 4 places', 'Property drives 62% of premium', "
            "'Cyber whitespace exists'. Distil the most board-worthy conclusions."
        ),
    )
    commentary: List[CommentarySection] = Field(
        default_factory=list,
        description="1-3 commentary sections distilled from the written analysis.",
    )
    risks: List[RiskItem] = Field(
        default_factory=list,
        description="0-4 risk/watch items if the analysis surfaces any; otherwise empty.",
    )
    comparison: Optional[ComparisonView] = Field(
        default=None,
        description=(
            "Populate ONLY when the answer compares two or more entities (e.g. carrier "
            "vs peers, multiple carriers, or the same metric across subjects) so the UI "
            "can show a side-by-side view. Leave null for single-subject answers."
        ),
    )
    battlecards: List[Battlecard] = Field(
        default_factory=list,
        description=(
            "One competitive profile per carrier discussed (the subject carrier and, when "
            "the analysis covers them, the key peers). Populate strengths/weaknesses/"
            "product_gaps/broker_perception ONLY from facts in the commentary or rows; "
            "leave a dimension empty rather than inventing. Empty list for non-carrier answers."
        ),
    )

    # ── Query-dependent advanced widgets — populate ONLY when the data supports them ──
    timeline: List[TimelineEvent] = Field(
        default_factory=list,
        description=(
            "Insight Timeline: major carrier movements across periods (premium growth, rank "
            "moves, score shifts, product changes). Populate ONLY when the answer spans "
            "multiple years/periods; else empty."
        ),
    )
    opportunity_map: Optional[OpportunityMap] = Field(
        default=None,
        description=(
            "Market Opportunity Map: a country×product whitespace/growth heatmap. Populate "
            "ONLY when the answer covers multiple countries and/or products; else null."
        ),
    )
    opportunities: List[Opportunity] = Field(
        default_factory=list,
        description=(
            "Opportunity Radar: detected whitespace where the carrier's premium is low but "
            "Marsh/peer activity is high. Populate ONLY when the data exposes such gaps; else empty."
        ),
    )
    positioning: Optional[PositioningMatrix] = Field(
        default=None,
        description=(
            "Peer Positioning Matrix (2x2: premium strength vs broker perception). Populate "
            "ONLY when BOTH premium and survey/perception signals are present for the carriers; "
            "else null."
        ),
    )


# ─────────── Staged digest generation ───────────
#
# One giant generation reliably under-fills a ~12-section optional schema — the
# model satisfices on the first fields and leaves the widget tail null even when
# the data supports it. The digest is therefore generated in stages:
#   1. `BoardroomCoreSignature`  -> the always-on heart (title/headline/KPIs/
#      insights/commentary/risks) — one focused call.
#   2. Deterministic signal detection over the RAW rows decides which widgets
#      the data actually supports (>=2 periods -> timeline, >=2 countries or
#      products -> opportunity map, ...).
#   3. One SMALL per-widget signature per selected widget — each call has one
#      job and one output, so it cannot under-fill its schema.
# `core.agents.boardroom` assembles the parts into the same `BoardroomDigest`
# the UI and PPT export already render.

_SQL_OUTPUT_DESC = (
    "Underlying result rows keyed by lens — either per-flow ('premium', "
    "'survey') or, on analyst turns, one entry per executed analytical lens "
    "('gpr:temporal_trend', 'gpr:peer_benchmark', 'survey:...'). Scan EVERY "
    "entry. Each value is a compact pipe-delimited table: an optional "
    "'constants:' line (columns identical on every row), a header row of "
    "column names, then one 'val | val | ...' line per row (truncated samples)."
)


class BoardroomCore(BaseModel):
    """The always-on heart of the dashboard (stage 1 of the staged digest)."""

    title: str = Field(description="Dashboard title — usually the carrier or subject, e.g. 'Zurich — Canada'.")
    subtitle: str = Field(
        default="",
        description="One-line context, e.g. '2024 premium performance vs peer set'.",
    )
    headline: str = Field(
        default="",
        description="A single punchy sentence stating the bottom line of the answer.",
    )
    kpis: List[KpiCard] = Field(
        default_factory=list,
        description="3-5 KPI cards covering the most decision-relevant numbers in the answer.",
    )
    insights: List[InsightCard] = Field(
        default_factory=list,
        description=(
            "2-4 polished executive insight cards — punchy, narrative takeaways (NOT bare "
            "metric tiles). Distil the most board-worthy conclusions."
        ),
    )
    commentary: List[CommentarySection] = Field(
        default_factory=list,
        description="1-3 commentary sections distilled from the written analysis.",
    )
    risks: List[RiskItem] = Field(
        default_factory=list,
        description="0-4 risk/watch items if the analysis surfaces any; otherwise empty.",
    )


class BoardroomCoreSignature(dspy.Signature):
    """
    [ROLE]
    You are an executive briefing designer. You receive an analyst's finished
    written answer (commentary) and the underlying result rows for an insurance
    carrier question, and you produce the CORE of a boardroom dashboard.

    [OBJECTIVE]
    Produce a `BoardroomCore` a C-suite reader could absorb in seconds:
    - 3-5 KPI cards with the most decision-relevant numbers, each formatted for
      display and tagged with the correct sentiment tone from the carrier's
      perspective (a premium decline is 'danger', a rank improvement is 'good').
    - A single-sentence `headline` stating the bottom line.
    - 2-4 `insights`: polished executive callouts — punchy narrative takeaways
      (e.g. 'Rank dropped 4 places', 'Property drives 62% of premium'), each
      with a one-line so-what. These are conclusions, not bare metrics.
    - 1-3 commentary sections (heading + 2-4 crisp bullets) distilled from the
      written analysis.
    - 0-4 risk items only if the analysis genuinely surfaces risks.

    [NARRATIVE FUNNEL — the board reads top-left to bottom-right]
    Order everything wide → narrow so the dashboard tells one story:
    - KPIs: the broadest, most decision-relevant numbers first (overall premium /
      rank before segment-level figures).
    - insights: the first card is the big-picture verdict; each later card narrows
      (segment → product → the single sharpest finding worth acting on).
    - commentary sections follow the same arc — e.g. 'The big picture' → "What's
      driving it" → 'Where to act'.

    [HARD CONSTRAINTS]
    - Use ONLY numbers and facts present in the commentary or rows. Never invent,
      extrapolate, or round in a way that changes meaning. If a comparison is not
      stated, leave `delta` empty.
    - Keep every string short and board-ready. No markdown, no citations.
    - Faithful to the commentary; reformat, never reanalyse.
    - Peers stay aggregated — never name an individual peer carrier (Marsh and
      the subject carrier are fine).
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    route: str = dspy.InputField(desc="Which analytical lens produced the answer (survey/premium/both/analyst/fallback).")
    commentary: str = dspy.InputField(desc="The finished written analysis to distil (may carry several lenses, each under a '## Lens' heading).")
    sql_output: Any = dspy.InputField(desc=_SQL_OUTPUT_DESC)
    core: BoardroomCore = dspy.OutputField(
        desc="The core dashboard content, faithful to the commentary."
    )


class BoardroomTimelineSignature(dspy.Signature):
    """
    Build the Insight Timeline for a boardroom dashboard: the carrier's major
    movements across periods (premium growth, rank moves, score shifts, product
    changes), in chronological order. The data ALREADY shows two or more
    periods — extract every notable movement between them. Use ONLY periods and
    values present in the commentary or rows; never fabricate. Each event gets
    a short title, an optional one-line detail, the right category, and a tone
    from the carrier's perspective. Peers stay aggregated (never name one).
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    commentary: str = dspy.InputField(desc="The finished written analysis.")
    sql_output: Any = dspy.InputField(desc=_SQL_OUTPUT_DESC)
    timeline: List[TimelineEvent] = dspy.OutputField(
        desc="Chronological movements; empty only if the periods carry no movement worth showing."
    )


class BoardroomOpportunityMapSignature(dspy.Signature):
    """
    Build the Market Opportunity Map for a boardroom dashboard: a
    country×product whitespace/growth-priority heatmap. The data ALREADY spans
    two or more countries and/or products — build the grid from them (sparse
    cells are fine; only populate cells the commentary or rows support).
    Intensity 0-100 = whitespace/growth priority (carrier low + market high =
    high). Use ONLY countries, products, and figures present in the commentary
    or rows; never fabricate. Peers stay aggregated.
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    commentary: str = dspy.InputField(desc="The finished written analysis.")
    sql_output: Any = dspy.InputField(desc=_SQL_OUTPUT_DESC)
    opportunity_map: OpportunityMap = dspy.OutputField(
        desc="The heatmap; leave rows/cols/cells empty only if no grid can be grounded."
    )


class BoardroomOpportunitiesSignature(dspy.Signature):
    """
    Build the Opportunity Radar for a boardroom dashboard: concrete whitespace
    where the carrier's premium/presence is LOW while Marsh-book or peer
    activity is HIGH. Scan every result set and the commentary for such gaps;
    score each 0-100 (carrier low + market high = high) and give a one-line
    recommended move. Use ONLY areas and figures present in the commentary or
    rows; an empty list is correct when no genuine gap shows. Peers stay
    aggregated (never name one).
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    commentary: str = dspy.InputField(desc="The finished written analysis.")
    sql_output: Any = dspy.InputField(desc=_SQL_OUTPUT_DESC)
    opportunities: List[Opportunity] = dspy.OutputField(
        desc="Detected whitespace gaps; empty when none is grounded in the data."
    )


class BoardroomPositioningSignature(dspy.Signature):
    """
    Build the Peer Positioning Matrix (2x2: premium strength on x, broker
    perception on y, both 0-100) for a boardroom dashboard. The data ALREADY
    carries both premium and perception/score signals — place the subject
    carrier (is_subject=true) and the aggregated peer set on the matrix.
    Normalise honestly from the figures present (e.g. highest premium in the
    data ≈ 90, peer average mid-scale); never fabricate a signal that is not
    there. Individual peers stay aggregated — plot 'Peer avg' as ONE point,
    never one point per named peer.
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    commentary: str = dspy.InputField(desc="The finished written analysis.")
    sql_output: Any = dspy.InputField(desc=_SQL_OUTPUT_DESC)
    positioning: PositioningMatrix = dspy.OutputField(
        desc="The 2x2 matrix; leave points empty only if a signal is genuinely missing."
    )


class BoardroomComparisonSignature(dspy.Signature):
    """
    Build the side-by-side Comparison view for a boardroom dashboard. The
    answer compares two or more entities (carrier vs peer set, several
    carriers, or one metric across subjects) — align every metric row's values
    to the SAME subject order, formatted for display, with optional tones from
    the subject's perspective. `highlight` = index of the carrier in focus.
    Individual peers stay aggregated: a 'Peer avg' subject is fine, named peer
    carriers are not. Use ONLY values present in the commentary or rows.
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    commentary: str = dspy.InputField(desc="The finished written analysis.")
    sql_output: Any = dspy.InputField(desc=_SQL_OUTPUT_DESC)
    comparison: ComparisonView = dspy.OutputField(
        desc="The aligned comparison; leave subjects empty only if nothing is comparable."
    )


class BoardroomBattlecardsSignature(dspy.Signature):
    """
    Build competitive Battlecards for a boardroom dashboard: one profile for
    the subject carrier (and the aggregated peer set ONLY if the analysis
    genuinely covers it as a unit — never a named individual peer). Populate
    strengths / weaknesses / product gaps / broker perception ONLY from facts
    in the commentary or rows; leave a dimension empty rather than inventing.
    Empty list for non-carrier answers.
    """

    user_query: str = dspy.InputField(desc="The user's original question.")
    commentary: str = dspy.InputField(desc="The finished written analysis.")
    sql_output: Any = dspy.InputField(desc=_SQL_OUTPUT_DESC)
    battlecards: List[Battlecard] = dspy.OutputField(
        desc="Grounded competitive profiles; empty when no carrier is discussed."
    )
