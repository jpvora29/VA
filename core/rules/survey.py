"""Survey-flow prompt rules.

**Phase 2 migration target.** The contents below will move to per-topic
`skill.md` files under `core/skills/` (peer.md, market.md, sow.md, ...) and
be loaded progressively by a registry. For now they sit as one bundle so
behavior is unchanged.
"""
from __future__ import annotations

import dspy


class SurveyRules:
    planner_rules = """
    [DOMAIN METRICS]
    - When query asks about Peer Average or peer score:
    1. Query the `Peers` table first.
        - Apply `Carrier` filter
        - Apply `Country` and `Practice` filters only if explicitly mentioned in the query or derived from context.
        - Get the unique list of `Peers`.
    2. Use this list to filter the `Carriers` table.
        - Apply all other user filters (year, region, attribute, section, etc.).
        - Compute the Peer Average score for that group.

    [ENTITY & FILTER INTEPRETATION RULES]:
    - 'Market' generally refers to a geographical region.
    For example:
    - 'Asia market' or 'Asian market' -> Region = 'Asia'
    - 'LATAM market' -> Region = 'Latin America'

    - If both 'market' and 'country' are mentioned, prioritize Country as the filter, but still ensure Region is inferred correctly if needed for hierarchy checks.
    - If only 'market' is mentioned, map it directly to the Region field.
    - The word 'global' or 'overall market' means no regional filter should be applied.

    - For YoY growth, YoY change or YoY Score, if specific years are not mentioned consider the most recent two years from the dataset.
    - Ensure relative or vague time references in the user query (like last year, recent period, latest survey, etc.)
      are correctly interpreted using the Survey_Year column before generating the reasoning plan.
      Example:- If the user query mentions "last year", interpret it as:
                Survey_Year = (MAX(Survey_Year) - 1)

    [SQL SAFETY RULES]
    1. Never use SQL joins - always use *sub-queries** and **IN clauses**.
        Example: `WHERE Carrier IN (SELECT Peers FROM Peers WHERE LOWER(Carrier)='zurich' AND Lower(Country)='canada')`

    2. When applying filters (e.g., SurveyCountry, Carrier, SurveyPractice, etc.), always wrap in LOWER() for comparison.

    3. Always handle multi-step logic with **nested sub-queries**.
        Example: For “top 3 carriers” and then “top attributes for those carriers”:
        - Step 1: Create a sub-query to get top 3 carriers.
        - Step 2: Use that result in another sub-query to fetch top attributes.
        - Step 3: Output both results (the top 3 carriers and the top attributes).

    4. For any ranking logic (Top-N), specify that sorting and limit must be used inside sub-query.
    5. Always mention when both base and derived results are needed (e.g., top carriers **and** their top products).
    6. Include only the relevant columns (for example:- if the query is regarding YoY growth include, Survey_Year, Avg_Scores along with other relevent columns)
    7. If query mentions across, by, (any dimension) include that in GROUPBY as they need the output by each value of the dimension.
        E.g. Give me the score for zurich in canada across SurveyPractice (In this SurveyPractice should be in GROUPBY)

    8. When the user query involves identifying "top N" or "best N" items **within each group** (e.g., top 3 attributes per carrier, top 5 carriers per country, or top 2 products per segment), use a window function for ranking.
    9. Don't use LOWER() when using IN operation for comparison.
    10. Do not assume anything, strictly get the context and filters from user query.

    [MULTI-STAGE RANKING AND SUB-QUERY RULES]
    - When a user query requests for top N carriers and top M attributes (or any two-level ranking):
    1. Always perform it in two distinct stages:
        a. First sub-query: Identify the top N carriers based on their average score.
        b. Second sub-query: For those top carriers, identify the top M attributes for each carrier.
    2. Apply separate LIMIT clauses for each stage, not a single global LIMIT.
    3. Return combined results showing all top carriers with their top attributes.
    4. Always use sub-queries or WITH clauses instead of JOINs.

    [CONFIDENTIALITY AND AGGREGATION RULES]

    1. Always use **average values** for all metrics when aggregating data for carriers, products, countries, or any other dimension.
    - Example: Instead of showing raw score sum of scores, show the average score or average score for that group.
    - If data is grouped by multiple dimensions (e.g., Product + Country), calculate the average within each group.

    2. For **peer-level metrics**, never display or calculate results for individual peers.
    - Only compute the **average peer score or value** for the selected carrier or filter combination.
    - Never reveal individual peer-level data — this is a **confidentiality constraint**.

    3. For all metrics involving comparisons (Carrier vs Peer):
    - Compute both sides as **average values**.
    - The comparison should be Carrier’s average vs Peer Average score.
    - Avoid using raw or total values unless explicitly requested.

    4. When generating reasoning steps or query plans:
    - Explicitly state when an average is being computed (e.g., “Calculate average score per carrier”).
    - For peer metrics, explicitly write “Calculate peer average only, not individual peers”.

    5. Do not include carrier identifiers for peers.
    - Only refer to them collectively as “Peers” or “Peer Group”.

    These rules apply to all reasoning and planning outputs, regardless of metric type (score, nps, response count).

    """

    query_rules = """

    [GUIDELINES]
        1. Follow all steps and rules in the reasoning plan exactly.
        2. Always use **sub-queries** and **IN clauses** instead of JOINs.
        3. Use **LOWER()** for all text comparisons in WHERE clauses for case-insensitivity.
        4. Use **NULLIF()** for any division to avoid divide-by-zero errors.
        5. Use **COALESCE()** to safely handle NULLs when aggregating.
        6. Use **LIMIT** and **ORDER BY** for ranking logic.
        7. Do NOT create new columns or metrics not mentioned in reasoning.
        8. Do NOT output explanations — output only SQL.
        9. Give proper alias names so that there is no unambiguous: OperationError
        10. Include only the relevant fields in the final sql query (e.g If query is about YoY include the Survey_Year column along with other relevant columns)
        11. If query mentions across, by, (any dimension) include that in GROUPBY
        12. When using **UNION ALL** be mindful to use **ORDER BY** Clause after the **UNION ALL**.
        13. Do not assume anything, strictly get the context and filters from reasoning plan.
        14. Do not hallucinate and invent your own filters.
        15. When the user query involves identifying "top N" or "best N" items **within each group** (e.g., top 3 attributes per carrier, top 5 carriers per country, or top 2 products per segment), use a window function for ranking.
            - Specifically, use: ROW_NUMBER() OVER (PARTITION BY <group_column> ORDER BY <metric_column> DESC) AS rank_<metric>


    [AGGREGATION AND CONFIDENTIALITY RULES]

        1. Always use **AVG()** when calculating any score, index, or metric value for a carrier, peer group, or any other dimension.
        - Example: `AVG(Score)` instead of `SUM(Score)` or individual values.
        - This rule applies to all score-like fields such as score, nps

        2. For peer-related results:
        - Always compute the **peer average**; never list or display scores of individual peers.
        - Use `WHERE Carrier IN (subquery for peers)` and wrap in `AVG()`.

        3. For carrier, product, or dimension-level comparisons:
        - Compute **average score per group** using `GROUP BY`.
        - Example:
            ```sql
            SELECT Product, AVG(Score) AS Avg_Score
            FROM Carrier
            WHERE LOWER(Carrier)='zurich' AND LOWER(Country)='canada'
            GROUP BY Product;
            ```
        4. Never output raw or individual-level scores in any SQL query.
        Only aggregate (AVG) results should appear in the SELECT clause.


        [NOTES]
        - Always write syntactically correct SQLite queries.
        - Handle multi-step logic using sub-queries exactly as described.
        - Never use JOINs.
        - Never add or omit filters not present in the reasoning.
        - The reasoning plan is the source of truth.

    """

    few_shot_dict = {
        "example_1": {
            "user_query": "Show me Zurich score in canada in 2023.",
            "sql_query": '''"SELECT AVG(Score) AS avg_score
                                    FROM Carriers
                                    WHERE LOWER(Carrier) = LOWER('Zurich')
                                    AND LOWER(SurveyCountry) = 'canada'
                                    AND Survey_Year = 2023;"''',
        },
        "example_2": {
            "user_query": "What is chubb's peers scores in Singapore in 2023?",
            "sql_query": """"SELECT AVG(c.Score) AS peer_average_score
                            FROM Carriers c
                            WHERE c.Carrier IN (
                                SELECT DISTINCT Peers
                                FROM Peers p
                                WHERE LOWER(p.Country) = LOWER('Singapore')
                                AND LOWER(p.Carrier) = LOWER('chubb')
                            )

                            AND LOWER(c.SurveyCountry) = LOWER('Singapore')
                            AND c.Survey_Year = 2023;" """,
        },
        "example_3": {
            "user_query": "Compare chubb and its peers score for signapore across products in 2025?",
            "sql_query": """"WITH peer_groups AS (
                        SELECT DISTINCT Peers
                        FROM Peers
                        WHERE LOWER(p.Country) = LOWER('singapore')
                        AND LOWER(p.Carrier) = LOWER('chubb')

                    )
                    SELECT
                        c.SurveyPractice AS Products,
                        AVG(CASE WHEN LOWER(c.Carrier) = LOWER('chubb') THEN c.Score END) AS carrier_score,
                        AVG(CASE WHEN c.Carrier IN (SELECT Peers FROM peer_groups) THEN c.Score END) AS peer_average_score

                        FROM Carriers c
                        WHERE LOWER(c.SurveyCountry) = LOWER('singapore')
                        AND c.Survey_Year = 2025

                        GROUP BY SurveyPractice
                        ORDER BY carrier_score;"
                    """,
        },
        "example_4": {
            "user_query": "What is the year-over-year (YoY) change in score for aig in US?",
            "sql_query": '''"SELECT
                        Survey_Year,
                        AVG(Score) as avg_score,
                        (AVG(Score) - LAG(AVG(Score)) OVER (ORDER BY Survey_Year)) / LAG(AVG(Score)) OVER (ORDER BY Survey_Year) * 100 AS YoY_Change
                        FROM Carriers
                        WHERE LOWER(Carrier) = LOWER('aig')
                        AND LOWER(SurveyCountry) = LOWER('us')

                        GROUP BY Survey_Year
                        ORDER BY Survey_Year;"''',
        },
        "example_5": {
            "user_query": "Identify the top 3 Carriers in Singapore for the Survey_Year 2025 and for each of them give me top 3 Attributes",
            "sql_query": '''"WITH TopCarriers AS (
                        SELECT Carrier, AVG(Score) AS avg_score
                        FROM Carriers
                        WHERE LOWER(SurveyCountry) = LOWER('singapore')
                        AND Survey_Year = 2025
                        GROUP BY Carrier
                        ORDER BY avg_score DESC
                        LIMIT 3
                    ),

                    RankedAttributes AS (
                        SELECT Carrier, Attribute, AVG(Score) as AvgScore, ROW_NUMBER() OVER (PARTITION BY Carrier ORDER BY AVG(Score) DESC) AS rank_attr
                        FROM Carriers
                        WHERE LOWER(SurveyCountry) = LOWER('singapore')
                        AND Survey_Year = 2025
                        AND Carrier IN (SELECT Carrier FROM TopCarriers)
                        GROUP BY Carrier, Attribute
                    )

                    SELECT Carrier, Attribute, AvgScore
                    FROM RankedAttributes
                    WHERE rank_attr <= 3
                    ORDER BY Carrier, AvgScore DESC;"''',
        },
    }

    survey_query_few_shots = [
        dspy.Example(
            user_query=ex["user_query"], sql_query=ex["sql_query"]
        ).with_inputs("user_query")
        for ex in few_shot_dict.values()
    ]

    response_rules = """
    1. STICK TO THE FACTS
    - Only describe what is present in the data.
    - Do NOT infer insights, trends, causes, or implications.
    - For YoY change always show in % and round it to 2 decimal.
    - Use the table information and always display it in the final output as its very important for transparency and tracebility.
    - Avoid speculative or analytical phrasing (e.g., "this suggests", "it indicates", "likely due to").

    2. PLAIN ENGLISH FORMATTING
    - Use simple, professional language suitable for business reporting.
    - Convert data rows or columns into coherent English sentences or bullet points.
    - Avoid jargon unless it is a defined insurance term (e.g., premium, appetite, loss ratio).

    3. BEAUTIFY THE OUTPUT
    - Use consistent formatting with either:
        a. Bullet lists for multiple records
        b. Markdown tables for structured comparison
    - Bold key terms such as Carriers, Products, Metrics, Years.
    - Add minimal spacing for readability.

    4. INCLUDE EVERY DATA POINT
    - Ensure every data point mentioned in the input is represented in the output.
    - Do not omit any category, metric, or carrier mentioned in the data.

    5. MAINTAIN CONTEXTUAL ACCURACY
    - If the data includes carrier, product, segment, or region details, mention them clearly.
    - Preserve numerical precision (e.g., “12.5%” instead of “about 13%”).
    - Retain time periods (e.g., “Q2 2025”, “Year 2024”) exactly as in the data.

    6. NO INSIGHTS OR CONCLUSIONS
    - You are NOT an insight generator here.
    - Avoid evaluative or interpretive words such as: improved, declined, strong, weak, positive, negative, trend, likely, suggests, etc.
    - Only report what the data explicitly states.
            - Do not hallucinate and add your points, filters or values.

    7. OUTPUT FORMAT
    - Use one of the following formats depending on data shape:
        a. **Bullet Points (for few records):**
            • **Carrier:** Zurich
                **Product:** Property
                **Score:** 6.2
                **Year:** 2024

        b. **Always Markdown Table (for comparative or multi-row data (>3 records in the list)):**
            | Carrier | Product | Metric | Value | Year |
            |----------|----------|---------|--------|------|
            | Zurich | Property | Score | 6.2 | 2024 |
            | Zurich  | Casualty | Score | 6.3 | 2024 |

    TONE AND STYLE:
    - Factual, concise, neutral, and data-grounded.
    - Avoid adjectives, interpretations, and opinions.
    - Think of it as writing a data statement, not a data story.


    """
