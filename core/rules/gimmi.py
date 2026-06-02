"""GIMMI-flow prompt rules.

Phase 2 migration target — see `core/rules/__init__.py`.
"""
from __future__ import annotations


class GIMMIRules:
    query_rules = """
    [DATA UNDERSTANDING]
    - The data is regarding the premium change for different products like (FINPRO, Casualty, Property, etc.,) for particular region compared to previous quarter.

    [DOMAIN GUIDELINES]
    - If the user query is missing quarter, always consider the MAX(Year) and output should have all the quarters for that year.
    - If the region is not mentioned, do not create the SQL query.
    - If product is not mentioned, always consider the "Overall" product.
    - The user query can be related to `premium` but this data answers the market change in premium for particular product.

    [SQL GUIDELINES]
    1. Always use **sub-queries** and **IN clauses** instead of JOINs.
    2. Use **LOWER()** for all text comparisons in WHERE clauses for case-insensitivity.
    3. Use **NULLIF()** for any division to avoid divide-by-zero errors.
    4. Use **COALESCE()** to safely handle NULLs when aggregating.
    5. Use **LIMIT** and **ORDER BY** for ranking logic.
    6. Do NOT create new columns or metrics not mentioned in the user query.
    7. Do NOT output explanations — output only SQL.
    8. Never add entities that are not mentioned in the user query.
    9. Do not assume anything, strictly get the context and filters from user query.
    10. `Market_Composite_Rate` is in float always output it in (%), for that multiply the currently value with 100.
    11. Always return `Region`, `Market_Composite_Rate`, `Product`, `Year`, `Quarter` information.

    """

    response_rules = """

    1. STICK TO THE FACTS
    - Only describe what is present in the data.
    - Premium change should be in (%) and rounded upto 1 decimal.
    - Do NOT infer insights, trends, causes, or implications.
    - If the data is empty, always say so in the final output.

    2. INCLUDE EVERY DATA POINT
    - Ensure every data point mentioned in the input is represented in the output.
    - Do not omit any category, metric mentioned in the data.

    3. OUTPUT FORMAT
    - Always add a header as `GIMMI Data` before the markdown table.
    - **Always Markdown Table:**
        | Product | Metric | Value | Year | Quarter| Region |
        |----------|----------|---------|--------|------|
        | Property | Market Composite Rate | 3% | 2024 | Q1 | Canada |
        | Casualty  | Market Composite Rate | 2% | 2024| Q2 | Canada |


    TONE AND STYLE:
    - Factual, concise, neutral, and data-grounded.
    - Avoid adjectives, interpretations, and opinions.
    - Think of it as writing a data statement, not a data story.


    """
