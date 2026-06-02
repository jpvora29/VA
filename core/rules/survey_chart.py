"""Chart-creation rules for the Survey flow.

Phase 2 migration target — see `core/rules/__init__.py`.
"""
from __future__ import annotations


class SurveyChartRules:
    chart_creation_rules = """
    1. Chart Type Selection
    - Use **bar chart** when a SINGLE comparing numerical metrics (Score, Score Growth %) across discrete categories (e.g., SurveyPractice, Carrier, SurveyCountry).
    - Use **line chart** for trends over time (e.g., Year, Quarter, Month). Prioritize when X-axis represents temporal progression. **NOTE: Use LINE CHART STRICTLY for Rolling 12 months, Month-on-Month, Year-over-Year**
    - Use **pie or donut chart** for proportion analysis where categories are few (≤6) and total = 100% (e.g., Score by Sections).
    - Use **scatter plot** to show relationships or correlations between TWO numeric measures (e.g., Score vs YoY Growth, Score % vs NPS Score).
    - Use **none** when the output is a single scalar value or a KPI (e.g., average score).

    - Preliminary Check for Categorical Data:
        - Before deciding on the chart type, first verify if any categorical columns are present in the SQL output.
            - **If NO categorical columns exist dont create any chart.**
            - If categorical columns ARE present, proceed with the detailed decision rules below.

    - Detailed Decision Rules:
        - Choose **scatter plot** when comparing TWO numeric values that:
            a) Are of different types (e.g., Score vs. Percentage), or
            b) Are of the same type but belong to different numeric category columns.
        - Choose **bar chart** when comparing:
            a) A SINGLE numeric value across categories, or
            b) TWO numeric values of the same type belonging to same numeric category columns.
        - Choose **line chart** specifically for rolling 12 months, month-on-month, or year-over-year data.

    - Clarification on Common Confusions:
        - Bar Chart vs. Scatter Plot (for comparing 2 numerical metrics across one or no categorical metric):
            - Case 1: Different types of values (e.g., Score vs. Percentage) → **scatter plot**
            - Case 2: Same type of values and same numeric category columns (e.g., Average Score for Carrier_1 vs. Average Score for Carrier_2) → **bar chart**
        - Bar Chart vs. Pie Chart (for comparing 1 numerical metric across categories):
            - Case 1: Number of categories ≤ 6 → **pie chart**
            - Case 2: Number of categories > 6 → **bar chart**
        - Bar Chart vs. Line Chart:
            - Case 1: If data spans MORE THAN 1 year → **line chart**
            - Case 2: If there is NO temporal progression (e.g., data requested for only 1 year) → **bar chart**

    2. Axis and Orientation Rules
    - Default orientation: **vertical** (X = category/time, Y = measure).
    - Note, always keep the orientation **vertical**
    - Sort data descending when showing rankings or top-N results.


    3. Series Rule:
    - The 'series' field defines how data is grouped and color-coded in the chart legend.
    - It should represent the categorical dimension that distinguishes multiple lines, bars, or groups within the same X-axis category.

    4. Legends and Grouping
    - Show legend only if multiple categories or series are present.
    - Color code groups logically (e.g., segments, regions, products).

    5. Titles and Labels
    - The chart title should summarize both metric and breakdown (e.g., “Score by Product, 2024”).
    - Use clear axis labels derived from the selected fields.

    6. Edge Cases
    - When no valid category/time field is detected, default to **scalar value** display.
    - Avoid pie/donut charts for continuous or high-cardinality categories.
    - If multiple suitable chart types apply, prefer the one that best highlights change or distribution.

    7. Parameter Assigning Rule:
    - For Y-axis:-
        - Accepts a List
        - Select the category which has numeric value or a measure, e.g. score, average, etc
        - Note, this accepts list and this can have multiple elements, e.g. [score_1, score_2]

    - For the X-axis and Series:-
        Priority order:
            a) Year - Represents the reporting or survey year
            b) Region - Broad geographic grouping that aggregates multiple countries (e.g., North America, EMEA, APAC, Latin America).
            c) Country - Geographic location where the insurance business, carrier or survey is conducted (e.g., US, Canada, Singapore).
            d) Carrier - An insurance company or underwriting entity that provides insurance coverage to clients.
            e) One of the following (equal-level alternatives):
                i) Practice - Line of Business (LOB) or product area covered in surveys (e.g., Property, Casualty, Cyber, Marine). Represents the insurance product being analyzed.
                OR
                ii) Section - Functional areas or dimensions of service being assessed in surveys, typically reflecting operational activities (e.g., Underwriting, Claims, Policy Servicing, Loss Control).
                OR
                iii) Attribute - Specific survey questions or metrics within a section that measure performance (e.g., Responsiveness, Accuracy, Timeliness).
                OR
                iv) Segment - Client or business grouping dimension, typically based on type of business or relationship stage (e.g., Large Corporate, Mid-Market).

        - **Assignment rules:**
            1) For X-axis:-
                - Accepts a string
                - Case 1:-
                    - If "chart_type" is "scatter plot", then **Strictly select any of the Numerical Metric**
                - Case 2:-
                    - For all the other cases, **Strictly select the highest priority categorical field available from the list above.**

            2) For Series:-
                - Accepts a List
                - After selecting Y-axis and X-axis fields, assign remaining relevant categorical fields from the priority list in descending order.
                - The first element in the series list should have the highest remaining priority, followed by lower priorities

        - **Validation:**
            - Before finalizing, verify that the X-axis field is the highest priority categorical field available.
            - Verify that the Series list excludes the X-axis and Y-axis fields.
            - Verify that all the remaining relevant categorical fields are included in Series. **Irrespective of the "chart_type"**
            - If these conditions are not met, reassign fields accordingly.

    - For bar_mode:-
        - It accepts a List
        - This should be filled only when 'chart_type' is 'bar chart'
        - If the 'chart_type' is 'bar chart', then assert that, len(series) == len(bar_mode)
        - 'bar_mode' must only have:-
            1) 'group' - Always

    - Additional notes / tie-break behavior
        - Always prefer the highest item in the applicable priority list.
        - When multiple fields share the same priority slot (e.g., Practice vs Section), they are interchangeable at that slot; pick one based on context or availability.
        - After assigning X-axis, do not choose the same field as Series—select the next most relevant categorical field per the Series priority list.
        - If only one categorical field is available, use it for X-axis and leave Series empty (or use a default single series).

    - Quick examples
        - Dataset has: Score, Country, Attribute → Y-axis = [Score], X-axis = Country; Series = [Attribute]; Bar Mode = [group].
        - Dataset has: Score_1, Score_2, Year, Region, Country → Y-axis = [Score_1, Score_2], X-axis = Year; Series = [Region, Country]; Bar Mode = [group, group].


    - **The exact field names from the priority list may not appear verbatim in the SQL output. Use the user query and SQL output context to identify the closest matching category.**
    - Ensure to use the **EXACT NAME** present in the **sql_output**


    Use the **EXACT NAME** as in the data for x, y, series fields as its important for chart creation. Same name will be directly used for the chart creation.

    """
