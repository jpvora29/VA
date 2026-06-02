"""GPR LangGraph subgraph: normalizer → planner → SQL → execute (+ fixer loop)."""
from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy.sql import text

from config.valid_values_config import *  # noqa: F401,F403 - preserves legacy globals (valid_year_quarter_gpr)
from core.agents.gpr.chart import GPRChartNode
from core.agents.gpr.planner import GPRPlannerNode
from core.agents.gpr.sql_agent import GPRSQLAgentNode
from core.data.general import GeneralFunctions
from core.data.valid_values import GetValidData
from core.initialization import Initialization
from core.observability import latency_timer, log_event, sql_metadata
from core.rules.gpr import GPRRules
from core.rules.gpr_chart import GPRChartRules
from core.schemas.gpr import (
    GPRCheckSQLOutput,
    GPRColumnSelectorAgent,
    GPRQueryNormalizer,
    GPRSQLJoinChecker,
)
from core.skills import get_skill_loader
from core.state.agent_state import AgentState
from logger import get_logger

logger = get_logger(__name__)


class GPRSubGraph:

    def gpr_normalizer_agent(state: AgentState) -> AgentState:

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
        4. For Carrier_Group i.e Zurich, Chubb always check the valid list of Carrier_Group as the name passed in the query will be slightly different from carrier group.
            For Example:- What is the premium for Zurich?
                          Valid Values :- [ZURICH GROUP, CHUBB, AXA]
                          Normalized Query:- What is the premium for ZURICH GROUP?
        5. Do not modify numbers, operators, or time references.
        6. Do not alter the question wording or structure beyond replacing names.
        7. Do not invent new columns or values.
        8. **Remember marsh is not a carrier nor a client its insurance broker. Do not apply any fuzzy logic on it**.
        9. If the user query is having a value for any column then post then also add the exact column name.
            - This will be extremely important as planner will get the right context for the column value.
            - Use the `valid_list` to check and get the exact column name.
            - Do not add anything for 'Marsh', 'peer' words in the user query.

            For example:-
            User Query:- What is the SoW for Merger & Acquistion Service in Canada?
            Normalized Query:- What is the SoW for Merger & Acquistion Service Product_Line in Canada?

            User Query:- What is zurich share in marsh book?
            Normalized Query:- What is ZURICH GROUP share in marsh book?

        10. If everything is already correct, return the query exactly as received.

        [STYLE]
        - Be precise and minimal — your output should look identical to the input except for corrected terms.
        - Do not explain what was corrected.
        - Output **only the updated query text** — no metadata, no lists, no JSON.

        [EXAMPLES]

        Example 1:
        User Query: "Show me total prem of zurich in singpore for property"
        Schema: ["Carrier", "Country", "Product_Line", "Premium"]
        Valid Values:
        - Country: ["Singapore", "Canada", "USA"]
        - Carrier: ["Zurich", "Chubb", "AIG"]
        - Product_Line: ["Property", "Casualty", "Financial Lines"]

        Output: "Show me total Premium of Zurich in Singapore for Property"

        ---

        Example 2:
        User Query: "growth of chub in canad across all products"
        Output: "growth of Chubb in Canada across all Product_Line"

        ---

        """

        messages = [
            SystemMessage(content=system_prompt),
            GeneralFunctions.build_human_message(
                user_query=question,
                schema=schema,
                valid_values_gpr=GetValidData.valid_values_gpr,
                is_gpr=True,
            ),
        ]

        structured_llm = Initialization.llm.with_structured_output(GPRQueryNormalizer)
        response = structured_llm.invoke(messages)

        last_msg = state["messages"][-1]
        # state["messages"][-1] = HumanMessage(response.normalized_query)

        print(f"Normalized User Question: {response.normalized_query}")

        return {
            "messages": [
                RemoveMessage(id=last_msg.id),
                HumanMessage(content=response.normalized_query),
            ]
        }

    def gpr_column_selector_agent(state: AgentState) -> AgentState:
        # question = state['question']
        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)

        system_prompt = """
        You are a Column Selector Agent specialized in Insurance and Risk Consulting data, particularly premium, peer performance datasets.
        Your task is to analyze a user’s natural language query and identify most relevant columns from the provided schema that can answer the user's query, using insurance-specific understanding of terms
        such as product line, appetite, SoW, growth, rank, segment, etc.

        Input Provided:
        - The rephrased query in clear English
        - List of schema column names
        - Definition for the `GPR` table columns

        Rules:
        1. Map user intent to the exact column names from the schema.
        2. If query asks for a breakdown ("across products", "by industry"), include that column as well.
        3. Always return output as a list of valid column names.
        4. Always use the `Carrier_Group` instead of `Carrier_Name`.
        5. If query mentions YoY, growth, SoW, appetite, rolling 12M, month-on-month include the `Premium` along with the requested column(s).
        6. Do not invent new columns.

        Output only JSON list:
        Example: []

        """
        messages = [
            SystemMessage(content=system_prompt),
            GeneralFunctions.build_human_message(
                user_query=question,
                schema=schema,
                definitions_gpr=GetValidData.definitions_gpr,
                is_gpr=True,
            ),
        ]

        structured_llm = Initialization.llm.with_structured_output(
            GPRColumnSelectorAgent
        )
        response = structured_llm.invoke(messages)

        # state["gpr_cols"] = response.columns

        print(f"Selected columns are: {response.columns}")

        return {"gpr_cols": response.columns}

    def gpr_planner_node(state: AgentState) -> AgentState:

        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
        gpr_schema = schema.get("GPR", [])
        peers_schema = schema.get("Peers", [])
        skill_rules = get_skill_loader().planner("gpr", question)
        planner_rules = skill_rules if skill_rules else GPRRules.planner_rules
        log_event(
            logger,
            "skill_load",
            node="gpr_planner",
            flow="gpr",
            scope="planner",
            used_skills=bool(skill_rules),
        )

        planner_node = GPRPlannerNode(
            gpr_schema=gpr_schema,
            peers_schema=peers_schema,
            definitions=GetValidData.definitions_gpr,
            rules=planner_rules,
        )

        query_plan = planner_node(
            user_query=question, valid_year_quarter=valid_year_quarter_gpr
        )

        Initialization.log_prompt_cache_usage(
            response=query_plan, label="gpr_planner_node"
        )

        # state["gpr_reasoning"] = query_plan

        print(f"Reasoning Plan for GPR Data: {query_plan}")

        return {"gpr_reasoning": query_plan}

    def gpr_convert_nl_to_sql(state: AgentState) -> AgentState:
        """Using LLM Converts the Natural Language Query to a SQL Query"""

        question = state["messages"][-1].content
        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
        gpr_schema = schema.get("GPR", [])
        peers_schema = schema.get("Peers", [])
        query_plan = state["gpr_reasoning"]
        skill_rules = get_skill_loader().sql("gpr", question)
        query_rules = skill_rules if skill_rules else GPRRules.query_rules
        log_event(
            logger,
            "skill_load",
            node="gpr_sql",
            flow="gpr",
            scope="sql",
            used_skills=bool(skill_rules),
        )

        sql_agent = GPRSQLAgentNode(
            gpr_schema=gpr_schema,
            peer_schema=peers_schema,
            rules=query_rules,
            few_shot=GPRRules.gpr_query_few_shots,
        )

        sql_query_output = sql_agent(
            user_query=question,
            query_plan=query_plan,
            valid_year_quarter=valid_year_quarter_gpr,
        )

        Initialization.log_prompt_cache_usage(
            response=sql_query_output, label="gpr_convert_nl_to_sql"
        )

        # state["gpr_sql_query"] = sql_query_output

        print(f"SQL Query For GPR Data: {sql_query_output}")

        return {"gpr_sql_query": sql_query_output}

    def gpr_execute_sql(state: AgentState) -> AgentState:
        """Executes the SQL Query"""

        sql_query = state["gpr_sql_query"].strip()
        session = Initialization.Session()

        log_event(
            logger,
            "sql_execute_start",
            route="premium",
            node="gpr_execute_sql",
            sql=sql_metadata(sql_query),
        )
        timing = {}
        try:
            with latency_timer() as timing:
                result = session.execute(text(sql_query))
                rows = result.fetchall()
                columns = result.keys()

            print(f" Fetched Rows are :\n {rows}")

            if rows:
                header = ", ".join(columns)
                query_result = [dict(zip(columns, row)) for row in rows]

            else:
                query_result = []

            is_error = False
            # query_result = GeneralFunctions.clean_sql_output(
            #     sql_output=query_result, reasoning=json.loads(state["gpr_reasoning"])
            # )
            is_dataOverflow = len(query_result) > 40
            log_event(
                logger,
                "sql_execute_end",
                route="premium",
                node="gpr_execute_sql",
                sql=sql_metadata(
                    sql_query,
                    row_count=len(query_result),
                    duration_ms=timing.get("duration_ms"),
                ),
                overflow=is_dataOverflow,
            )

        except Exception as e:
            query_result = f"Error executing SQL query: {e}"
            is_error = True
            is_dataOverflow = False
            log_event(
                logger,
                "sql_execute_error",
                logging.ERROR,
                route="premium",
                node="gpr_execute_sql",
                sql=sql_metadata(sql_query, duration_ms=timing.get("duration_ms")),
                error=str(e),
            )

        finally:
            session.close()

        return {"gpr_query_result": query_result, "gpr_sql_error": is_error}

    def gpr_sql_join_rewriter(state: AgentState) -> AgentState:
        sql_query = state["gpr_sql_query"].strip()

        system_prompt = """
        You are a SQL Rewriter Agent.
        Your task is to review the SQL query generated by another SQLAgent and ensure that it does not use any JOIN operations.

        Rules:
        1. If the SQL query contains a JOIN, you must rewrite it by removing the JOIN.
        2. Instead of JOINs, use subqueries with IN or EXISTS clauses.
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

        structured_llm = Initialization.llm.with_structured_output(GPRSQLJoinChecker)
        response = structured_llm.invoke(messages)

        Initialization.log_prompt_cache_usage(
            response=response, label="gpr_sql_join_rewriter"
        )

        # print(f"SQL Join Rewriting for: {state['messages'][-1]}")

        # state["gpr_sql_query"] = response.updated_query

        print(f"Updated Without Join Query: {response.updated_query}")

        return {"gpr_sql_query": response.updated_query}

    def gpr_sql_fixer_agent(state: AgentState) -> AgentState:
        sql_query = state["gpr_sql_query"].strip()
        # question = state['question']
        question = state["messages"][-1].content
        error_message = state["gpr_query_result"]

        print(f"Error message: {error_message}")

        schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
        gpr_schema = schema.get("GPR", [])
        peer_schema = schema.get("Peers", [])

        system_prompt = """
        You are a SQL Error Fixer Agent.

        [R – Role]
        You act as a SQL expert who diagnoses errors in SQL queries and fixes them.
        You understand schemas, valid values, and typical SQL syntax errors.

        [E – Explicitness]
        - Input includes: user query, schema, definition (GPR table columns), SQL query, error message, valid list of column values.
        - Your task: identify the cause of the error and return a corrected SQL query.
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

        - Error: “no such table: PeerScores”
        Fix: Replace with correct table `Peers`.

        [O – Output Format]
        - Always return JSON
        - Example:
        `{"SELECT Carrier, AVG(Score) FROM Carriers WHERE Country='Canada' GROUP BY CarrierName" }`

        [N – Nuances]
        - Apply fuzzy matching for column/value names (e.g., “Chub” → “Chubb”).
        - If peer average is mentioned, apply rules:
        - Use `Peers` table, get Peers list for Carrier, Country, Product combination, then apply filters in Carriers table.
        - Avoid unnecessary joins unless explicitly needed.
        - If unsure, choose the safest correction aligned with schema.
        - Do not output reasoning or explanation text—only the corrected SQL query inside JSON.
        - Always use `Carrier_Group` column instead of `Carrier_Name`.
        """

        human_message = f"""
        Usery Query: {question}
        GPR Schema: {gpr_schema}
        Peer Schema: {peer_schema}
        SQL Query: {sql_query}
        Error Message: {error_message}
        Valid Values:{GetValidData.valid_values_gpr}
        """

        print(f"Fixing the original query: {question}")

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]

        structured_llm = Initialization.llm.with_structured_output(GPRCheckSQLOutput)
        corrected_response = structured_llm.invoke(messages)

        Initialization.log_prompt_cache_usage(
            response=corrected_response, label="gpr_sql_fixer_agent"
        )

        # state["gpr_sql_query"] = corrected_response.updated_query
        # # print(f"Total Attempts for far: {state['attempts']}")
        # state["gpr_attempts"] += 1

        return {"gpr_sql_query": corrected_response.updated_query, "gpr_attempts": 1}

    def gpr_check_if_join_required_router(state: AgentState) -> AgentState:
        print("Check Join Router")
        if re.search(r"(?i)join", state["gpr_sql_query"]):
            print("gpr_sql_join_rewriter\n")
            return "gpr_sql_join_rewriter"
        else:
            print("gpr_execute_sql\n")
            return "gpr_execute_sql"

    def gpr_end_max_iterations(state: AgentState) -> AgentState:
        # state["gpr_query_result"] = "Please try again !"
        print("Maximum attempts reached. Ending the workflow.")
        return {"gpr_query_result": "Please try again later !"}

    def gpr_check_attempts_router(state: AgentState):
        if state["gpr_attempts"] < 3:
            return "gpr_execute_sql"
        else:
            return "gpr_end_max_iterations"

    def gpr_execute_sql_router(state: AgentState):
        # if not state.get("gpr_sql_error", False):
        #     return "premium_chart_data_creation"
        # else:
        #     return "gpr_sql_fixer_agent"
        if not state.get("gpr_sql_error", False):
            return "end"
        else:
            return "gpr_sql_fixer_agent"

    def premium_chart_data_creation(state: AgentState) -> AgentState:
        # print("In premium_chart_data_creation")
        # print("Statetet\n", state)
        gpr_query_output = state["gpr_query_result"]
        question = state["messages"][-1].content

        # survey_query_output_updated = GeneralFunctions.reshape_for_chart(survey_query_output)
        gpr_query_output_updated = gpr_query_output
        print("GPR Sql Output", gpr_query_output_updated)
        skill_rules = get_skill_loader().chart("gpr", question)
        chart_rules = skill_rules if skill_rules else GPRChartRules.chart_creation_rules
        log_event(
            logger,
            "skill_load",
            node="gpr_chart",
            flow="gpr",
            scope="chart",
            used_skills=bool(skill_rules),
        )
        gpr_chart_creation_agent = GPRChartNode(
            chart_creation_rules=chart_rules
        )
        gpr_chart_data = gpr_chart_creation_agent(
            user_query=question, sql_output=gpr_query_output_updated
        )
        print("GPR Chart Data", gpr_chart_data)
        # state['gpr_chart'] = gpr_chart_data

        # return state
        return {"gpr_chart": gpr_chart_data}

    gpr_graph = StateGraph(AgentState)

    gpr_graph.add_node("gpr_normalizer_agent", gpr_normalizer_agent)
    # gpr_graph.add_node("gpr_column_selector_agent", gpr_column_selector_agent)
    gpr_graph.add_node("gpr_planner_node", gpr_planner_node)
    gpr_graph.add_node("gpr_convert_to_sql", gpr_convert_nl_to_sql)
    gpr_graph.add_node("gpr_execute_sql", gpr_execute_sql)
    # gpr_graph.add_node("gpr_sql_join_rewriter", gpr_sql_join_rewriter)
    gpr_graph.add_node("gpr_sql_fixer_agent", gpr_sql_fixer_agent)
    gpr_graph.add_node("gpr_end_max_iterations", gpr_end_max_iterations)
    # gpr_graph.add_node("premium_chart_data_creation", premium_chart_data_creation)

    gpr_graph.add_edge(START, "gpr_normalizer_agent")
    # gpr_graph.add_edge("gpr_normalizer_agent", "gpr_column_selector_agent")
    gpr_graph.add_edge("gpr_normalizer_agent", "gpr_planner_node")
    gpr_graph.add_edge("gpr_planner_node", "gpr_convert_to_sql")
    gpr_graph.add_edge("gpr_convert_to_sql", "gpr_execute_sql")

    # gpr_graph.add_conditional_edges(
    #     "gpr_convert_to_sql",
    #     gpr_check_if_join_required_router,
    #     {
    #         "gpr_sql_join_rewriter": "gpr_sql_join_rewriter",
    #         "gpr_execute_sql": "gpr_execute_sql",
    #     },
    # )

    # gpr_graph.add_edge("gpr_sql_join_rewriter", "gpr_execute_sql")

    gpr_graph.add_conditional_edges(
        "gpr_execute_sql",
        gpr_execute_sql_router,
        {
            "end": END,
            # "premium_chart_data_creation": "premium_chart_data_creation",
            "gpr_sql_fixer_agent": "gpr_sql_fixer_agent",
        },
    )

    gpr_graph.add_conditional_edges(
        "gpr_sql_fixer_agent",
        gpr_check_attempts_router,
        {
            "gpr_execute_sql": "gpr_execute_sql",
            "gpr_end_max_iterations": "gpr_end_max_iterations",
        },
    )

    gpr_graph.add_edge("gpr_end_max_iterations", END)
    # gpr_graph.add_edge("premium_chart_data_creation", END)

    GPRAgent = gpr_graph.compile()
    # mermaid_code = GPRAgent.get_graph().draw_mermaid()
    # print(f"GPR Data Graph: {mermaid_code}")
