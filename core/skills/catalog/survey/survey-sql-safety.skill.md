---
name: survey-sql-safety
description: SQL safety, sub-query, aggregation and grouping rules that apply to every Survey planner output.
flow: survey
scope: [planner]
always: true
priority: 100
---

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
