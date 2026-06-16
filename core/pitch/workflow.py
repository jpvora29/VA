"""Pitch builder workflow — multi-question docx report generation.

Pitch has its own state schema, checkpointer, and graph topology. The pitch
question graph currently mirrors the chat analytical flow, but future chat-only
nodes will not be inherited by Pitch Builder automatically.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from core.analysis import plan_analysis
from core.graph.checkpointer import build_pitch_checkpointer, checkpoint_config
from core.graph.pitch_question_graph import PitchQuestionGraph
from core.initialization import Initialization
from core.observability import log_event
from core.schemas.pitch import PitchExtractedInsight, PitchNarrativeArc, PitchTopKPIs
from core.schemas.routing import RoutingContext
from core.skills.loader import get_skill_loader
from core.state.pitch_state import PitchAgentState, PitchQuestionResult
from logger import get_logger

logger = get_logger(__name__)


class PitchBuilderWorkflow:
    """Pitch-specific orchestration with islolated pitch state fields."""

    THEME_LABELS = {"performance_pitch": "Performance Pitch"}

    def __init__(self) -> None:
        self.checkpointer = build_pitch_checkpointer()
        self.pitch_question_graph = PitchQuestionGraph(
            checkpointer=self.checkpointer,
            default_thread_id="pitch-question-default",
        )
        self._workflow_app = None
        self._report_workflow_app = None

    @staticmethod
    def _build_question_prompt(
        theme_key: str, filters: dict[str, Any], question: str
    ) -> str:
        theme_label = PitchBuilderWorkflow.THEME_LABELS.get(
            theme_key, theme_key or "Pitch"
        )
        filter_text = ", ".join(
            f"{label}: {value}"
            for label, value in [
                ("Country", filters.get("country")),
                ("Carrier", filters.get("carrier")),
                ("Year", filters.get("year")),
            ]
            if value
        )

        return question
        # return (
        #     f"Theme: {theme_label}"
        #     f"Using only the database tables and SQL-backed evidence, answer this insurance domain question: {question}. "
        #     f"Apply these filters exactly where available: {filter_text or 'no explicit filters selected'}. "
        #     "Return a concise answer suitable for a one-page executive pitch report. "
        #     "If the database does not contain enough evidence, say what is missing instead of inventing facts."
        # )

    @staticmethod
    def _extract_answer(state: PitchAgentState) -> str:
        route = (state.get("current_route") or "").lower()
        if route == "survey":
            return state.get("survey_response") or ""
        if route == "premium":
            parts = [state.get("gpr_response") or "", state.get("gimmi_response") or ""]
            return "\n\n".join(part for part in parts if part).strip()
        if route == "both":
            return state.get("combined_response") or ""

        return state.get("out_of_scope_answer") or ""

    @staticmethod
    def _extract_question_result(
        state: PitchAgentState, question: str, answer: str
    ) -> PitchQuestionResult:
        route = state.get("current_route")
        result: PitchQuestionResult = {
            "question": question,
            "answer": answer,
            "pitch_route": route,
            "pitch_sql_query": None,
            "pitch_query_result": None,
        }

        if route == "survey":
            result["pitch_sql_query"] = state.get("survey_sql_query")
            result["pitch_query_result"] = state.get("survey_query_result")
        elif route == "premium":
            result["pitch_sql_query"] = state.get("gpr_sql_query")
            result["pitch_query_result"] = state.get("gpr_query_result")
        elif route == "both":
            result["pitch_sql_query"] = {
                "survey": state.get("survey_sql_query"),
                "premium": state.get("gpr_sql_query"),
            }
            result["pitch_query_result"] = {
                "survey": state.get("survey_query_result"),
                "premium": state.get("gpr_query_result"),
            }

        return result

    def _answer_question(
        self,
        theme_key: str,
        filters: dict[str, Any],
        question: str,
        *,
        thread_id: str,
    ) -> PitchQuestionResult:
        prompt = self._build_question_prompt(theme_key, filters, question)
        isolated_state: PitchAgentState = {
            "messages": [HumanMessage(content=prompt)],
            "survey_attempts": 0,
            "gpr_attempts": 0,
            "gimmi_attempts": 0,
            "pitch_theme": theme_key,
            "pitch_filters": filters,
        }

        updated_state = self.pitch_question_graph.trigger_workflow(
            isolated_state, thread_id=thread_id
        )
        answer = self._extract_answer(updated_state).strip()
        return self._extract_question_result(updated_state, question, answer)

    def generate_answers(self, state: PitchAgentState) -> PitchAgentState:
        theme_key = state.get("pitch_theme") or "performance_pitch"
        filters = state.get("pitch_filters") or {}
        questions = state.get("pitch_questions") or []
        pitch_thread_id = state.get("pitch_thread_id") or uuid.uuid4().hex[:12]
        answers: dict[str, str] = {}
        question_results: list[PitchQuestionResult] = []

        for index, question in enumerate(questions, start=1):
            question = (question or f"Question {index}").strip()
            if not question:
                continue
            try:
                result = self._answer_question(
                    theme_key,
                    filters,
                    question,
                    thread_id=f"{pitch_thread_id}:question:{index}",
                )
            except Exception as exc:
                result = {
                    "question": question,
                    "answer": "",
                    "pitch_route": "error",
                    "pitch_sql_query": None,
                    "pitch_query_result": None,
                    "error": str(exc),
                }

            answers[question] = result.get("answer", "")
            question_results.append(result)

        state["pitch_thread_id"] = pitch_thread_id
        state["pitch_theme_label"] = "Performance Pitch"
        state["pitch_answers"] = answers
        state["pitch_question_results"] = question_results

        return state

    @staticmethod
    def _dump_model(value: Any) -> dict[str, Any]:
        if isinstance(value, BaseModel):
            if hasattr(value, "model_dump"):
                return value.model_dump()
            return value.dict()
        if isinstance(value, dict):
            return value
        return {}

    @staticmethod
    def _json_for_prompt(value: Any, limit: int = 12000) -> str:
        text = json.dumps(value, indent=2, default=str)
        # if len(text) <= limit:
        return text
        # return text[: limit - 80].rstrip() + "\n... [truncated for prompt size]"

    @staticmethod
    def _fallback_extracted_insight(
        result: PitchQuestionResult, error: str = ""
    ) -> dict[str, Any]:
        limitations = [
            "Structured insight extraction failed; using factual answer fallback."
        ]
        if error:
            limitations.append(error)
        answer = result.get("answer") or ""
        return {
            "question": result.get("question") or "",
            "answer_summary": answer,
            "route": str(result.get("pitch_route")),
            "extracted_metrics": {},
            "business_meaning": answer,
            "evidence_rows_used": [],
            "confidence": "low",
            "limitations": limitations,
        }

    @staticmethod
    def _find_metric_value(metrics: Any, key_terms: list[str]) -> Any:
        if isinstance(metrics, dict):
            for key, value in metrics.items():
                key_text = str(key).lower()
                if any(term in key_text for term in key_terms):
                    return value

            for value in metrics.values():
                found = PitchBuilderWorkflow._find_metric_value(value, key_terms)
                if found not in (None, "", [], {}):
                    return found

        elif isinstance(metrics, list):
            for item in metrics:
                found = PitchBuilderWorkflow._find_metric_value(item, key_terms)
                if found not in (None, "", [], {}):
                    return found
        return None

    def extract_question_insights(self, state: PitchAgentState) -> PitchAgentState:
        question_results = state.get("pitch_question_results") or []
        extracted_insights: list[dict[str, Any]] = []

        for result in question_results:
            prompt = f"""
            You are an insurance analytics insight extractor. Convert one Performance analyzer question result into structured JSON.
            Rules:
            - Extract only facts present in the SQL output or SQL-backed answer.
            - Do not infer missing metrics, percentages, ranks, products, Share of Wallet values, or market claims.
            - Preserve numbers exactly when already formatted.
            - Format Premium values as USD where the value is clearly a premium.
            - Format percenage values with a % sign where the evidence is clearly a percentage.
            - Put all extracted measures in extracted_metrics. Do not use hard-coded metric slots.
            - extracted_metrics is a FLAT list of items. Each item has exactly three fields: `metric` (measure name), `value` (the value as text), and `context` (layer label + optional qualifier such as product / segment / period). Do NOT emit nested dictionaries or lists inside an item — use multiple flat items instead, one per measure, each tagged with its layer in the `context` field.
            - evidence_rows_used should include only the most releveant SQL rows.
            - confidence should be high, medium, or low.

            Required ordering and coverage for extracted_metrics (include every layer that is supported by the evidence, in this exact order; skip a layer only if the SQL output contains nothing for it):
            1. KPIs - top-line headline measures supported by the evidence (e.g., totals, overall growth, overall SoW, score, premiums, overall rank).
            2. Carrier-Level information - carrier-specific measures such as premium, score, rank, policies, last year's rank, prior-period comparisons, and any other carrier-level facts present.
            3. Carrier product breakdown - the same carrier metrics broken down by product / line of business
            4. Carrier attribute-level information or any other carrier breakdowns - segmentation by attributes or industry, region, segments, sections or any other dimension present in the evidence.
            5. Peer-level information - peer / competitor metrics (premium, rank, score, policies, growth, etc.).
            6. Peer product breakdown - peer metrics broken down by product / line of business.
            7. Peer attribute-level information or any other peer breakdowns - peer segmention by attribute / dimension.
            8. Marsh-level information - Marsh-level (book of business / placements, premiums) measures.
            9. Marsh-level breakdowsn - Marsh metric broken down by product, industry, region, or any other dimension present in the evidence.

            For each extracted_metrics item, the context field must clearly state which layer it belongs to (e.g. "KPI", "Carrier", "Carrier product breakdown", "Carrier attribute breakdown", "Peer", "Peer product breakdown", "Peer attribute breakdown", "Marsh", "Marsh breakdown") so the downstream report can group them.
            Do not invent values for layers that are not represented in the SQL output.

            Question result:
            {self._json_for_prompt(result)}
            """.strip()

            try:
                # Fast tier: per-question evidence extraction is a focused,
                # schema-bound pass. Aliases llm until MODEL_TIERS=on.
                structured_llm = Initialization.llm_fast.with_structured_output(
                    PitchExtractedInsight
                )
                response = structured_llm.invoke(
                    [
                        SystemMessage(
                            content="You return only structured, evidence-grounded insights."
                        ),
                        HumanMessage(content=prompt),
                    ],
                )
                logger.debug("Extracted insight response: %s", response)
                insight = self._dump_model(response)
                if not insight:
                    insight = self._fallback_extracted_insight(
                        result, "Structured response was empty."
                    )

            except Exception as e:
                log_event(
                    logger,
                    "pitch_insight_extraction_error",
                    logging.ERROR,
                    error=str(e),
                )
                insight = self._fallback_extracted_insight(
                    result, "Structured response was empty."
                )

            result["extracted_insight"] = insight
            extracted_insights.append(insight)

        state["pitch_extracted_insights"] = extracted_insights
        return state

    @staticmethod
    def _build_report_prompt(state: PitchAgentState) -> str:
        theme_label = state.get(
            "pitch_theme_label"
        ) or PitchBuilderWorkflow.THEME_LABELS.get(
            state.get("pitch_theme") or "performance_pitch"
        )
        filters = state.get("pitch_filters") or {}
        answers = state.get("pitch_answers") or {}
        data_summary = state.get("pitch_data_summary") or {}

        answer_lines = "\n".join(
            f"- Question: {question} \n Answer: {answer or 'Not provided'}"
            for question, answer in answers.items()
        )

        return f"""
        You are a senior insurance consulting leader creating a one-page executive analysis builder report for leadership stakeholders.
        Your objective is to transform structured insurance insights into a concise, executive-grade consulting report that explains:
        - What is happening.
        - Why it matters.
        - Where the carrier is winning or underperforming
        - What strategic risk or opportunities exist.

        The report must feel like it was prepared by a senior insurance strategy consultant, not an AI summarizer.

        ==================================================
        FILTERS
        ==================================================
        - Country: {filters.get('country') or 'Not selected'}
        - Carrier: {filters.get('carrier') or 'Not selected'}
        - Year: {filters.get('year') or 'Not selected'}

        ==================================================
        EXTRACTED INSIGHTS
        ==================================================
        {PitchBuilderWorkflow._json_for_prompt(state.get("pitch_extracted_insights") or [])}

        ==================================================
        APPROVED NARRATIVE SPINE
        ==================================================
        A senior consultant has already decided the story. Expand THIS spine into the
        report below. Follow its through-line, lead with its ranked developments, and
        surface its tensions and whitespace. Do not contradict it or introduce claims
        beyond the evidence it cites.
        {PitchBuilderWorkflow._json_for_prompt(state.get("pitch_narrative_arc") or {})}

        ==================================================
        STRICT DATA GROUNDING RULES
        ==================================================

        - Use ONLY the provided evidence, extracted insights, and SQL-backed results.
        - Never invent:
        - Rankings
        - Market conditions
        - Competitive movements
        - Growth drivers
        - Numerical values
        - Business explanations
        - Never assume trends unless explicitly supported by evidence.
        - Every insight MUST be traceable to provided evidence.
        - If evidence is weak or unavailable, omit the claim.
        - Do not hallucinate market commentary.
        - Do not fabricate strategic recommendations unrelated to evidence.
        - Never compare against peers unless peer evidence is explicitly available.
        - Never assume competitive positioning without supporting evidence.

        ==================================================
        STRICT WRITING RULES
        ==================================================
        - Always include timeframe reference when describing decline or improvement (In and from year both).
        - Every sentence MUST be complete, grammatically correct, and end with a full stop.
        - Do NOT output sentence fragments or incomplete thoughts.
        - Each bullet must be a full sentence.
        - Avoid vague or generic consulting language.
        - Avoid overly long paragraphs.
        - Write in a confident consulting tone.
        - Whenever premium performance is discussed, write it as:
        "Carrier premium was <carrier premium>, compared with peer average premium of <peer average premium>, representing <percentage comparison/change>."

        ==================================================
        EXECUTIVE REASONING RULES
        ==================================================

        Before generating the report:

        1. Identify the most strategically important business developments.
        2. Detect major improvements or deteriorations.
        3. Compare current performance versus prior year wherever available (include year information for both current and previous year).
        4. Identify strongest and weakest product areas.
        5. Detect contradictions between premium growth and broker sentiment.
        6. Identify whether Share of Portfolio changes align with competitive positioning.
        7. Prioritize insights by business importance.
        8. Focus on executive-relevant movements rather than raw metric repetition.
        9. Build a coherent business narrative before writing.

        ==================================================
        INSIGHT PRIORITIZATION RULES
        ==================================================

        Prioritize insights in this order:

        1. Significant YoY movement.
        2. Major rank improvement or deterioration.
        3. Large premium movement.
        4. Significant broker perception movement.
        5. Strong or declining Share of Portfolio signals.
        6. Competitive outperformance or underperformance.
        7. Product-level momentum shifts.
        8. Service or claims-related concerns.
        9. Multi-product patterns.

        ==================================================
        WHITESPACE IDENTIFICATION RULES
        ==================================================

        - If the carrier has zero, null, or materially insignificant premium for a breakdown AND peers have non-zero premium for the same breakdown,
        classify the area as "whitespace".

        - Always use the exact term:
        "whitespace"

        - Never replace "whitespace" with:
        - untapped
        - unexploited
        - underpenetrated
        - uncaptured
        - whitespace opportunity
        - whitespace potential
        - or similar synonyms.

        - Use "whitespace" only when evidence supports:
        - carrier absence or near absence
        - combined with meaningful peer participation.

        - Whitespace may apply across:
        - products
        - industries
        - segments
        - sub-products
        - portfolio allocation areas.

        - When whitespace exists, explain the business implication concisely.

        ==================================================
        PRODUCT-LEVEL ANALYSIS RULES
        ==================================================

        For product-level analysis:

        - Identify the strongest and weakest products.
        - Compare Share of Portfolio, growth, premium, and perception signals by product.
        - Highlight products showing:
        - Strong momentum
        - Weakening position
        - High strategic importance
        - Competitive advantage
        - Share of Portfolio expansion
        - Share of Portfolio reduction
        - Mention YoY movement wherever available.
        - Identify products with conflicting signals:
        - High premium but weak perception
        - Strong perception but declining growth
        - Focus on products materially impacting business performance.
        - Avoid listing every product unless meaningful evidence exists.
        - Prioritize commercially important products.
        - Identify whitespace products where peer presence exists but carrier premium is zero or materially insignificant.
        - Highlight whitespace only when peer-backed evidence exists.
        - Explain whitespace in terms of growth opportunity or portfolio gap.

        ==================================================
        TOP 5 COMPETITOR COMPARISON RULE:
        ==================================================
        - Do not report percentage differences alone.
        - Always include the carrier's actual premium value alongside the Top 5 competitor benchmark.

        BENCHMARK DISPLAY RULE:
        - For each comparison, present:
        1. Carrier premium value
        2. Top 5 competitor average premium value
        3. Premium gap (absolute value)
        4. Percentage difference, if available

        NARRATIVE RULE:
        - Explain the carrier's position relative to the Top 5 competitors using both premium values and percentage comparisons.
        - Emphasize whether the carrier is above, near, or below the Top 5 benchmark based on actual premium values, not percentages alone.

        OUTPUT EXAMPLE STYLE:
        - "The carrier generated premium of X compared with the Top 5 competitor average of Y, resulting in a premium gap of Z (A%)."

        DATA SAFETY RULE:
        - Use only values explicitly provided in the SQL-backed evidence.
        - Do not estimate competitor averages, premium gaps, or rankings.

        ==================================================
        PEER COMPARISON RULES
        ==================================================

        When peer evidence is available:

        - For peer comparison, do NOT show only percentages.
            - Always include both:
            1. Carrier actual premium value
            2. Peer average premium value
            3. Percentage difference or change, if available.
        - Compare carrier performance against peers across products.
        - Highlight products where the carrier outperforms peers.
        - Highlight products where the carrier underperforms peers.
        - Mention YoY peer comparison where available.
        - Identify whether competitive positioning is improving or weakening.
        - Do not disclose individual peer names or individual peer values.
        - Keep peer commentary aggregated and confidentiality-safe.

        ==================================================
        MARSH COMPARISON RULES
        ==================================================

        When Marsh evidence is available:

        - Compare carrier Share of Portfolio and premium against Marsh across each product.
        - Highlight products where the carrier is aligned with Marsh.
        - Highlight products where the carrier is under-indexed or over-indexed versus Marsh.
        - Mention change from last year where available.
        - Explain what the difference implies for opportunity, focus, or strategic alignment.

        ==================================================
        SURVEY AND ATTRIBUTE RULES
        ==================================================

        When survey evidence is available:

        - Summarize overall score, rank, and YoY movement.
        - Highlight strongest and weakest sections.
        - Mention top and bottom attributes only when they explain performance.
        - Do not overload the report with all attributes.
        - Convert attribute findings into business meaning.
        - Connect weak attributes to broker experience, service quality, or relationship risk where evidence supports it.


        ==================================================
        CONSULTING STYLE RULES
        ==================================================

        - Write like a senior insurance consulting leader.
        - Write in very easy to understand language.
        - Explain business meaning, not just metrics.
        - Translate data into strategic interpretation.
        - Connect related insights into business narratives.
        - Use executive storytelling.
        - Focus on implications and directionality.
        - Avoid sounding like a dashboard summary.
        - Every important metric should explain:
        - Why it matters.
        - What it implies.
        - What leadership should pay attention to.

        ==================================================
        IMPORTANT NUMERIC RULES
        ==================================================

        Whenever Premium appears:
        - Include Premium amount in USD if available.
        - Pair Premium with:
        - Growth %
        - Share of Wallet %
        - Share of Portfolio %
        - Variance %
        - Rank movement
        Where evidence exists.

        Do not overload sections with excessive numbers.
        Use metrics only when they strengthen executive understanding.

        ==================================================
        FINAL OUTPUT FORMAT
        ==================================================

        Return EXACTLY the following sections.
        1. Executive Summary
        A. Premium Performance Perspective
        - 2–3 sentences.
        - Summarize premium performance, policy movement, rank movement, product growth, Share of Portfolio trends, and competitive positioning.
        - Mention major YoY movement where available.
        - Focus on business growth and market positioning.

        B. Broker Perspective
        - 2–3 sentences.
        - Summarize survey score, strongest and weakest sections, strong or weak attributes, and relationship positioning.
        - Focus on perception, service quality, and broker experience.

        2. Product-Level Analysis
        - 4–6 bullet points or short paragraphs.
        - Summarize strongest and weakest products.
        - Highlight product Share of Portfolio, growth, and positioning trends.
        - Mention strategic product opportunities or risks.

        3. Carrier Comparison with Peers
        - 3–5 sentences or bullet points.
        - Compare carrier performance against peer benchmarks where evidence exists.
        - Highlight areas of competitive strength and weakness.
        - Mention relative positioning across:
        - Premium growth
        - Share of Portfolio
        - Share of Wallet
        - Broker perception (Score)
        - Rank
        - Product performance
        - Identify whether the carrier is gaining or losing competitive positioning.
        - Highlight where peers materially outperform the carrier.
        - Highlight where the carrier demonstrates competitive advantage.

        4. Carrier Comparison with Top 5 Carriers
        - 3-5 sentences or bullet points
        - Identify whether the carrier is above, near, or below the Top 5 benchmark based on actual premium values, not percentages alone.

        5. Whitespace Analysis
        - 3-5 bullet points.
        - Use the EXACT term "whitespace" (never untapped/underpenetrated/uncaptured).
        - Identify product, industry (SIC class), or segment slices where the carrier has zero, null, or materially insignificant premium WHILE the Marsh book (market) participates meaningfully.
        - For each whitespace slice, state the carrier premium (or its absence) alongside the market premium, and explain the portfolio gap / growth headroom.
        - Only claim whitespace where the evidence shows meaningful market participation. If no whitespace is evidenced, write one sentence saying so.

        6. Industry-Level Analysis
        - 3-5 bullet points or short paragraphs.
        - Summarize performance by industry (SIC Major Class) where evidence exists: premium, YoY movement, and share.
        - Call out the strongest and weakest industries and any concentration risk.
        - Mention YoY movement with both current and prior year where available.

        7. Segment Analysis
        - 3-5 bullet points or short paragraphs.
        - Summarize performance by client segment where evidence exists: premium, YoY movement, and share.
        - Highlight where the segment mix is shifting and where the carrier over- or under-indexes versus the market/peers.
        - Mention YoY movement with both current and prior year where available.
        """.strip()

    def build_narrative_arc(self, state: PitchAgentState) -> PitchAgentState:
        """Reason about the story BEFORE writing it.

        Turns the flat extracted insights + KPIs into a ranked 'story spine'
        (through-line, key developments, tensions, whitespace). The writer node
        then expands this spine into prose, which reads far more like a
        consultant's narrative than a single-pass metric dump.
        """
        extracted = state.get("pitch_extracted_insights") or []
        kpis = state.get("pitch_top_kpis") or {}
        filters = state.get("pitch_filters") or {}

        prompt = f"""
        You are a senior insurance strategy consultant planning a one-page carrier report.
        From the evidence below, decide the STORY before any prose is written.

        Filters — Carrier: {filters.get('carrier') or 'N/A'}, Country: {filters.get('country') or 'N/A'}, Year: {filters.get('year') or 'N/A'}

        Rules:
        - Ground every development in the extracted evidence. Never invent numbers, ranks, products, or causes.
        - Rank developments by business importance (significant YoY moves, rank shifts, large premium moves, perception swings, Share of Portfolio signals, competitive position, product momentum).
        - Surface genuine tensions/disconnects (e.g. premium up but broker perception down; premium up but Share of Wallet down).
        - Flag whitespace only where the carrier is absent/insignificant AND peers participate, per the evidence.
        - Refer to peers only in aggregate; never name an individual peer.

        TOP KPIS:
        {self._json_for_prompt(kpis)}

        EXTRACTED INSIGHTS:
        {self._json_for_prompt(extracted)}
        """.strip()

        arc: dict[str, Any] = {}
        try:
            # Reason tier: the narrative spine is the report's core reasoning step
            # — everything downstream expands it. Aliases llm_creative until ON.
            structured_llm = Initialization.llm_reason.with_structured_output(
                PitchNarrativeArc
            )
            response = structured_llm.invoke(
                [
                    SystemMessage(
                        content="You build a tight, evidence-grounded narrative spine for an executive insurance report."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            arc = self._dump_model(response) or {}
            Initialization.log_prompt_cache_usage(arc, "pitch_narrative_arc")
        except Exception as e:
            log_event(logger, "pitch_narrative_arc_error", logging.ERROR, error=str(e))
            arc = {}

        state["pitch_narrative_arc"] = arc
        return state

    @staticmethod
    def _pitch_skill_query(state: PitchAgentState) -> str:
        """Trigger text for pitch-scope skill matching.

        The pitch report has no single user query, so join the questions,
        answers, and extracted insights — this lets trigger-based skills (e.g.
        Share of Portfolio) fire when the report content actually involves them.
        `always: true` skills (confidentiality) match regardless.
        """
        parts: list[str] = list(state.get("pitch_questions") or [])
        parts.extend(str(v) for v in (state.get("pitch_answers") or {}).values())
        parts.append(
            json.dumps(state.get("pitch_extracted_insights") or [], default=str)
        )
        return " ".join(p for p in parts if p)

    def generate_report_summary(self, state: PitchAgentState) -> PitchAgentState:
        prompt = self._build_report_prompt(state)

        # Inject pitch-scope skills (Share of Portfolio definition, peer
        # confidentiality) so the report obeys the same authoritative rules as
        # the chat flows instead of relying solely on the hardcoded prompt.
        skill_rules = get_skill_loader().load_many(
            ["survey", "gpr"], "pitch", self._pitch_skill_query(state)
        )
        log_event(
            logger,
            "skill_load",
            node="pitch_report_summary",
            flow="pitch",
            scope="pitch",
            used_skills=bool(skill_rules),
        )
        if skill_rules:
            prompt = (
                f"{prompt}\n\n"
                "==================================================\n"
                "DOMAIN SKILL RULES (authoritative — override anything above on conflict)\n"
                "==================================================\n"
                f"{skill_rules}"
            )

        state["pitch_report_prompt"] = prompt

        try:
            # Reason tier: writing the executive report is the heaviest synthesis
            # in the pitch flow. Aliases llm_creative until MODEL_TIERS=on.
            response = Initialization.llm_reason.invoke(
                [
                    SystemMessage(
                        content=(
                            "You create comprehensive, evidence-grounded insurance pitch report content. "
                            "You never invent facts beyond the supplied question-answer inputs."
                        )
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            Initialization.log_prompt_cache_usage(response, "pitch_report_summary")
            state["pitch_report_summary"] = (response.content or "").strip()

            logger.debug(
                "Pitch report summary: %s", state["pitch_report_summary"]
            )

        except Exception as e:
            log_event(logger, "pitch_report_summary_error", logging.ERROR, error=str(e))
            state["pitch_report_summary"] = ""

        return state

    @staticmethod
    def _markdown_table(headers: list[str], rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            values = []
            for header in headers:
                value = row.get(header, "")
                values.append(str(value).replace("\n", " ").replace("|", "/"))
            lines.append("| " + " | ".join(values) + " |")
        return "\n".join(lines)

    @staticmethod
    def _rows_to_markdown(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        headers: list[str] = []
        seen: set = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    headers.append(str(key))
        if not headers:
            return ""
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized.append({h: row.get(h, "") for h in headers})
        return PitchBuilderWorkflow._markdown_table(headers, normalized)

    @staticmethod
    def _query_result_to_markdown(query_result: Any) -> str:
        if query_result is None:
            return ""
        if isinstance(query_result, list):
            return PitchBuilderWorkflow._rows_to_markdown(query_result)
        if isinstance(query_result, dict):
            premium_md = ""
            survey_md = ""
            if "premium" in query_result or "survey" in query_result:
                premium_rows = query_result.get("premium")
                survey_rows = query_result.get("survey")
                if isinstance(premium_rows, list):
                    premium_md = PitchBuilderWorkflow._rows_to_markdown(premium_rows)
                if isinstance(survey_rows, list):
                    survey_md = PitchBuilderWorkflow._rows_to_markdown(survey_rows)
                parts: list[str] = []
                if premium_md:
                    parts.append("**Premium**\n" + premium_md)
                if survey_md:
                    parts.append("**Survey**\n" + survey_md)
                return "\n\n".join(parts)
            return PitchBuilderWorkflow._rows_to_markdown([query_result])
        return ""

    def build_query_markdown(self, state: PitchAgentState) -> PitchAgentState:
        question_results = state.get("pitch_question_results") or []
        markdown_dict: dict[str, str] = {}
        for result in question_results:
            question = str(result.get("question") or "").strip()
            if not question:
                continue
            md = self._query_result_to_markdown(result.get("pitch_query_result"))
            if md:
                markdown_dict[question] = md
        state["pitch_query_markdown"] = markdown_dict
        return state

    def compute_top_kpis(self, state: PitchAgentState) -> PitchAgentState:
        extracted = state.get("pitch_extracted_insights") or []
        filters = state.get("pitch_filters") or {}
        carrier = filters.get("carrier") or ""
        country = filters.get("country") or ""
        year = filters.get("year") or ""

        prompt = f"""
        You are an insurance analytics KPI extractor. Produce the headline KPI title values for a report.

        Hard rules:
        - Use ONLY items from extracted_metrics whose starts with "KPI" or "Carrier".
        - IGNORE any items whose context starts with "Peer", "Marsh", "Carrier product breakdown", or "Carrier attribute".
        - Do not aggregate, sum, or average across peer or Marsh-level items into a carrier-level field.
        - Preserve formatting from the evidence (currency symbols, % signs, signs).
        - Leave a field as an empty string if no carrier-level evidence supports it. Do not guess.
        - total_premium must be the carrier's own current year premium (not Marsh book and not peer average).
        - yoy must be the carrier's own YoY growth %.
        - rank, rank_delta, last_year_rank must be the carrier's own ranks.
        - score is the carrier's own overall survey score.
        - policies is the carrier's own policy count for current year.

        Filters (for disambiguation only):
        - Carrier: {carrier}
        - Country: {country}
        - Year: {year}

        Extracted insights (already labelled by layer in each metric's context):
        {self._json_for_prompt(extracted)}
        """.strip()

        top_kpis: dict[str, Any] = {}
        try:
            # Fast tier: headline KPI extraction is a constrained lookup over
            # already-labelled metrics. Aliases llm until MODEL_TIERS=on.
            structured_llm = Initialization.llm_fast.with_structured_output(PitchTopKPIs)
            response = structured_llm.invoke(
                [
                    SystemMessage(
                        content="You return only structured, evidence-grounded carrier-only KPI values."
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            top_kpis = self._dump_model(response) or {}
            Initialization.log_prompt_cache_usage(top_kpis, "compute_top_kpis")

        except Exception as e:
            log_event(logger, "pitch_top_kpis_error", logging.ERROR, error=str(e))
            top_kpis = {}

        state["pitch_top_kpis"] = top_kpis
        return state

    def generate_pitch_questions(self, state: PitchAgentState) -> PitchAgentState:
        """Build the derived analytical battery for the report via the lens planner.

        In "comprehensive" mode the planner expands the carrier/country/year
        filters into the full set of relevant derived analyses (market, peer,
        trend, product/industry mix, whitespace, opportunity, contradictions).
        Each becomes a pitch question answered multi-step by the analyst agent.
        Manually supplied questions are appended after the derived battery.
        """
        filters = state.get("pitch_filters") or {}
        carrier = filters.get("carrier")
        country = filters.get("country")
        year = filters.get("year")
        manual = [q.strip() for q in (state.get("pitch_questions") or []) if (q or "").strip()]

        slice_text = " ".join(
            part
            for part in [
                f"for {carrier}" if carrier else "",
                f"in {country}" if country else "",
                f"for year {year}" if year else "",
            ]
            if part
        ).strip()
        seed_query = (
            f"Comprehensive performance pitch {slice_text}. Assess premium and "
            "growth, market position versus the Marsh book, peer benchmark, "
            "product, industry (SIC class) and client-segment mix, whitespace and "
            "growth opportunities by product/industry/segment, and any "
            "perception-versus-financial tensions."
        )

        routing_context = RoutingContext(
            table_family="both",
            inherited_carrier=carrier,
            inherited_country=country,
            inherited_year=str(year) if year else None,
            intent_type="new_question",
            analysis_depth="analytical",
        )

        plan = plan_analysis(seed_query, routing_context, mode="comprehensive")
        derived = [
            d.sub_question.strip() for d in plan.derived if (d.sub_question or "").strip()
        ]

        questions = derived + [q for q in manual if q not in derived]
        if not questions:
            questions = manual or [seed_query]

        log_event(
            logger,
            "pitch_questions_generated",
            node="generate_pitch_questions",
            derived=len(derived),
            manual=len(manual),
            total=len(questions),
        )
        state["pitch_questions"] = questions
        return state

    def create_workflow(self):
        workflow = StateGraph(PitchAgentState)
        workflow.add_node("generate_pitch_questions", self.generate_pitch_questions)
        workflow.add_node("generate_pitch_answers", self.generate_answers)
        workflow.add_edge(START, "generate_pitch_questions")
        workflow.add_edge("generate_pitch_questions", "generate_pitch_answers")
        workflow.add_edge("generate_pitch_answers", END)
        return workflow.compile(checkpointer=self.checkpointer)

    def trigger_workflow(self, state: PitchAgentState) -> PitchAgentState:
        pitch_thread_id = state.get("pitch_thread_id") or uuid.uuid4().hex[:12]
        state["pitch_thread_id"] = pitch_thread_id
        if self._workflow_app is None:
            self._workflow_app = self.create_workflow()
        return self._workflow_app.invoke(
            state, config=checkpoint_config(f"{pitch_thread_id}:answers")
        )

    def create_report_workflow(self):
        workflow = StateGraph(PitchAgentState)
        workflow.add_node("extract_question_insights", self.extract_question_insights)
        workflow.add_node("compute_top_kpis", self.compute_top_kpis)
        workflow.add_node("build_narrative_arc", self.build_narrative_arc)
        workflow.add_node("generate_pitch_report_summary", self.generate_report_summary)

        # extract evidence → headline KPIs → reason the story spine → write the report
        workflow.add_edge(START, "extract_question_insights")
        workflow.add_edge("extract_question_insights", "compute_top_kpis")
        workflow.add_edge("compute_top_kpis", "build_narrative_arc")
        workflow.add_edge("build_narrative_arc", "generate_pitch_report_summary")
        workflow.add_edge("generate_pitch_report_summary", END)
        return workflow.compile(checkpointer=self.checkpointer)

    def trigger_report_workflow(self, state: PitchAgentState) -> PitchAgentState:
        pitch_thread_id = state.get("pitch_thread_id") or uuid.uuid4().hex[:12]
        state["pitch_thread_id"] = pitch_thread_id
        if self._report_workflow_app is None:
            self._report_workflow_app = self.create_report_workflow()
        return self._report_workflow_app.invoke(
            state, config=checkpoint_config(f"{pitch_thread_id}:report")
        )
