"""Signatures for the GIMMI (market data) flow."""
from __future__ import annotations

from typing import Any, Dict, List

from core.llm import InputField, OutputField, Signature


class GIMMISQLAgentSignature(Signature):
    """
    [ROLE]
    You are an SQL generation agent specialized in creating valid and efficient SQLite queries for insurance market data.

    [OBJECTIVE]
    Your task:
    Understand the user query and create accurate SQLite query using only the provided schema.
    """

    context: str = InputField(
        desc="All background info: rules, schema, definitions, valid_values"
    )
    user_query: str = InputField(desc="User's natural language question or query")
    sql_output: str = OutputField(
        desc="SQL output for the user query with no codeblocks like ```sql```"
    )


class GIMMIResponseSignature(Signature):
    """
    ROLE:
    You are an Insurance Data Narrator specialized in translating structured market insurance data into precise markdown table.

    OBJECTIVE:
    Convert the provided data or model output into clear, concise, and directly relevant natural language responses strictly based on the given data points.
    You must NOT provide any inference, assumption, or additional commentary beyond what is explicitly present in the data.

    """

    rules: str = InputField(
        desc="Important rules to follow during the final output creation"
    )
    sql_output: List[Dict[str, Any]] = InputField(
        desc="SQL output for the GIMMI data (market data)"
    )
    user_query: str = InputField(desc="User's natural language question or query")
    gimmi_response: str = OutputField(
        desc="Concise natural language response in markdown table for the user query"
    )
