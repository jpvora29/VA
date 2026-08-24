"""GPR-flow prompt rules.

Phase 2 migration target — see `core/rules/__init__.py`.
"""
from __future__ import annotations

from core.llm import Example


class GPRRules:
    planner_rules = """
    [SQL SAFETY RULES]
    1. ALWAYS use sub-queries and IN clauses instead of JOINs
    2. When applying filters (Country, Carrier_Group, Product_Line, etc.), always wrap in LOWER() for comparison.
    3. FOR AND/OR logic combining multiple conditions, use nested WHERE clauses within sub-queries.Do not combine dimensions using JOINs.
    4. For Top-N queries, use LIMIT inside the sub-queries (not globally).
    Always ORDER BY the metric (SUM/AVG/etc.) inside each ranking sub-query.
    5. Always include dimension in GROUP BY if they appear in the user query or 'across', 'by' clauses
        E.g. Give me the premium for zurich in canada across products (In this products should be in GROUPBY)
    6. Extract filters and context only from explicit user query mentions. Do not infer unstated dimensions or filters.
    7. Always use `Carrier_Group` instead of `Carrier_Name`.
    8. Always refer to the table schema to get the correct column names.


    [DOMAIN METRICS]
    - Peer Average:
        1. Query the `Peers` table WHERE Carrier_Group = [user's carrier]
            - Apply `Country` filter only if explicitly mentioned in the query or derived from context.
            - Extract the unique `Overall_Peer_Group` value(s)

        2. Use this list to filter the `GPR` table.
            - Apply all other user filters (year, region, sub-product, segment, etc.).
            - Compute the Peer Average premium for that group.
            - Return only the aggregated peer average (optionally alongside the carrier’s own premium if the user is comparing)

        Calculation:- WITH peer_group AS (SELECT Overall_Peer_Group FROM Peers WHERE Carrier_Group = [user's carrier])
                          SELECT AVG(Premium) FROM GPR WHERE Carrier_Group IN (SELECT Overall_Peer_Group FROM peer_group)

    - Marsh Premium:
        1. Marsh is an insurance broker (not a carrier or client)
        2. To compute Marsh Premium, query `GPR` table with ALL user-specified filters EXCEPT `Carrier_Group`
        3. This returns total market premium for the filtered dimensions.
        4. Use this value for Marsh comparisons and benchmarking

        Example: If user asks "Chubb premium vs Marsh", compute Chubb's premium AND total market premium without `Carrier_Group` filter.

    - Share of Wallet (SoW):
        Definition: Ratio of a carrier's premium to total market premium in Marsh's book

        Calculation:
        1. Numerator: SUM(Premium) for the specific carrier with all user filters
        2. Denominator: SUM(Premium) for ALL carriers with the same user filters (no `Carrier_Group` filter)
        3. Result: ROUND(100.0 * Numerator / NULLIF(Denominator, 0), 1)

        Rules:
        - Always use PARTITION BY {relevant filters} in window function
        - Apply only filters explicitly mentioned in user query
        - If no filters specified, use raw totals
        - Never restrict denominator by `Carrier_Group`

    - Share of Portfolio:
        Definition: A carrier's premium share within their own portfolio for a specific dimension

        Calculation:
        1. Numerator: SUM(Premium) for this carrier by dimension (e.g., Product)
        2. Denominator: SUM(Premium) for this carrier across all values of that dimension
        3. Result: ROUND(100.0 * Numerator / NULLIF(Denominator, 0), 3)

        Rules:
        - PARTITION BY Carrier_Group
        - GROUP BY the dimension mentioned in user query (e.g., GROUP BY Product if user asks "premium by product")
        - Always use PARTITION BY Carrier_Group even when looking at other dimensions


    [TIMEFRAME RULES]
    1. Time Period Interpretation:

    When user mentions time-related terms, interpret as follows:
    - "recent" or "recent period" → Last 30 days (or last available month if current month incomplete)
    - "this quarter" → Current calendar quarter (Q1=Jan-Mar, Q2=Apr-Jun, etc.)
    - "last quarter" → Previous calendar quarter
    - "last year" or "past year" → Full previous calendar year (Jan-Dec)
    - "YTD" (Year-To-Date) → Jan 1 of current year through max available `Billing_Date`
    - "TTM" (Trailing Twelve Months) → Last 12 months from max available `Billing_Date`
    - Specific dates/years → Use exactly as mentioned (e.g., "2024" = Jan 1 - Dec 31, 2024)
    - In data we have separate column as Quarter with values as (Q1, Q2, Q3, Q4) and Year (2023, 2024, 2025), include as described in filters.
        Example:-
        CORRECT Usage:
        ✓ Query: "Chubb Limited premium?"
            Filters: Carrier_Group = 'Chubb Limited', Quarter='Q1', Year=2025

        ✗ Query: "Chubb Limited premium?"
            Filters: Carrier_Group = 'Chubb Limited', Quarter='2025-Q1'

        Exception: If query explicitly specifies date range, use that range exactly.

    2. **ALWAYS** Derive Time Period from `Billing_Date`:
        Steps:
        a) Identify the time term in user query
        b) Map to `Billing_Date` range using interpretations from Rule 1
        c) Filter WHERE Billing_Date >= start_date AND Billing_Date <= end_date
        d) If no time term mentioned, default to MAX(Billing_Date)

    3. YoY (Year-over-Year) Comparison Special Logic:

    CRITICAL: Always compare equivalent time periods

    Algorithm:
    a) Identify the two years to compare (e.g., 2025 vs 2024)
    b) Determine data availability:
        - What is the max `Billing_Date` for 2025? (e.g., Q1 end = Mar 31, 2025)
        - What is the max `Billing_Date` for 2024?
    c) *For accurate comparison, align incomplete years with the same period from the prior year. For instance, if 2025 has data only through Q1, compare it against Q1 2024*.
    d) Compute comparison using same date ranges for both years
    e) Return both years' data alongside each other for user context

    4. Renewal Date Logic:
    If query is about "renewal", "renew", "expiry", or "expires":
    a) Use `Cover_Expiry_Date` instead of Billing_Date
    b) Define "renewals that are due":
        - WHERE Cover_Expiry_Date >= TODAY AND Cover_Expiry_Date <= [TODAY + 90 days]
        OR
        - If user specifies timeframe (e.g., "renewals next quarter"), use that range
    c) Apply all other user filters (Carrier, Country, Product, etc.)

    5. Quarter Mapping (if needed):

    Calendar quarters (for ambiguous "this quarter", "last quarter"):
    - Q1 = January 1 - March 31
    - Q2 = April 1 - June 30
    - Q3 = July 1 - September 30
    - Q4 = October 1 - December 31

    6. Output Format:

    For YoY queries, always return data for BOTH periods with clear labels:
    - "2025 (Jan-Mar): $X premium"
    - "2024 (Jan-Mar): $Y premium"
    - "Growth: Z%"


    [ENTITY & FILTER INTEPRETATION]
    1. Geographic Entities:

        Market/Region Mapping:
        - 'Asia', 'Asian market'-> Region = 'Asia'
        - 'North America', 'NA' → Region = 'North America'
        - 'Europe', 'European market' -> Region = 'Continental Europe'
        - 'Global', 'overall market' → No Region filter applied

        Country Specification:
        - Country names (Canada, Singapore, US, etc.) → Apply Country filter directly
        - When both Country AND Market/Region mentioned:
            * Primary: Use Country as the filter
            * Validation: Ensure Country falls within specified Region
            * If conflict (e.g., "US in Asia"), flag and use Country only

        If only Market mentioned → Map directly to Region field

    2. Business Entities:

        Carrier_Group:
        - Always use exact, complete Carrier_Group values (no abbreviations or truncation)
        - Examples of correct usage:
            * User says "Premium for AIG GROUP" → Query: Carrier_Group = 'AIG GROUP'

        - These values are critical for hierarchical calculations; truncation breaks results

    3. General Principle - Entity Inclusion:

    Core Rule: Include only entities explicitly mentioned in user query

    What counts as "explicitly mentioned":
    - Directly stated: "in Canada", "for AIG", "by product"
    - Contextually implied: "by product" implies `Product_Line` dimension
    - Standard defaults: Apply default timeframe if not specified

    What NOT to add:
    - Dimensions or filters not mentioned and not implied
    - Conflicting entities
    - Inferenced relationships not stated by user

    Exception for Standard Context:
    - Timeframe: If not specified, do not apply timeframe filter
    - Reason: Timeframe is needed for accurate calculations

    4. Examples:

    CORRECT Usage:
    ✓ Query: "Chubb Limited premium?"
        Filters: Carrier_Group = 'Chubb Limited'
        Dimensions: None
        Timeframe: None

    ✓ Query: "Chubb premium in Canada by product"
        Filters: Carrier_Group = 'Chubb Limited', Country = 'Canada'
        Dimensions: GROUP BY Product_Line

    ✓ Query: "Top 3 carriers in asia for 2024"
        Filters: Region = 'Asia', Year = 2024
        Dimensions: None
        Ranking: Top 3 by SUM(Premium)

    ✗ Query: "Chubb Limited premium"
        INCORRECT: Adding Region = 'Asia' without user mentioning "Asia"
        CORRECT: Only Carrier_Group = 'Chubb Limited'


    ✗ Query: "Premium by product in Canada"
        INCORRECT: Using Product_Line as filter
        CORRECT: GROUP BY Product_Line, apply Country = 'Canada' as filter


    [CONFIDENTIALITY & AGGREGATION]

    APPLIES TO: All reasoning and planning outputs, regardless of metric type
    (premium, YoY, rank, rolling 12 months, share of portfolio, share of wallet, etc.)

    1. Aggregation Requirements:

    General Principle: Always aggregate data before displaying results

    Aggregation by Metric Type:
    - Refer to Domain Metrics section for metric-specific aggregation
    - Share of Wallet (SoW): SUM(Premium) / SUM(Premium) [see Domain Metrics]
    - Share of Portfolio: SUM(Premium) / SUM(Premium) [see Domain Metrics]
    - Peer Average: AVG(Premium) [see Domain Metrics]
    - Marsh Premium: SUM(Premium) excluding Carrier filter [see Domain Metrics]

    Default aggregation (if metric not explicitly defined):
    - Financial metrics (premiums, costs): Use SUM()
    - Count metrics: Use COUNT()

    Grouping:
    - Always GROUP BY all dimensions mentioned in the query
    - If multiple dimensions (e.g., Product + Country), show aggregation per combination
    - Never display unaggregated raw data rows

    Examples:
    ✓ Query: "Premium by carrier" → GROUP BY Carrier_Group, SUM(Premium) → one row per carrier
    ✓ Query: "Average premium by product and country" → GROUP BY Product_Line, Country, AVG(Premium)
    ✗ Query: "Premium by carrier" → Show individual rows → WRONG, must aggregate

    2. Peer Confidentiality Constraints:

    Core Rule: Never display individual peer names or identifiers in results

    What constitutes "individual peer":
    - Named peer entities (AIG GROUP, AXA, ZURICH, etc.)
    - Breakdown showing results per named peer
    - Any identification linking a result to a specific peer

    Correct Aggregation for Peers:
    - Aggregate ALL peers in the group into a SINGLE "Peer Group" metric

    Correct Output Format:
    ✓ "Peer Group Average Premium: $X"
    ✓ "Large Peers Average: $X; Mid-Market Peers Average: $Y"
    ✓ "Comparison: Chubb ($X) vs Peer Group ($Y)"

    Incorrect Output Format:
    ✗ "AIG GROUP (Peer): $X, AXA (Peer): $Y, ZURICH(Peer): $Z"
    ✗ "Individual peers: [details by peer name]"
    ✗ "Peer A: $X, Peer B: $Y" (even if coded)

    Calculation:
    - Use AVG(Premium) across all peers in group: SUM(ALL_peer_premiums) / COUNT(peers)
    - Never show individual premium values for peers

    3. Carrier vs Peer Comparisons:

    For comparison queries (Carrier vs Peer):
    - Compute: Carrier's SUM(Premium) vs Peer Group's AVG(Premium)
    - Do not use raw individual data rows
    - Do not show peer breakdown within the comparison

    Example Query: "How does Chubb compare to peers?"
    ✓ Output: "Chubb Premium: $X | Peer Group Average: $Y | Difference: $Z"
    ✗ Output: "Chubb: $X | AIG GROUP: $Y | AXA: $Z | Average: $W"

    4. Reasoning and Query Plan Generation:

    When writing reasoning steps or explaining query logic:
    - Explicitly state aggregation method (e.g., "GROUP BY Carrier_Group, calculate SUM(Premium)")
    - For peer metrics, explicitly write: "Calculate peer group average only, not individual peers"
    - Explain WHY aggregation is applied (confidentiality, accuracy, business logic)
    - Be specific about dimensions in GROUP BY clause

    Examples:
    ✓ "Step 1: GROUP BY Carrier_Group, calculate SUM(Premium) for each carrier"
    ✓ "Step 2: Calculate peer group average premium (confidentiality constraint: no individual peers)"
    ✗ "Step 1: Calculate premium" (too vague)
    ✗ "Step 2: Get peer data" (doesn't specify aggregation)

    """

    query_rules = """

        [DOMAIN METRICS]

        - Share of Wallet (SoW): Carriers premium (all other filters applied) / total premium (without applying carrier filter).
        - Share of Portfolio: Carrier's premium share within its own portfolio, i.e., within the same dimension (e.g., product)

        Peer Average: Always follow the important mandatory steps
        SELECT Overall_Peer_Group, Filter LOWER(Carrier_Group)


        [GUIDELINES]
        1. Follow all steps and rules in the reasoning plan exactly.
        2. Always use **sub-queries** and **IN clauses** instead of JOINs.
        3. Use **LOWER()** for all text comparisons in WHERE clauses for case-insensitivity.
        4. Use **NULLIF()** for any division to avoid divide-by-zero errors.
        5. Use **COALESCE()** to safely handle NULLs when aggregating.
        6. Use **LIMIT** and **ORDER BY** for ranking logic.
        7. Do NOT create new columns or metrics not mentioned in reasoning.
        8. Do NOT output explanations — output only SQL.
        9. Never add entities that are not mentioned in the user query.
        10. Do not assume anything, strictly get the context and filters from user query.



        [TIMEFRAME RULES]
        1. When the user mentions any time-related term (e.g., recent, past, last quarter, YTD, TTM) us `Billing_Date` to derive the time period.
        2.  If the period is vague (e.g., "recent period"), interpret is as:
            - "MAX(Billing_Date) as the most recent date."
            - "Then, include data from the start of the previous quarter up to that MAX(Billing_Date)."
            - If a specific year or range is mentioned, filter accordingly.
        3. If the query is about renewals refer to `Cover_Expiry_Date` to get the renewals that are due.

        [ENTITY RULES]
        1. Always use `Carrier_Group` column instead of `Carrier_Name` from the `GPR` table for grouping and filtering.

        [AGGREGATION AND CONFIDENTIALITY RULES]

        1. Always use **SUM()** when calculating any score, index, or metric value for a carrier.
        - Example: `SUM(Premium)` instead of individual values.

        2. For peer-related results:
        - Always compute the **peer average**; never list or display scores of individual peers.
        - Use `WHERE Carrier IN (subquery for peers)` and wrap in `AVG()`.

        3. For carrier, product, or dimension-level comparisons:
        - Compute **total or sum of premium** using `GROUP BY`.
        - Example:
            ```sql
            SELECT Product, SUM(Premium) AS total_premium
            FROM GPR
            WHERE LOWER(Carrier_Group)='zurich' AND LOWER(Country)='canada'
            GROUP BY Product;
            ```

        [NOTES]
        - Always write syntactically correct SQLite queries.
        - Handle multi-step logic using sub-queries exactly as described.
        - Never use JOINs.
        - Never add or omit filters not present in the reasoning.
        - The reasoning plan is the source of truth.

    """

    gpr_few_shot_dict = {
        "example_1": {
            "user_query": "Show chubb limited premium vs peer average by product in singapore for the year 2024.",
            "sql_query": '''WITH peer_groups AS (
                                SELECT DISTINCT p."Overall_Peer_Group"
                                FROM Peers p
                                WHERE LOWER(p.Country) = LOWER('singapore')
                                AND LOWER(p."Carrier_Group") = LOWER('chubb limited')
                            )

                            SELECT Product_Line as Products,
                                   SUM(CASE WHEN LOWER(P.Carrier_Group) = LOWER('chubb') THEN P.Premium END) AS carrier_premium,
                                   AVG(CASE WHEN P.Carrier_Group IN (SELECT Overall_Peer_Group FROM peer_groups) THEN P.Premium END) AS peer_average_premium
                            FROM GPR P
                            WHERE LOWER(P.Country) = LOWER('singapore')
                            AND P.Year = 2024

                            GROUP BY P.Product_Line
                            ORDER BY carrier_premium;"''',
        },
        "example_2": {
            "user_query": "What is the appetite of zurich in singapore across different products?",
            "sql_query": '''"SELECT Carrier_Group, Product_Line, SUM(Premium) AS carrier_premium, ROUND(100.0 * SUM(Premium) / NULLIF(SUM(SUM(Premium)) OVER (PARTITION BY Carrier_Group), 0), 1) AS Appetite
                        FROM GPR
                        WHERE LOWER(Country) = LOWER('singapore')
                        AND LOWER(Carrier_Group) = LOWER('ZURICH')
                        GROUP BY Carrier_Group, Product_Line
                        ORDER BY Appetite DESC;"''',
        },
        "example_3": {
            "user_query": "What is the SoW of chubb in canada across segments.",
            "sql_query": '''"WITH product_totals AS (SELECT Country, Client_Segment, Carrier_Group, SUM(Premium) AS carrier_premium, SUM(SUM(Premium)) OVER (PARTITION BY Country, Client_Segment) AS total_premium
                                FROM GPR
                                WHERE LOWER(Country) = LOWER('canada')
                                GROUP BY Carrier_Group, Client_Segment
                                )
                                SELECT Carrier_Group, Client_Segment, carrier_premium, ROUND(((carrier_premium / total_premium) * 100), 1) AS SoW
                                FROM product_totals
                                WHERE LOWER(Carrier_Group) = LOWER('chubb')
                                ORDER BY SoW DESC;"''',
        },
        "example_4": {
            "user_query": "What is change in rank over past 3 years for zurich in canada in property",
            "sql_query": '''"WITH ranked_data AS (
                                SELECT
                                    Carrier_Group,
                                    Country,
                                    Product_Line,
                                    Year,
                                    SUM(Premium) AS total_premium,
                                    RANK() OVER (
                                        PARTITION BY Country, Product_Line, Year
                                        ORDER BY SUM(Premium) DESC
                                    ) AS rank_in_year
                                FROM GPR
                                WHERE
                                    LOWER(Country) = 'canada'
                                    AND LOWER(Product_Line) = 'property'
                                GROUP BY Carrier_Group, Country, Product_Line, Year
                            )
                            SELECT
                                Carrier_Group,
                                Country,
                                Product_Line,
                                Year,
                                rank_in_year,
                                LAG(rank_in_year, 1) OVER (
                                    PARTITION BY Carrier_Group, Country, Product_Line
                                    ORDER BY Year
                                ) AS prev_year_rank,
                                (LAG(rank_in_year, 1) OVER (
                                    PARTITION BY Carrier_Group, Country, Product_Line
                                    ORDER BY Year
                                ) - rank_in_year) AS change_in_rank
                            FROM ranked_data
                            WHERE
                                LOWER(Carrier_Group) = 'zurich'
                            ORDER BY Year;"''',
        },
        "example_5": {
            "user_query": "what is premium for chubb in singapore for trailing twelve months across sic major?",
            "sql_query": '''"SELECT Carrier_Group, SIC_Major_Class, SUM(Premium) AS carrier_premium
                                FROM GPR
                                WHERE LOWER(Country) = 'singapore'
                                AND LOWER(Carrier_Group) = 'chubb'
                                AND Billing_Date >= DATE((SELECT MAX(Billing_Date) FROM GPR), '-12 months') AND Billing_Date < DATE((SELECT MAX(Billing_Date) FROM GPR))
                                GROUP BY Product_Line
                                ORDER BY carrier_premium DESC;"''',
        },
    }

    gpr_query_few_shots = [
        Example(inputs={"user_query": ex["user_query"]}, outputs={"sql_query": ex["sql_query"]})
        for ex in gpr_few_shot_dict.values()
    ]

    response_rules = """
    0. GLOBAL TERMINOLOGY (mandatory)
    - Refer to the metric stored as `Appetite` as "Share of Portfolio" in every sentence, table header, and label. Even if the user's question uses "appetite", reply using "Share of Portfolio".

    1. INTERPRET, DON'T JUST RESTATE
    - Read like a sharp analyst briefing, not a data dump. Lead with the "so what" for the carrier: growth, share movement, concentration, retention, pricing power, or competitive position.
    - Use directional, evaluative language (grew, slipped, outpaced, lagged, concentrated) ONLY when the returned data supports it, and quantify the movement.
    - Call out disconnects the data reveals (e.g. premium up but Share of Wallet down = the market grew faster than the carrier).
    - Where the evidence warrants, add a brief, specific implication or next step tied to a number you just cited — never generic filler.
    - Use the reasoning plan to fill in context not present in the user query (e.g. which two years a YoY used); state it for clarity.

    2. GROUNDING GUARDRAILS (non-negotiable)
    - Every figure must come from the data or `query_plan`. Never invent numbers, ranks, products, causes, or market conditions.
    - If a claim is not evidenced by the data, do not make it. If the result is empty, say no data was returned for the selected filters.
    - Refer to peers only in aggregate (`Peer Group` / `Peer Average`); never name or value an individual peer.

    3. NUMERIC FORMAT & TIMEFRAME
    - Premium values are in USD: always show the $ sign and no decimal places.
    - Show YoY / Share of Wallet / Share of Portfolio / variance as % (YoY rounded to 2 decimals).
    - For any timeframe query (TTM, MoM, YoY) ALWAYS state the period/years considered. Infer from the valid_year_quarter input (unique year+quarter values); e.g. last 12 months -> from 2024 to latest 2025.
    - If years are absent from the output and query, infer the timeframe from the `query_plan`; if none, state that all years are considered.
    - Preserve numerical precision (e.g. "12.5%", not "about 13%"); retain exact periods (e.g. "Q2 2025").

    4. FORMAT
    - Bold key terms (Carriers, Products, Metrics, Years). Keep it concise and readable.
    - For comparative or multi-row data (>3 records), anchor the discussion to a compact markdown table of the key rows, then interpret it. Example:
        | Carrier | Product | Metric | Value | Year |
        |----------|----------|---------|--------|------|
        | Zurich | Property | Premium | $8M | 2024 |
        | Chubb  | Casualty | Share of Wallet | 12% | 2024 |
    """

