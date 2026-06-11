"""Pydantic + dspy schemas for the context filler, rephraser, and router nodes.

The routing-context flow:
    context_filler  -> RoutingContext (typed)
    rephraser       -> rephrased_query (string), informed by RoutingContext
    router          -> reads RoutingContext.table_family deterministically
                       (no LLM call)
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import dspy
from pydantic import BaseModel, Field


class RephraserAgent(BaseModel):
    rephrased_question: str = Field(description="Rephrased question")


class RouteQuery(BaseModel):
    name: Literal["survey", "premium", "both", "fallback"] = Field(
        description="Indicates where to route to. 'survey', 'premium', 'both', or 'fallback'. Use 'both' when the user query does NOT explicitly name a table AND could plausibly be enriched by BOTH broker-perception (survey) and premium/financial data."
    )


class OutputDirectives(BaseModel):
    """Per-turn presentation preferences stated inline in the user's query.

    The first slice of the query contract: chart-producing nodes check
    `charts` instead of running unconditionally, so "don't generate a chart"
    is honored as plumbing, not prompt hope. Defaults mean "no preference
    stated" — never invent a directive the user didn't give.
    """

    charts: Literal["auto", "none", "required"] = Field(
        default="auto",
        description=(
            "'none' ONLY when the user explicitly asks for no charts/graphs/"
            "visuals or text/table-only output. 'required' ONLY when the user "
            "explicitly asks to see a chart/graph/visualization. 'auto' (the "
            "default) whenever the query states no chart preference."
        ),
    )
    presentation: Literal["prose", "chart_only", "table_only"] = Field(
        default="prose",
        description=(
            "What the answer body should be. 'prose' (default) — the normal "
            "written answer (plus a chart unless `charts`=='none'). 'chart_only' "
            "— ONLY the chart, no written analysis or follow-ups ('just show me "
            "the visual'). 'table_only' — ONLY the data table, no written "
            "analysis, no chart ('just the table', 'just the numbers'). Set ONLY "
            "on an explicit user request; never guess. The deterministic phrase "
            "detector keeps `charts` coherent (chart_only -> 'required', "
            "table_only -> 'none')."
        ),
    )
    depth: Literal["analyst", "direct"] = Field(
        default="analyst",
        description=(
            "How long the written answer should be. 'analyst' (default) — the "
            "full structured analysis. 'direct' — a one-to-two-sentence answer "
            "with no headings, recommendations table, or follow-ups, when the "
            "user asks for a short/one-line answer. Per-turn; never inherited."
        ),
    )
    source: str = Field(
        default="",
        description=(
            "Where the directive came from: 'deterministic' (phrase detector) "
            "or 'llm'. Leave empty for the 'auto' default."
        ),
    )


class QueryEntities(BaseModel):
    """Entity MENTIONS in the current turn, verbatim as the user wrote them.

    Slice 2 of the query contract. The context filler extracts these once
    (including inherited ones already materialised in inherited_*); the node
    then resolves them deterministically against each flow's valid values into
    `RoutingContext.resolved_filters`, so every downstream consumer — the
    rephraser, the analyst's schema identifier, the solvers — works from the
    SAME canonical values instead of re-deriving them per node.
    """

    carriers: List[str] = Field(
        default_factory=list,
        description=(
            "Carrier names mentioned, verbatim (e.g. ['Zurich', 'Chubb']). "
            "NEVER include Marsh — it is the broker, not a carrier. Empty when "
            "no carrier is named or inherited."
        ),
    )
    countries: List[str] = Field(
        default_factory=list,
        description="Countries/markets mentioned, verbatim (e.g. ['UK', 'Canada']).",
    )
    products: List[str] = Field(
        default_factory=list,
        description="Product / line-of-business mentions, verbatim (e.g. ['cyber']).",
    )
    industries: List[str] = Field(
        default_factory=list,
        description="Industry / sector mentions, verbatim (e.g. ['manufacturing']).",
    )
    segments: List[str] = Field(
        default_factory=list,
        description="Client-segment mentions, verbatim (e.g. ['large corporate']).",
    )
    years: List[str] = Field(
        default_factory=list,
        description=(
            "Explicit years/periods mentioned, as text (e.g. ['2024']). Leave "
            "empty for relative terms — those belong in timeframe_hint."
        ),
    )


class UnresolvedTerm(BaseModel):
    """An entity mention that failed to resolve to any stored value."""

    kind: str = Field(default="", description="Entity kind: carrier/country/product/industry/segment.")
    term: str = Field(default="", description="The user's wording that failed to match.")
    column: str = Field(default="", description="The column it was checked against.")
    flow: str = Field(default="", description="The flow whose values were checked.")


class RoutingContext(BaseModel):
    """Structured routing + inheritance context produced by the context filler.

    Single source of truth for: which SQL family to route to, what filters
    were inherited from prior turns, what timeframe the LLM should assume,
    and what kind of turn this is (new question vs followup). Downstream:
    - Rephraser consumes it to produce a single coherent NL sentence.
    - Router reads `table_family` to dispatch without an extra LLM call.
    """

    table_family: Literal["survey", "premium", "both", "fallback"] = Field(
        description=(
            "Routing decision. 'survey' for broker-perception/NPS/score queries; "
            "'premium' for GPR/SoW/appetite/rank queries; 'both' for holistic "
            "strategic queries with no exclusive metric (HYBRID); 'fallback' "
            "for out-of-scope queries."
        )
    )
    inherited_carrier: Optional[str] = Field(
        default=None,
        description=(
            "Carrier name inherited from prior turn when current query is a "
            "followup that omits it (e.g., 'and in Canada?'). Null when the "
            "current query explicitly names a carrier or no prior turn exists."
        ),
    )
    inherited_country: Optional[str] = Field(
        default=None,
        description="Country inherited from prior turn for followup queries. Null otherwise.",
    )
    inherited_year: Optional[str] = Field(
        default=None,
        description=(
            "Year or year range inherited from prior turn (as text, e.g. '2024' "
            "or '2023-2024'). Null when current query specifies it or no prior turn."
        ),
    )
    inherited_metric: Optional[str] = Field(
        default=None,
        description=(
            "Metric (Score, NPS, Premium, SoW, etc.) inherited from prior turn "
            "ONLY when current query is a direct followup. Never invented."
        ),
    )
    timeframe_hint: str = Field(
        default="",
        description=(
            "Resolution of relative time references in the current query. E.g., "
            "'last year' -> 'MAX(Survey_Year) - 1', 'TTM' -> 'last 12 months from "
            "MAX(Billing_Date)'. Empty when no relative time term is present."
        ),
    )
    analysis_depth: Literal["lookup", "analytical"] = Field(
        default="lookup",
        description=(
            "How much analytical depth the query needs. 'lookup': a direct "
            "factual value retrieval answerable by a single query (e.g. 'what is "
            "Zurich's premium in Canada in 2024?', 'Zurich's NPS?'). 'analytical': "
            "any interpretive / multi-step / comparative question that benefits "
            "from context — compare, trend, why, performance, positioning, "
            "'how is X doing', breakdowns across a dimension, or any 'both' "
            "(HYBRID) query. NOTE: this value is re-decided downstream by a "
            "dedicated depth classifier (`DepthClassifierSignature`) and will be "
            "overwritten — the default here is only a placeholder, so do not rely "
            "on it for routing."
        ),
    )
    intent_type: Literal[
        "new_question", "followup", "drilldown", "topic_switch"
    ] = Field(
        description=(
            "Turn classification. 'new_question': independent of history. "
            "'followup': inherits filters from immediate prior turn (e.g., 'what about peers?'). "
            "'drilldown': narrows the prior result by one dimension. "
            "'topic_switch': changes table_family vs prior turn — drop incompatible filters."
        )
    )
    conversation_intent: Literal[
        "analyze", "summarize_chat", "recall_previous"
    ] = Field(
        default="analyze",
        description=(
            "Whether the turn is a META request about the conversation itself "
            "rather than a new data question. 'analyze' (default): a normal "
            "analytical/lookup turn — route to SQL/analyst as usual. "
            "'summarize_chat': the user asked to summarize/recap the discussion. "
            "'recall_previous': the user asked what was recommended/concluded/"
            "decided earlier. Meta turns are answered from the persisted "
            "transcript with NO new database query. LEAVE as 'analyze'; a "
            "deterministic detector sets the meta values downstream."
        ),
    )
    rationale: str = Field(
        default="",
        description=(
            "One-paragraph CoT explanation of the routing + inheritance choices. "
            "Surfaces the reasoning so HITL can show it to the user when "
            "confidence is low."
        ),
    )
    output_directives: OutputDirectives = Field(
        default_factory=OutputDirectives,
        description=(
            "Presentation preferences stated inline in the current query "
            "(chart suppression/request). Set charts='none' or 'required' ONLY "
            "on an explicit user statement; otherwise keep the 'auto' default."
        ),
    )
    entities: QueryEntities = Field(
        default_factory=QueryEntities,
        description=(
            "Entity mentions in the current turn, verbatim — including filters "
            "you inherited (also set inherited_*). Extract, never invent."
        ),
    )
    resolved_filters: Dict[str, List[str]] = Field(
        default_factory=dict,
        description=(
            "LEAVE EMPTY. Filled deterministically downstream: exact stored "
            "values per column (e.g. {'Country': ['United Kingdom']})."
        ),
    )
    unresolved_terms: List[UnresolvedTerm] = Field(
        default_factory=list,
        description="LEAVE EMPTY. Filled downstream with mentions that matched no stored value.",
    )


class ContextFillerSignature(dspy.Signature):
    """
    [ROLE]
    You are the Context Filler Agent for an insurance analytics chatbot. You
    extract STRUCTURED routing + inheritance context from the user's current
    query and recent conversation history. You do NOT rephrase the query — a
    downstream agent does that, using your structured output.

    [OBJECTIVE]
    Produce a single RoutingContext object with:
      1. table_family — which SQL family the query targets (Carriers survey,
         GPR premium, both for HYBRID, fallback for out-of-scope).
      2. Inherited filters (carrier, country, year, metric) — ONLY when the
         current query is a followup that omits them. Never invent.
      3. timeframe_hint — concrete resolution of any relative time term.
      4. intent_type — new_question / followup / drilldown / topic_switch.
      5. rationale — short CoT trace.

    [ROUTING RULES — table_family]
    1) survey (Carriers/perception lens)
       - Exclusive triggers: NPS, score, satisfaction, sentiment, perception,
         attribute, section, response count, feedback, broker rating.
    2) premium (GPR/financial lens)
       - Exclusive triggers: premium, GPR, revenue, share of wallet, SoW,
         share of portfolio, rank, growth rate, rolling 12, MoM, market share,
         gross premium.
    3) both (HYBRID — fused view)
       - HOLISTIC / STRATEGIC queries with no exclusive metric ("QBR view",
         "how is X performing", "competitive positioning", "carrier health").
       - Queries pairing perception + financial intent ("growth matching NPS").
       - Shared metrics (YoY, peer, trend) without a disambiguating lens AND
         no prior single-lens turn in history.
    4) fallback
       - Clearly outside insurance carrier/broker/market scope.

    AMBIGUOUS SHARED METRICS (YoY, growth, rank, trend, peer comparison):
       i.   If the same query contains an exclusive term -> use that family.
       ii.  Else if prior user turn clearly targeted one family -> inherit it.
       iii. Else -> both (HYBRID).

    [ANALYSIS DEPTH — analysis_depth]
    Classify how much depth the query needs:
      - "lookup": a single concrete value the user named explicitly — a metric
        for a specific carrier/slice/period with no comparison or reasoning
        ("Zurich's premium in Canada 2024?", "AXA's NPS?"). Stays on the fast
        deterministic path.
      - "analytical": interpretive or genuinely multi-step — compare/vs peers,
        trend or growth framed for interpretation, "why", "how is X
        performing/positioned", "analyse", a cross of two+ dimensions/metrics,
        whitespace/opportunity, or ANY table_family == "both" (HYBRID) query.
        These get the proactive analyst agent. NOTE: a plain single-dimension
        breakdown / GROUP BY ("SoW across products", "premium by region") is a
        "lookup" — a breakdown alone is not analytical. (Re-decided downstream by
        DepthClassifierSignature.)

    [INHERITANCE POLICY]
    - P0: Always begin with the current user query.
    - P1: If filters (Country, Carrier, Year, Product, etc.) are missing in
      the current query, inherit from the IMMEDIATE prior query first.
    - P2: If P1 yields nothing, scan older history (newest -> oldest) and
      inherit from the most recent turn whose family matches (or overlaps for
      HYBRID) the current family.
    - TOPIC SWITCH: when current family != prior family, ONLY inherit filters
      valid in the NEW family's schema; drop the rest. Set intent_type =
      "topic_switch".
    - SELF-REFERENCE: "my", "I", "me", "our" -> inherit Carrier from most
      recent turn.

    [ENTITY EXTRACTION — entities]
    List every entity MENTION in the current turn, verbatim as the user wrote
    it (after applying inheritance: an inherited carrier appears in BOTH
    inherited_carrier and entities.carriers):
      - carriers ('Zurich', 'AXA' — NEVER Marsh, it is the broker),
      - countries/markets ('UK', 'Singapore'),
      - products/lines ('cyber', 'property'), industries ('manufacturing'),
        client segments, explicit years ('2024').
    Entities are FILTER VALUES (who/where/which slice), never MEASURES. Do NOT
    put a metric/measure word in any entity bucket — 'premium', 'GPR',
    'revenue', 'share of wallet', 'SoW', 'appetite', 'share of portfolio',
    'product mix', 'NPS', 'score', 'growth', 'rank' are measures, not
    products/segments/industries. Leave those out of entities entirely.
    Do NOT normalise or expand the wording — downstream code resolves each
    mention against the stored valid values deterministically. Leave
    resolved_filters and unresolved_terms EMPTY; they are filled downstream.

    [OUTPUT DIRECTIVES — output_directives.charts]
    Read the CURRENT query for an explicit presentation preference:
      - 'none'      — the user asks for no charts/graphs/visuals, or text/table/
                      numbers-only output ("no chart", "without a graph",
                      "just the numbers", "table only").
      - 'required'  — the user explicitly asks to SEE a chart/graph/plot
                      ("show me a chart of...", "visualize", "as a graph").
      - 'auto'      — the default; the query states no preference. NEVER guess.
    When you set 'none' or 'required', set output_directives.source = 'llm'.
    A negated phrase ("don't generate a chart") is ALWAYS 'none', never
    'required'. Directives are per-turn: do not inherit them from history.

    [HARD RULES]
    - Never invent a metric, carrier, country, or year not present in the
      current query or recoverable from history.
    - For HYBRID, leave inherited_metric null — do not force a lens.
    - For first-turn queries (empty history), inherited_* must all be null.
    """

    static_context: str = dspy.InputField(
        desc="Stable schemas dictionary + valid-values snapshot for entity matching."
    )
    current_user_query: str = dspy.InputField(
        desc="The latest user question — primary input to classify and contextualise."
    )
    last_user_query: str = dspy.InputField(
        desc="The immediately prior user query, or empty string if this is the first turn."
    )
    conversation_history: List[str] = dspy.InputField(
        desc="Older user queries (oldest -> newest), excluding `last_user_query` and `current_user_query`. Empty list if not available."
    )
    routing_context: RoutingContext = dspy.OutputField(
        desc="Structured routing decision + inherited filters + timeframe + intent + rationale."
    )


class DepthDecision(BaseModel):
    """Output of the dedicated analysis-depth classifier."""

    analysis_depth: Literal["lookup", "analytical"] = Field(
        description=(
            "'lookup' = a single concrete value the user named explicitly (one "
            "metric for one carrier/slice/period, no comparison/reasoning). "
            "'analytical' = anything interpretive or multi-step: compare, rank, "
            "trend, growth, 'why', 'how is X performing/positioned', 'analyse', "
            "breakdowns ('by product/industry/segment'), whitespace/opportunity."
        )
    )
    reason: str = Field(
        default="",
        description="One short sentence justifying the lookup-vs-analytical call.",
    )


class DepthClassifierSignature(dspy.Signature):
    """
    [ROLE]
    You are a focused query-depth classifier for an insurance analytics chatbot.
    Your ONLY job is to decide whether the user's question is a simple factual
    LOOKUP or an interpretive ANALYTICAL question. You do not route, rephrase, or
    answer — you output one label.

    [WHY THIS MATTERS]
    A 'lookup' goes to a cheap single-query path. An 'analytical' question goes to
    a proactive multi-step analyst agent. Misclassifying a comparison/trend/"why"
    question as 'lookup' produces a shallow, unhelpful answer.

    [DECIDE 'lookup' WHEN]
    - The query is answerable by a SINGLE SQL query, even if it aggregates or
      groups. This INCLUDES a plain breakdown of ONE metric across ONE dimension
      ("SoW across products", "premium by region", "score by section") and a
      simple ranking / top-N ("top 5 carriers by premium"). A GROUP BY is still a
      lookup — a breakdown by itself does NOT make a query analytical.
    - The user names a metric (optionally for a carrier/slice/period) and wants
      the value(s), with no comparison, driver ("why"), or interpretation.
    - Examples:
        * "What is Zurich's premium in Canada in 2024?"  -> lookup
        * "AXA's NPS?"                                    -> lookup
        * "Chubb's rank in Singapore last year?"         -> lookup
        * "SoW across products"                          -> lookup
        * "Premium by region for Zurich"                 -> lookup
        * "Top 5 carriers by gross premium"              -> lookup

    [DECIDE 'analytical' WHEN]
    - The question is interpretive or genuinely multi-step — it needs more than
      one query or a layer of reasoning on top of the numbers:
        * comparison against peers / benchmark ("vs peers", "compare X and Y"),
        * a trend the user wants explained, or growth/YoY/QoQ framed as movement
          to interpret ("how has X changed", "what's driving growth"),
        * "why", "how is X doing/performing/positioned", "analyse", competitive
          position, portfolio/carrier health,
        * a cross of TWO+ dimensions or metrics ("premium vs NPS by product"),
        * whitespace, opportunity, appetite gaps, or contradictions.
    - Examples:
        * "How is Zurich performing vs peers by product?"   -> analytical
        * "Why did AXA's premium drop in 2024?"             -> analytical
        * "Compare Chubb's growth across industries."        -> analytical
        * "Where is Zurich's whitespace in Canada?"          -> analytical

    [HARD RULE]
    - If table_family is "both" (HYBRID), the answer is ALWAYS "analytical".
    - A single-dimension breakdown / GROUP BY with no comparison, no "why", and
      no peer/trend interpretation is a 'lookup', not 'analytical'.
    - When genuinely unsure between a plain breakdown and a comparison, prefer
      'lookup'; reserve 'analytical' for clear interpretive / multi-step intent.
    """

    current_user_query: str = dspy.InputField(
        desc="The latest user question to classify for depth."
    )
    table_family: str = dspy.InputField(
        desc="Routing family already decided upstream: survey | premium | both | fallback."
    )
    intent_type: str = dspy.InputField(
        desc="Turn classification: new_question | followup | drilldown | topic_switch."
    )
    depth_decision: DepthDecision = dspy.OutputField(
        desc="The lookup-vs-analytical decision plus a one-line reason."
    )


class RephaserNodeSignature(dspy.Signature):
    """
    [ROLE]
    You are the Rephraser Agent. You receive (a) the user's current query and
    (b) a structured RoutingContext already produced upstream by the Context
    Filler. You produce ONE clear, grammatically correct, self-contained
    natural-language query that downstream SQL agents can act on.

    [SCOPE — WHAT YOU DO]
    - Stitch the current query together with inherited filters from
      RoutingContext into ONE sentence.
    - Fix grammar and expand shorthand.
    - Normalise synonyms to schema terms ("top line" -> "Gross Premium",
      "satisfaction" -> "Score") only where schemas confirm.
    - Resolve pronouns ("they", "it", "that carrier") using the inherited
      filters provided in RoutingContext.

    [SCOPE — WHAT YOU DO NOT DO]
    - You do NOT pick a table family — that was decided by the Context Filler.
    - You do NOT invent filters, metrics, peers, or timeframes that are
      absent from both the current query and RoutingContext.
    - You do NOT add a metric hint to a HYBRID (both) query. If
      RoutingContext.inherited_metric is null and table_family is "both",
      keep the query metric-free.

    [INHERITANCE BEHAVIOUR]
    - If RoutingContext.inherited_carrier is set, weave it into the rephrased
      sentence (e.g., current "what about 2025?" + inherited Zurich/Score ->
      "What is Zurich's Score in 2025?").
    - If RoutingContext.resolved_filters holds the exact stored value(s) for an
      entity the user named loosely, write the EXACT stored value ("UK" ->
      "United Kingdom", "Zurich" -> "ZURICH GROUP"). Mentions listed in
      RoutingContext.unresolved_terms stay verbatim — never substitute a guess.
    - If RoutingContext.timeframe_hint is set, materialise it (e.g., "last
      year" -> "2024").
    - If intent_type == "topic_switch", DROP inherited filters not valid in
      the new family's schema.

    [OUTPUT FORMAT]
    Return ONE single rephrased sentence. No commentary, no JSON, no headers.
    If the current query is already perfect and no inheritance is needed,
    return it unchanged.

    [PRESERVE PHRASES]
    If the user query contains "across", "by", or a dimension phrase
    (product, industry, region, etc.), preserve it verbatim — it controls
    the downstream GROUP BY.
    """

    routing_context: RoutingContext = dspy.InputField(
        desc="Structured routing + inheritance context produced by the Context Filler. Use it to know what to inherit and what NOT to invent."
    )
    construction_rules: str = dspy.InputField(
        desc="Grammar / synonym / phrase-preservation rules for the final sentence."
    )
    current_user_query: str = dspy.InputField(
        desc="The latest user question — the sentence to rephrase."
    )
    rephrased_query: str = dspy.OutputField(
        desc="A single self-contained natural-language query for the SQL agents."
    )
