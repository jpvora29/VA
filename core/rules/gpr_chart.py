"""Chart-creation rules for the GPR (premium) flow.

Phase 2 migration target — see `core/rules/__init__.py`.
"""
from __future__ import annotations


class GPRChartRules:

    chart_creation_rules = """
    1. Chart Type Selection
    - Use **bar chart** when a SINGLE comparing numerical metrics (Premium, Premium Growth %) across discrete categories (e.g., Product, Carrier, Country, Segment, Industry) or when showing multiple series across the same X-axis (e.g., Premium by Segment for each Carrier).
    - Use **line chart** for trends over time (e.g., Year, Quarter, Month). Prioritize when X-axis represents temporal progression. **NOTE: Use LINE CHART STRICTLY for Rolling 12 months, Month-on-Month, Year-over-Year**
    - Use **pie or donut chart** for proportion analysis where categories are few (≤6) and total = 100% (e.g., Apetite, Portfolio).
    - Use **scatter plot** to show relationships or correlations between TWO numeric measures (e.g., Carriers Premium vs Peers Premium, Carriers Growth vs Marsh Growth).
    - Use **none** when the output is a single scalar value or a KPI (e.g., premium).

    - Preliminary Check for Categorical Data:
        - Before deciding on the chart type, first verify if any categorical columns are present in the SQL output.
            - **If NO categorical columns exist dont create any chart.**
            - If categorical columns ARE present, proceed with the detailed decision rules below.

    - Detailed Decision Rules:
        - Choose **scatter plot** when comparing TWO numeric values that:
            a) Are of different types (e.g., Premium vs. Percentage), or
            b) Are of the same type but belong to different numeric category columns.
        - Choose **bar chart** when comparing:
            a) A SINGLE numeric value across categories, or
            b) TWO numeric values of the same type belonging to same numeric category columns.
        - Choose **line chart** specifically for rolling 12 months, month-on-month, or year-over-year data.

    - Clarification on Common Confusions:
        - Bar Chart vs. Scatter Plot (for comparing 2 numerical metrics across one or no categorical metric):
            - Case 1: Different types of values (e.g., Premium vs. Percentage) → **scatter plot**
            - Case 2: Same type of values but different numeric category columns (e.g., Percentages for Share of Wallet vs. Percentages for Share of Portfolio) → **scatter plot**
            - Case 3: Same type of values and same numeric category columns (e.g., Percentages for Appetite vs. Percentages for Share of Portfolio) → **bar chart**
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
    - Use clear axis labels derived from the selected fields.

    6. Edge Cases
    - When no valid category/time field is detected, default to **scalar value** display.
    - Avoid pie/donut charts for continuous or high-cardinality categories.
    - If multiple suitable chart types apply, prefer the one that best highlights change or distribution.

    7. Parameter Assigning Rule:
    - For Y-axis:-
        - Accepts a List
        - Select the category which has numeric value or a measure, e.g. premium, share of portfolio etc
        - Note, this accepts list and this can have multiple elements, e.g. [premium_1, premium_2]

    - For the X-axis and Series:-
        Assign based on the following priority order of categorical fields:
            a) Year - Represents the year when the insurance premium was billed or invoiced to the client
            b) Region - Broad geographic grouping that aggregates multiple countries (e.g., North America, EMEA, APAC, Latin America).
            c) Country - Geographic location where the insurance policy was issued, where the risk is located, or where the client is based (e.g., US, Canada, Singapore).
            d) Carrier_Group - A grouping of individual insurance carriers under a parent or holding entity (e.g., AIG includes various AIG companies).
            e) One of the following (equal-level alternatives):
                i) Product_Line - A high-level categorization of insurance products based on the type of risk covered (e.g., Property, Casualty, FINPRO etc). Represents the insurance product being analyzed.
                OR
                ii) Cover_Line - The most granular level of insurance categorization, describing the specific type of coverage within a Business Line (e.g., Fire, Earthquake, Theft under Property).
                OR
                iii) Segment - A classification of clients based on size, revenue, risk profile, or strategic importance (e.g., Risk Management, Corporate, Commerical etc).

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
        - Note that, for each element in the series, the corresponding element in the bar_mode descibes what type of chart it will be for 'bar chart'
        - 'bar_mode' must only have:-
            1) 'stack' - For Product_Line, Cover_Line or Segment
            2) 'group' - Otherwise

    - Additional notes / tie-break behavior
        - Always prefer the highest item in the applicable priority list.
        - When multiple fields share the same priority slot (e.g., Product_Line vs Segment), they are interchangeable at that slot; pick one based on context or availability.
        - After assigning X-axis, do not choose the same field as Series—select the next most relevant categorical field per the Series priority list.
        - If only one categorical field is available, use it for X-axis and leave Series empty (or use a default single series).

    - Quick examples
        - Dataset has: Premium, Country, Product_Line → Y-axis = [Premium], X-axis = Country; Series = [Product_Line]; Bar Mode = [stack].
        - Dataset has: Premium_1, Premium_2, Year, Region, Country → Y-axis = [Premium_1, Premium_2], X-axis = Year; Series = [Region, Country]; Bar Mode = [group, group].


    - **The exact field names from the priority list may not appear verbatim in the SQL output. Use the user query and SQL output context to identify the closest matching category.**
    - Ensure to use the **EXACT NAME** present in the **sql_output**

    Use the **EXACT NAME** as in the data for x, y, series fields as its important for chart creation. Same name will be directly used for the chart creation.

    """
