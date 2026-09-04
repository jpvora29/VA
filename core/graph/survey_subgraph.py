"""Survey LangGraph subgraph: normalizer → planner → analytics tools → (SQL + fixer loop).

The analytics-tool node answers the turn by CALLING the deterministic primitive
library; the LLM-SQL path below it is the fallback for questions the library does
not cover. Set ``ANALYTICS_TOOLS=off`` to restore the pure SQL path.
"""
from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy.sql import text

from config.valid_values_config import *  # noqa: F401,F403 - preserves legacy globals
from core.agents.common import (
    BaseSQLFixerNode,
    analytics_covered,
    annotate_plan_notes,
    log_sql_failure,
    recalled_sql_examples,
    record_recovered_sql_fix,
    run_analytics_tools,
)
from core.agents.common.contract import resolved_filters_of
from core.agents.common.directives import charts_suppressed
from core.agents.common.peer_privacy import redactor_for
from core.agents.common.peers import custom_peer_directive
from core.mcp.tools import execute_sql
from core.agents.survey.chart import SurveyChartNode
from core.agents.survey.planner import PlannerNode
from core.agents.survey.sql_agent import SQLAgentNode
from core.data.general import GeneralFunctions
from core.data.valid_values import GetValidData
from core.initialization import Initialization
from core.observability import latency_timer, log_event, sql_metadata
from core.rules.survey import SurveyRules
from core.rules.survey_chart import SurveyChartRules
from core.schemas.survey import (
    SurveyColumnSelectorAgent,
    SurveyQueryNormalizer,
    SurveySQLJoinChecker,
)
from core.skills import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class SurveySubGraph:

    def survey_normalizer_agent(state: AgentState) -> AgentState:
        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)

        system_prompt = """
        [ROLE]
        You are the Normalization Agent in an agentic SQL workflow.
        Your purpose is to clean and normalize the user query so that all column names and entity values exactly match the valid names from the provided schema and valid value list.
        You should keep the query meaning, structure, and tone fully intact — only replace or correct names that do not match valid schema or valid values.

        [INPUTS]
        - user_query: The natural language query from the user.
        - schema: List of valid column names in the table.
        - valid_values: Dictionary mapping column names to lists of valid entries.

        [OBJECTIVE]
        Return the **normalized query** where:
        1. Column names are replaced with their closest valid schema names (using fuzzy or semantic matching).
        2. Entity or filter values are replaced with their closest valid names (e.g., “Cananda” → “Canada”, “Chub” → “Chubb”).
        3. If a name is already valid, keep it unchanged.
        4. Do not modify numbers, operators, or time references.
        5. Do not alter the question wording or structure beyond replacing names.
        6. Do not invent new columns or values.
        7. If everything is already correct, return the query exactly as received.
        8. `Marsh` is a insurance broker, do not treat it as Carrier or Client and try to apply fuzzy logic or match with any Carrier, Client or anything.

        [STYLE]
        - Be precise and minimal — your output should look identical to the input except for corrected terms.
        - Do not explain what was corrected.
        - Output **only the updated query text** — no metadata, no lists, no JSON.

        [EXAMPLES]

        Example 1:
        User Query: "Show me score of zurich in singpore for property for the year 2025"
        Schema: ["Carrier", "SurveyCountry", "SurveyPractice", "Score", "Survey_Year"]
        Valid Values:
        - Country: ["Singapore", "Canada", "USA"]
        - Carrier: ["Zurich", "Chubb", "AIG"]
        - Product_Line: ["Property", "Casualty", "FINPRO"]

        Output: "Show me Score of Zurich in Singapore for Property for the Survey_Year 2025"

        ---

        Example 2:
        User Query: "score of chub in canad across all segments"
        Output: "Score of Chubb in Canada across all SurveySegment"

        ---

        """

        messages = [
            SystemMessage(content=system_prompt),
            GeneralFunctions.build_human_message(
                user_query=question,
                schema=schema,
                valid_values_survey=GetValidData.valid_values,
                is_survey=True,
            ),
        ]

        structured_llm = Initialization.llm.with_structured_output(
            SurveyQueryNormalizer
        )
        response = structured_llm.invoke(messages)

        Initialization.log_prompt_cache_usage(response, "survey_normalizer_agent")

        last_msg = state["messages"][-1]
        # state["messages"][-1] = HumanMessage(content=response.normalized_query)

        logger.debug("Survey normalized question: %s", response.normalized_query)

        return {
            "messages": [
                RemoveMessage(id=last_msg.id),
                HumanMessage(content=response.normalized_query),
            ]
        }

    def survey_column_selector_agent(state: AgentState) -> AgentState:
        # question = state['question']
        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)

        system_prompt = """
        You are a Column Selector Agent specialized in Insurance and Risk Consulting data, particularly survey, peer performance datasets.
        Your task is to analyze a user’s natural language query and identify most relevant columns from the provided schema that can answer the user's query, using insurance-specific understanding of terms
        such as score (ranging from 1-9), nps score (ranging from -100 to 100) attributes, segments, sections.

        Input Provided:
        - The rephrased query in clear English
        - List of schema column names
        - Definition for the `GPR` table columns

        Rules:
        1. Map user intent to the exact column names from the schema.
        2. If query asks for a breakdown ("across products", "by attributes"), include that column as well.
        3. Always return output as a list of valid column names.
        4. If query mentions YoY, growth, SoW, appetite, rolling 12M, month-on-month include the `Premium` along with the requested column(s).
        5. Do not invent new columns.

        Output only JSON list:
        Example: []

        """
        messages = [
            SystemMessage(content=system_prompt),
            GeneralFunctions.build_human_message(
                user_query=question,
                schema=schema,
                definitions_survey=GetValidData.definitions,
                is_survey=True,
            ),
        ]

        structured_llm = Initialization.llm.with_structured_output(
            SurveyColumnSelectorAgent
        )
        response = structured_llm.invoke(messages)

        # state["survey_cols"] = response.columns

        logger.debug("Survey selected columns: %s", response.columns)

        return {"survey_cols": response.columns}

    def survey_planner_node(state: AgentState) -> AgentState:

        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
        carriers_schema = schema.get("Carriers", [])
        peers_schema = schema.get("Peers", [])

        # Phase 2: prefer skill-md progressive disclosure; fall back to the
        # legacy SurveyRules.planner_rules bundle if no skills match (or the
        # skills directory is empty).
        skill_rules = get_skill_loader().planner("survey", question)
        planner_rules = skill_rules if skill_rules else SurveyRules.planner_rules
        log_event(
            logger,
            "skill_load",
            node="survey_planner",
            flow="survey",
            scope="planner",
            used_skills=bool(skill_rules),
        )

        planner_node = PlannerNode(
            carriers_schema=carriers_schema,
            peers_schema=peers_schema,
            rules=planner_rules,
        )
        plan = planner_node(
            user_query=question,
            routing_context=state.get("routing_context"),
            valid_year_quarter=valid_years,
        )

        # Deterministic, advisory grounding check (never blocks the flow).
        plan = annotate_plan_notes(
            plan,
            schema_tables={"Carriers": carriers_schema, "Peers": peers_schema},
            valid_values=GetValidData.valid_values,
            flow="survey",
        )

        # state["survey_reasoning"] = plan

        logger.debug("Survey reasoning plan: %s", plan)

        return {"survey_reasoning": plan}

    def survey_analytics_tools(state: AgentState) -> AgentState:
        """Answer the turn by calling the deterministic analytics primitives.

        Clears the coverage key when the library does not cover the question, which
        routes the turn to the LLM-SQL path below exactly as before.
        """
        return run_analytics_tools(state, flow="survey", engine=Initialization.engine)

    def survey_analytics_router(state: AgentState) -> str:
        """Computed facts skip SQL generation entirely; everything else falls back."""
        if analytics_covered(state, "survey"):
            return "survey_chart_data_creation"
        return "survey_convert_to_sql"

    def survey_convert_nl_to_sql(state: AgentState) -> AgentState:
        """Using LLM Converts the Natural Language Query to a SQL Query"""

        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(Initialization.engine)
        carriers_schema = schema.get("Carriers", [])
        peers_schema = schema.get("Peers", [])

        query_plan = state["survey_reasoning"]
        # Session-pinned custom peers override the Peers-table resolution for this
        # conversation. Inject only into the SQL agent's plan text — NOT into
        # `survey_reasoning`, which is re-parsed as JSON by survey_execute_sql.
        directive = custom_peer_directive(
            state.get("custom_peers"),
            "survey",
            active=state.get("custom_peers_active", False),
        )
        if directive:
            query_plan = f"{query_plan}\n\n{directive}"
        skill_rules = get_skill_loader().sql("survey", question)
        query_rules = skill_rules if skill_rules else SurveyRules.query_rules
        log_event(
            logger,
            "skill_load",
            node="survey_sql",
            flow="survey",
            scope="sql",
            used_skills=bool(skill_rules),
        )

        recalled = recalled_sql_examples(
            state.get("user_id"), "survey", question, k=3
        )

        sql_agent = SQLAgentNode(
            carrier_schema=carriers_schema,
            peer_schema=peers_schema,
            rules=query_rules,
            few_shot=SurveyRules.survey_query_few_shots + recalled,
        )

        sql_query_output = sql_agent(
            user_query=question,
            query_plan=query_plan,
            valid_year_quarter=valid_years,
        )

        # state["survey_sql_query"] = sql_query_output

        logger.debug("Survey SQL query: %s", sql_query_output)

        return {"survey_sql_query": sql_query_output}

    def survey_execute_sql(state: AgentState) -> AgentState:
        """Executes the SQL Query for the survey data via the shared execute_sql tool.

        The tool owns validation, execution, and logging. Survey-specific
        post-processing (`clean_sql_output`, which needs the reasoning plan, and
        the list-wrapped `:-` error convention the downstream nodes expect) stays
        here. Overflow is recomputed on the *cleaned* rows, matching prior behavior.
        """

        sql_query = state["survey_sql_query"].strip()
        result = execute_sql("survey", sql_query, node="survey_execute_sql")

        if result.error:
            return {
                "survey_query_result": [f"Error executing SQL query:- {result.error}"],
                "survey_sql_error": True,
                "survey_overflow": False,
            }

        record_recovered_sql_fix(state, route="survey", working_sql=sql_query)

        logger.debug("Survey query fetched %d row(s)", result.row_count)
        query_result = GeneralFunctions.clean_sql_output(
            sql_output=result.rows, reasoning=json.loads(state["survey_reasoning"])
        )
        # Peer confidentiality at the same boundary the analyst and the GPR rail
        # use — after cleaning, so the redactor sees the columns the UI will.
        query_result = redactor_for(
            "survey",
            resolved_filters_of(state.get("routing_context")),
            state.get("custom_peers"),
        ).rows(query_result)

        return {
            "survey_query_result": query_result,
            "survey_sql_error": False,
            "survey_overflow": len(query_result) > 40,
        }

    def survey_sql_join_rewriter(state: AgentState) -> AgentState:
        sql_query = state["survey_sql_query"].strip()

        system_prompt = """
        You are a SQL Rewriter Agent.
        Your task is to review the SQL query generated by another SQLAgent and ensure that it does not use any JOIN operations.

        Rules:
        1. If the SQL query contains a JOIN, you must rewrite it by removing the JOIN.
        2. Instead of JOINs, use subqueries with IN or EXISTS clauses.
        - Example:
            - Original:
            WITH top_carriers AS (
                SELECT Carrier, AVG(Score) AS avg_score
                FROM Carriers
                WHERE LOWER(SurveyCountry) = LOWER('singapore')
                AND Survey_Year = 2025
                GROUP BY Carrier
                ORDER BY avg_score DESC
                LIMIT 3
            )
            SELECT tc.Carrier, c.Attribute, AVG(c.Score) AS avg_attribute_score
            FROM top_carriers tc
            JOIN Carriers c ON LOWER(c.Carrier) = LOWER(tc.Carrier)
            WHERE LOWER(c.SurveyCountry) = LOWER('singapore')
            AND c.Survey_Year = 2025
            GROUP BY tc.Carrier, c.Attribute
            ORDER BY tc.Carrier, avg_attribute_score DESC;

            - Rewritten:
                    SELECT Carrier, AVG(Score) AS avg_score
                            FROM Carriers
                            WHERE LOWER(SurveyCountry) = LOWER('singapore')
                            AND Survey_Year = 2025
                            GROUP BY Carrier
                            ORDER BY avg_score DESC
                            LIMIT 3
                        )
                    SELECT
                        c.Carrier,
                        c.Attribute,
                        AVG(c.Score) AS attribute_average_score
                            FROM Carriers c
                            WHERE c.Carrier IN (SELECT Carrier FROM top_carriers)
                            AND LOWER(c.SurveyCountry) = LOWER('singapore')
                            AND c.Survey_Year = 2025
                            GROUP BY c.Carrier, c.Attribute
                            ORDER BY attribute_average_score DESC;

        3. Preserve all SELECT columns and filtering conditions.
        4. The rewritten query must produce logically equivalent results without using JOIN.
        5. If no JOIN is present, return the query unchanged.
        6. Always output only the final valid SQL query — no explanations, no comments.

        Special Considerations:
        - Handle multiple JOINs by nesting IN subqueries.
        - Ensure case insensitivity (JOIN, join, inner join → all treated the same).
        - Keep formatting compact (single-line or minimal spacing).

        Output format:
        Return only the rewritten SQL query.

    """

        human_message = f"""
            SQL Query: {sql_query}
        """

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]

        structured_llm = Initialization.llm.with_structured_output(SurveySQLJoinChecker)
        response = structured_llm.invoke(messages)

        # state["survey_sql_query"] = response.updated_query

        logger.debug("Survey join-rewritten query: %s", response.updated_query)

        return {"survey_sql_query": response.updated_query}

    def survey_sql_fixer_agent(state: AgentState) -> AgentState:

        sql_query = state["survey_sql_query"].strip()
        question = state["messages"][-1].content
        error_message = state["survey_query_result"]

        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
        survey_schema = schema.get("Carriers", [])
        peer_schema = schema.get("Peers", [])

        log_event(
            logger,
            "sql_fix_attempt",
            route="survey",
            node="survey_sql_fixer_agent",
            sql=sql_metadata(sql_query),
            error=str(error_message),
        )

        fixer = BaseSQLFixerNode(flow="survey")
        corrected_query = fixer.fix(
            user_query=question,
            schema_tables={"Carriers": survey_schema},
            peer_schema=peer_schema,
            sql_query=sql_query,
            error_message=error_message,
            valid_values=GetValidData.valid_values,
            definitions=GetValidData.definitions,
        )

        return {
            "survey_sql_query": corrected_query,
            "survey_attempts": 1,
            **log_sql_failure(question, sql_query, error_message, "survey"),
        }

    def survey_end_max_iterations(state: AgentState) -> AgentState:
        # state["survey_query_result"] = "Please try again !"
        log_event(
            logger,
            "sql_fix_max_attempts",
            logging.WARNING,
            route="survey",
            node="survey_end_max_iterations",
        )
        return {"survey_query_result": "Plase try again later !"}

    def survey_check_attempts_router(state: AgentState):
        if state["survey_attempts"] < 3:
            return "survey_execute_sql"
        else:
            return "survey_end_max_iterations"

    def survey_execute_sql_router(state: AgentState):
        if not state.get("survey_sql_error", False):
            return "survey_chart_data_creation"
        else:
            return "survey_sql_fixer_agent"

    def survey_check_if_join_required_router(state: AgentState) -> AgentState:
        if re.search(r"(?i)join", state["survey_sql_query"]):
            logger.debug("Survey join router -> survey_sql_join_rewriter")
            return "survey_sql_join_rewriter"
        logger.debug("Survey join router -> survey_execute_sql")
        return "survey_execute_sql"

    def survey_chart_data_creation(state: AgentState) -> AgentState:
        survey_query_output = state.get("survey_query_result")
        question = state["messages"][-1].content

        # Query-contract gate: an explicit "no chart" directive wins outright.
        if charts_suppressed(state.get("routing_context")):
            log_event(
                logger,
                "charts_suppressed_by_directive",
                route="survey",
                node="survey_chart",
            )
            return {}

        # Guard: only chart a genuine, non-empty result set. On a SQL error the
        # result is a list-wrapped error string; on overflow / no rows skip
        # charting (no-op) so the fixer/overflow paths are unaffected.
        if (
            not isinstance(survey_query_output, list)
            or not survey_query_output
            or state.get("survey_sql_error", False)
            or state.get("survey_overflow", False)
        ):
            return {}

        survey_query_output_updated = survey_query_output
        logger.debug("Survey chart input rows: %s", survey_query_output_updated)
        skill_rules = get_skill_loader().chart("survey", question)
        chart_rules = skill_rules if skill_rules else SurveyChartRules.chart_creation_rules
        log_event(
            logger,
            "skill_load",
            node="survey_chart",
            flow="survey",
            scope="chart",
            used_skills=bool(skill_rules),
        )
        survey_chart_creation_agent = SurveyChartNode(
            chart_creation_rules=chart_rules
        )
        survey_chart_data = survey_chart_creation_agent(
            user_query=question, sql_output=survey_query_output_updated
        )
        logger.debug("Survey chart data: %s", survey_chart_data)
        # state['survey_chart'] = survey_chart_data

        # return state
        return {"survey_chart": survey_chart_data}

    survey_graph = StateGraph(AgentState)

    survey_graph.add_node("survey_normalizer_agent", survey_normalizer_agent)
    # survey_graph.add_node("survey_column_selector_agent", survey_column_selector_agent)
    survey_graph.add_node("survey_planner", survey_planner_node)
    survey_graph.add_node("survey_analytics_tools", survey_analytics_tools)
    survey_graph.add_node("survey_convert_to_sql", survey_convert_nl_to_sql)
    survey_graph.add_node("survey_execute_sql", survey_execute_sql)
    survey_graph.add_node("survey_chart_data_creation", survey_chart_data_creation)
    # survey_graph.add_node("survey_sql_join_rewriter", survey_sql_join_rewriter)
    survey_graph.add_node("survey_sql_fixer_agent", survey_sql_fixer_agent)
    survey_graph.add_node("survey_end_max_iterations", survey_end_max_iterations)

    survey_graph.add_edge(START, "survey_normalizer_agent")
    # survey_graph.add_edge("survey_normalizer_agent", "survey_column_selector_agent")
    survey_graph.add_edge("survey_normalizer_agent", "survey_planner")
    survey_graph.add_edge("survey_planner", "survey_analytics_tools")

    survey_graph.add_conditional_edges(
        "survey_analytics_tools",
        survey_analytics_router,
        {
            "survey_chart_data_creation": "survey_chart_data_creation",
            "survey_convert_to_sql": "survey_convert_to_sql",
        },
    )

    survey_graph.add_edge("survey_convert_to_sql", "survey_execute_sql")

    # survey_graph.add_conditional_edges(
    #     "survey_convert_to_sql",
    #     survey_check_if_join_required_router,
    #     {
    #         "survey_sql_join_rewriter": "survey_sql_join_rewriter",
    #         "survey_execute_sql": "survey_execute_sql",
    #     },
    # )

    # survey_graph.add_edge("survey_sql_join_rewriter", "survey_execute_sql")

    survey_graph.add_conditional_edges(
        "survey_execute_sql",
        survey_execute_sql_router,
        {
            "survey_chart_data_creation": "survey_chart_data_creation",
            "survey_sql_fixer_agent": "survey_sql_fixer_agent",
        },
    )

    survey_graph.add_conditional_edges(
        "survey_sql_fixer_agent",
        survey_check_attempts_router,
        {
            "survey_execute_sql": "survey_execute_sql",
            "survey_end_max_iterations": "survey_end_max_iterations",
        },
    )

    survey_graph.add_edge("survey_chart_data_creation", END)
    survey_graph.add_edge("survey_end_max_iterations", END)

    SurveyAgent = survey_graph.compile()
    # mermaid_code = SurveyAgent.get_graph().draw_mermaid()
    # print(f"Survey Data Graph: {mermaid_code}\n")
