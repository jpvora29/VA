"""Survey LangGraph subgraph: normalizer → planner → SQL → execute (+ fixer loop)."""
from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy.sql import text

from config.valid_values_config import *  # noqa: F401,F403 - preserves legacy globals
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
    SurveyCheckSQLOutput,
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

        print(f"Normalized User Question: {response.normalized_query}")

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

        print(f"Selected columns are: {response.columns}")

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
            definitions=GetValidData.definitions,
            rules=planner_rules,
        )
        plan = planner_node(user_query=question)

        # state["survey_reasoning"] = plan

        print(f"Reasoning Plan for Survey Data: {plan}")

        return {"survey_reasoning": plan}

    def survey_convert_nl_to_sql(state: AgentState) -> AgentState:
        """Using LLM Converts the Natural Language Query to a SQL Query"""

        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(Initialization.engine)
        carriers_schema = schema.get("Carriers", [])
        peers_schema = schema.get("Peers", [])

        query_plan = state["survey_reasoning"]
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

        sql_agent = SQLAgentNode(
            carrier_schema=carriers_schema,
            peer_schema=peers_schema,
            rules=query_rules,
            few_shot=SurveyRules.survey_query_few_shots,
        )

        sql_query_output = sql_agent(user_query=question, query_plan=query_plan)

        # state["survey_sql_query"] = sql_query_output

        print(f"SQL Query for Survey Data: {sql_query_output}")

        return {"survey_sql_query": sql_query_output}

    def survey_execute_sql(state: AgentState) -> AgentState:
        """Executes the SQL Query for the survey data"""

        sql_query = state["survey_sql_query"].strip()
        session = Initialization.Session()

        log_event(
            logger,
            "sql_execute_start",
            route="survey",
            node="survey_execute_sql",
            sql=sql_metadata(sql_query),
        )
        timing = {}
        try:
            with latency_timer() as timing:
                result = session.execute(text(sql_query))
                rows = result.fetchall()
                columns = result.keys()

            if rows:
                # header = ", ".join(columns)
                query_result = [dict(zip(columns, row)) for row in rows]
                print(f"Raw SQL Query Result For Survey Data: {query_result}")

            else:
                query_result = []

            is_error = False

            query_result = GeneralFunctions.clean_sql_output(
                sql_output=query_result, reasoning=json.loads(state["survey_reasoning"])
            )

            if len(query_result) > 40:
                is_dataOverflow = True

            else:
                is_dataOverflow = False
            log_event(
                logger,
                "sql_execute_end",
                route="survey",
                node="survey_execute_sql",
                sql=sql_metadata(
                    sql_query,
                    row_count=len(query_result),
                    duration_ms=timing.get("duration_ms"),
                ),
                overflow=is_dataOverflow,
            )

        except Exception as e:
            query_result = [f"Error executing SQL query:- {e}"]
            is_error = True
            is_dataOverflow = False
            log_event(
                logger,
                "sql_execute_error",
                logging.ERROR,
                route="survey",
                node="survey_execute_sql",
                sql=sql_metadata(sql_query, duration_ms=timing.get("duration_ms")),
                error=str(e),
            )

        finally:
            session.close()

        return {
            "survey_query_result": query_result,
            "survey_sql_error": is_error,
            "survey_overflow": is_dataOverflow,
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

        print(f"SQL Join Rewriting for: {state['messages'][-1]}")

        # state["survey_sql_query"] = response.updated_query

        print(f"Updated Without Join Query: {response.updated_query}")

        return {"survey_sql_query": response.updated_query}

    def survey_sql_fixer_agent(state: AgentState) -> AgentState:

        sql_query = state["survey_sql_query"].strip()
        # question = state['question']
        question = state["messages"][-1]
        error_message = state["survey_query_result"]

        print(f"Error message: {error_message}")

        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
        survey_schema = schema.get("Carriers", [])
        peer_schema = schema.get("Peers", [])

        system_prompt = """
        You are a SQL Error Fixer Agent.

        [R – Role]
        You act as a SQL expert who diagnoses errors in SQL lite queries and fixes them.
        You understand schemas, valid values, and typical SQL lite syntax errors.

        [E – Explicitness]
        - Input includes: user query, schema, definition (Carriers table columns), SQL lite query, error message, valid list of column values.
        - Your task: identify the cause of the error and return a corrected SQL lite query.
        - Never invent new filters or columns outside the schema.
        - Always ensure case-insensitivity for values (normalize them to valid ones).

        [A – Approach]
        1. Read the provided SQL query and error message.
        2. Compare the query with the schema and valid values.
        3. Identify the likely cause of the error (missing column, wrong alias, syntax issue, invalid filter, etc.).
        4. Fix the query step by step, ensuring it adheres to schema and business rules.
        5. Test mentally if the fixed query would avoid the error.

        [S – Scaffolding]
        Examples:
        - Error: “no such column: CarrierNme”
        Fix: Correct typo → `CarrierName`.

        - Error: “near ‘union’: syntax error”
        Fix: Ensure `ORDER BY` appears after `UNION ALL`.

        - Error: “no such table: Peers”
        Fix: Replace with correct table `PeerScores`.

        [O – Output Format]
        - Always return fixed SQL Query
        - Example:
        `{"SELECT Carrier, AVG(Score) FROM Carriers WHERE Country='Canada' GROUP BY CarrierName" }`

        [N – Nuances]
        - Apply fuzzy matching for column/value names (e.g., “Chub” → “Chubb”).
        - If peer average is mentioned, apply rules:
        - Use `Peers` table, get Peers list for Carrier, Country, Product combination, then apply filters in Carriers table.
        - Avoid unnecessary joins unless explicitly needed.
        - If unsure, choose the safest correction aligned with schema.
        - Do not output reasoning or explanation text, only the corrected SQL query.

        """

        human_message = f"""
        Usery Query: {question}
        Survey Schema: {survey_schema}
        Peer Schema: {peer_schema}
        Carrier Table Columns Definitions: {GetValidData.definitions}
        SQL Query: {sql_query}
        Error Message: {error_message}
        Valid Values:
            - SurveyCountry: {valid_countries}
            - Carrier: {valid_carriers}
            - Survey_Year: {valid_years}
            - SurveyPractice: {valid_practices}
            - Section: {valid_sections}
            - Attributes: {valid_attributes}
            - Region: {valid_regions}

        """

        print(f"Fixing the original query: {question}")

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]

        structured_llm = Initialization.llm.with_structured_output(SurveyCheckSQLOutput)
        corrected_response = structured_llm.invoke(messages)

        # state["survey_sql_query"] = corrected_response.updated_query
        # print(f"Total Attempts for far: {state['attempts']}")
        # state["survey_attempts"] += 1

        return {
            "survey_sql_query": corrected_response.updated_query,
            "survey_attempts": 1,
        }

    def survey_end_max_iterations(state: AgentState) -> AgentState:
        # state["survey_query_result"] = "Please try again !"
        print("Maximum attempts reached. Ending the workflow.")
        return {"survey_query_result": "Plase try again later !"}

    def survey_check_attempts_router(state: AgentState):
        if state["survey_attempts"] < 3:
            return "survey_execute_sql"
        else:
            return "survey_end_max_iterations"

    def survey_execute_sql_router(state: AgentState):
        # if not state.get("survey_sql_error", False):
        #     return "survey_chart_data_creation"
        # else:
        #     return "survey_sql_fixer_agent"
        if not state.get("survey_sql_error", False):
            return "end"
        else:
            return "survey_sql_fixer_agent"

    def survey_check_if_join_required_router(state: AgentState) -> AgentState:
        print("Check Join Router")
        if re.search(r"(?i)join", state["survey_sql_query"]):
            print("survey_sql_join_rewriter\n")
            return "survey_sql_join_rewriter"
        else:
            print("execute_sql\n")
            return "survey_execute_sql"

    def survey_chart_data_creation(state: AgentState) -> AgentState:
        print("In survey_chart_data_creation")
        # print("Statetet\n", state)
        survey_query_output = state["survey_query_result"]
        question = state["messages"][-1].content

        # survey_query_output_updated = GeneralFunctions.reshape_for_chart(survey_query_output)
        survey_query_output_updated = survey_query_output
        print("Survey Sql Output", survey_query_output_updated)
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
        print("Survey Chart Data", survey_chart_data)
        # state['survey_chart'] = survey_chart_data

        # return state
        return {"survey_chart": survey_chart_data}

    survey_graph = StateGraph(AgentState)

    survey_graph.add_node("survey_normalizer_agent", survey_normalizer_agent)
    # survey_graph.add_node("survey_column_selector_agent", survey_column_selector_agent)
    survey_graph.add_node("survey_planner", survey_planner_node)
    survey_graph.add_node("survey_convert_to_sql", survey_convert_nl_to_sql)
    survey_graph.add_node("survey_execute_sql", survey_execute_sql)
    # survey_graph.add_node("survey_chart_data_creation", survey_chart_data_creation)
    # survey_graph.add_node("survey_sql_join_rewriter", survey_sql_join_rewriter)
    survey_graph.add_node("survey_sql_fixer_agent", survey_sql_fixer_agent)
    survey_graph.add_node("survey_end_max_iterations", survey_end_max_iterations)

    survey_graph.add_edge(START, "survey_normalizer_agent")
    # survey_graph.add_edge("survey_normalizer_agent", "survey_column_selector_agent")
    survey_graph.add_edge("survey_normalizer_agent", "survey_planner")
    survey_graph.add_edge("survey_planner", "survey_convert_to_sql")

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
            "end": END,
            # "survey_chart_data_creation": "survey_chart_data_creation",
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

    # survey_graph.add_edge("survey_chart_data_creation", END)
    survey_graph.add_edge("survey_end_max_iterations", END)

    SurveyAgent = survey_graph.compile()
    # mermaid_code = SurveyAgent.get_graph().draw_mermaid()
    # print(f"Survey Data Graph: {mermaid_code}\n")
