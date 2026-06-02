"""General-purpose helpers: schema introspection, HumanMessage assembly, SQL cleanup."""
from __future__ import annotations

import re
from typing import Dict, List

import pandas as pd
from langchain_core.messages import HumanMessage
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from config.valid_values_config import *  # noqa: F401,F403 - preserves legacy globals (valid_countries, valid_country_carrier, valid_countries_gpr, valid_country_carrier_gpr)
from core.data.valid_values import GetValidData


class GeneralFunctions:
    """Cross-flow utilities used by the planner, SQL agent, and response nodes.

    Like `GetValidData`, methods are called on the class, not on instances.
    """

    def get_database_schema(engine: Engine) -> Dict[str, list]:
        """Return per-table column metadata for the connected database.

        Args:
            engine: SQLAlchemy engine for the analyst's SQLite database.

        Returns:
            Dict keyed by table name (Carriers, GPR, Peers, GIMMI). Each value
            is a list of {Column Name, type, nullable, default, primary_key}.
        """

        inspector = inspect(engine)

        schema_dict: Dict[str, list] = {"Carriers": [], "GPR": [], "Peers": [], "GIMMI": []}

        for table_name in inspector.get_table_names():
            for col in inspector.get_columns(table_name):
                schema_dict[table_name].append(
                    {
                        "Column Name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col["nullable"],
                        "default": col["default"],
                        "primary_key": col["primary_key"],
                    }
                )

        print("Retrieved database schema.")

        return schema_dict

    def build_human_message(
        user_query: str,
        schema: Dict,
        valid_values_survey: Dict = {},
        definitions_survey: Dict = {},
        valid_values_gpr: Dict = {},
        definitions_gpr: Dict = {},
        reasoning_survey: str = "",
        reasoning_gpr: str = "",
        messages: List = [],
        required_cols: List = [],
        is_survey: bool = False,
        is_gpr: bool = False,
    ) -> HumanMessage:

        parts = []
        updated_valid_values = {}

        ### Adding User Query
        parts.append(f"User Query: {user_query.strip()}")
        # parts.append(user_query.strip())
        parts.append("\n")

        ### Adding Survey Schema
        if is_survey:
            parts.append("Schemas:")
            parts.append(f"Carriers Table Schema: {schema.get('Carriers', [])}")
            parts.append("\n")

            parts.append(f"Peers Table Schema: {schema.get('Peers', [])}")
            parts.append("\n")

        ### Adding GPR Schema
        if is_gpr:
            parts.append("Schemas:")
            parts.append(f"GPR Table Schema: {schema.get('GPR', [])}")
            parts.append("\n")

            parts.append(f"Peers Table Schema: {schema.get('Peers', [])}")
            parts.append("\n")

        if len(reasoning_survey) > 0:
            parts.append(f"Reasoning Plan: {reasoning_survey}")
            parts.append("\n")

        if len(reasoning_gpr) > 0:
            parts.append(f"Reasoning Plan: {reasoning_gpr}")
            parts.append("\n")

        ### Adding Defintions for Survey
        if definitions_survey:
            parts.append("Definitions Carriers Table:\n")
            for col, vars in definitions_survey.items():
                parts.append(f"- {col}: {vars}")
                # parts.append("\n")
            parts.append("\n")

        ### Adding Defintions for Survey
        if definitions_gpr:
            parts.append("Definitions GPR Table:\n")
            for col, vars in definitions_gpr.items():
                parts.append(f"- {col}: {vars}")
                # parts.append("\n")
        parts.append("\n")

        ### Adding Conversation History
        if len(messages) > 0:
            conversation_history = []
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    conversation_history.append(msg)
                    print(f"Current Conversation History: {conversation_history} ")

            if len(conversation_history) > 1:
                parts.append(f"Latest Query: {conversation_history[-2]}")
                print(f"Latest Query is : {conversation_history[-2]}")
                parts.append("\n")

                parts.append(f"Conversation History: {conversation_history[-5:-2]}")
                print(f"Conversation History is: {conversation_history[-5:-2]}")
                parts.append("\n")

        ### Adding Valid Values for Survey
        if valid_values_gpr:
            country, carriers = GetValidData.matching_values(
                user_query=user_query,
                valid_countries=valid_countries_gpr,
                country_carrier_dict=valid_country_carrier_gpr,
            )
            # print(country, carriers)
            # valid_values_gpr['Country'] = country
            # valid_values_gpr['Carrier_Group'] = carriers

            parts.append("Valid Values GPR Table:\n")

            if len(required_cols) > 0:
                for col, vars in valid_values_gpr.items():
                    if col in required_cols:
                        updated_valid_values[col] = vars

                for col, vars in updated_valid_values.items():
                    parts.append(f"- {col}: {vars}")

            else:
                for col, vars in valid_values_gpr.items():
                    parts.append(f"- {col}: {vars}")

            parts.append("\n")

        ### Adding Valid Values for GPR
        if valid_values_survey:
            country, carriers = GetValidData.matching_values(
                user_query=user_query,
                valid_countries=valid_countries,
                country_carrier_dict=valid_country_carrier,
            )
            valid_values_survey["SurveyCountry"] = country
            valid_values_survey["Carrier"] = carriers

            parts.append("Valid Values Carriers Table:\n")

            if len(required_cols) > 0:
                for col, vars in valid_values_survey.items():
                    if col in required_cols:
                        updated_valid_values[col] = vars

                for col, vars in updated_valid_values.items():
                    parts.append(f"- {col}: {vars}")

            else:
                for col, vars in valid_values_survey.items():
                    parts.append(f"- {col}: {vars}")

            parts.append("\n")

        content = "\n".join(parts)

        return HumanMessage(content=content)

    def clean_sql_output(sql_output: List[Dict], reasoning: Dict) -> List[Dict]:
        # print("Reasoning:", reasoning)

        df = pd.DataFrame(sql_output)

        df = df.loc[~((df == 0).any(axis=1) | df.isnull().any(axis=1))]

        carrier_keywords = []
        # print("Typeeee", type(reasoning))
        filters = reasoning.get("filters", {})
        # print("Filetetrtr", filters)
        for key, val in filters.items():
            if re.search(r"carrier", key, re.IGNORECASE):
                # Split on underscore or space
                if isinstance(val, str):
                    carrier_keywords.extend(re.split(r"[_\s]+", val))
        # print("Carr", carrier_keywords)

        numeric_cols = df.select_dtypes(include=["number"]).columns

        premium_cols = [
            col for col in numeric_cols if re.search(r"premium", col, re.IGNORECASE)
        ]

        for col in numeric_cols:
            if col in premium_cols:
                df[col] = df[col].round(0)
            else:
                df[col] = df[col].round(1)

        sort_col = None
        for col in premium_cols:
            if re.search(r"carrier", col, re.IGNORECASE):
                sort_col = col
                break
            if any(
                re.search(keyword, col, re.IGNORECASE) for keyword in carrier_keywords
            ):
                sort_col = col
                break

        if not sort_col and premium_cols:
            if premium_cols:
                sort_col = premium_cols[0]
            elif numeric_cols:
                sort_col = numeric_cols[0]

        if sort_col:
            df = df.sort_values(by=sort_col, ascending=False)

        return df.to_dict(orient="records")
