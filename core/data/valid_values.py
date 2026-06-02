"""Fuzzy matching helpers + cached valid-value lookups for each SQL flow.

`GetValidData` exposes class-level dicts of valid values and column definitions
for Survey, GPR, and GIMMI tables, and rapidfuzz-backed lookups that the
planner/SQL-agent nodes use to pin LLM input down to a single country or
short list of carriers (reduces prompt noise + hallucination risk).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process, utils

from config.valid_values_config import *  # noqa: F401,F403 - preserves legacy import surface


class GetValidData:
    """Fuzzy-match helpers + cached column metadata for all three flows.

    Methods are called on the class (`GetValidData.extract_country(...)`), not
    on instances; that's why they have no `self` parameter.
    """

    def extract_country(
        user_query: str,
        valid_countries: List[str],
        score_cutoff: Optional[int] = 60,
    ) -> Optional[str]:
        """Return the best-matching country from `valid_countries` for `user_query`.

        Args:
            user_query: The natural-language user query.
            valid_countries: All valid country values in the relevant table.
            score_cutoff: Minimum rapidfuzz `partial_ratio` score; defaults to 60.

        Returns:
            The matched country, or None if no match meets the cutoff.
        """
        match = process.extractOne(
            user_query,
            valid_countries,
            scorer=fuzz.partial_ratio,
            processor=utils.default_process,
            score_cutoff=score_cutoff,
        )
        return match[0] if match else None

    def extract_carriers(
        user_query: str,
        country_carrier_dict: Dict[str, List[str]],
        country: str,
        top_n: Optional[int] = 10,
        score_cutoff: Optional[int] = 0,
    ) -> Optional[List[str]]:
        """Return the top-N carriers for `country` best matching `user_query`.

        Args:
            user_query: The natural-language user query.
            country_carrier_dict: Mapping of country to its valid carriers.
            country: Country resolved from `extract_country`.
            top_n: Maximum carriers to return.
            score_cutoff: Minimum rapidfuzz `partial_ratio` score.

        Returns:
            A list of up to `top_n` matched carriers, an empty list if the
            country has no carriers, or None if no matches meet the cutoff.
        """
        choices = country_carrier_dict.get(country, [])
        if not choices:
            return []
        match = process.extract(
            user_query,
            choices,
            scorer=fuzz.partial_ratio,
            processor=utils.default_process,
            limit=top_n,
            score_cutoff=score_cutoff,
        )
        return [val[0] for val in match] if match else None

    def matching_values(
        user_query: str,
        valid_countries: List[str],
        country_carrier_dict: Dict[str, List[str]],
    ) -> Tuple[Optional[str], Optional[List[str]]]:
        """Convenience wrapper: returns (country, carriers) for one query."""
        country = GetValidData.extract_country(
            user_query=user_query, valid_countries=valid_countries
        )

        carriers = GetValidData.extract_carriers(
            user_query=user_query,
            country_carrier_dict=country_carrier_dict,
            country=country,
        )

        return country, carriers

    # ------------------------------------------------ SURVEY DATA ------------------------------------------------

    valid_values: Dict[str, list] = {
        "SurveyPractice": valid_practices,
        "Carrier": valid_carriers,
        "Region": valid_regions,
        "Sections": valid_sections,
        "Attributes": valid_attributes,
        "Survey_Year": valid_years,
        "SurveySegment": valid_segments,
    }

    definitions: Dict[str, str] = {
        "SurveyCountry": "Geographic location where the insurance business, carrier or survey is conducted (e.g., US, Canada, Singapore).",
        "Carrier": "An insurance company or underwriting entity that provides insurance coverage to clients.",
        # "Carrier_Group": "A parent or consolidated group of carriers under the same corporate ownership (e.g., Chubb Group, Zurich Group). Used to aggregate performance across affiliated carriers.",
        "Survey_Year": "Represents the reporting or survey year",
        "SurveyPractice": "Line of Business (LOB) or product area covered in surveys (e.g., Property, Casualty, Cyber, Marine). Represents the insurance product being analyzed.",
        "Score": "Survey Score ranging from 1-9.",
        "Regions": "Broad geographic grouping that aggregates multiple countries (e.g., North America, EMEA, APAC, Latin America).",
        "Section": "Functional areas or dimensions of service being assessed in surveys, typically reflecting operational activities (e.g., Underwriting, Claims, Policy Servicing, Loss Control).",
        "Attribute": "Specific survey questions or metrics within a section that measure performance (e.g., Responsiveness, Accuracy, Timeliness).",
        "SurveySegment": "Client or business grouping dimension, typically based on type of business or relationship stage (e.g., Large Corporate, Mid-Market).",
        "NPS Score": "Net Promoter Score rating provided by the respondent on a 0–10 scale, indicating likelihood to recommend the carrier.",
        "NPS_Group": "Classification of the NPS_Score into standard groups: Promoters (9–10) = highly satisfied and loyal clients. Passives (7–8) = neutral clients. Detractors (0–6) = dissatisfied clients.",
        "YoY Growth": "Year-over-year change in metric value = (CurrentYear - PreviousYear) / PreviousYear * 100",
        "Peer Average": "Aggegrated score of all the distinct peers for the mentioned carrier.",
    }

    # ------------------------------------------------ GPR DATA----------------------------------------------------------------------------------

    valid_values_gpr: Dict[str, list] = {
        "Region": valid_regions_gpr,
        "Country": valid_countries_gpr,
        "Carrier_Group": valid_groups_gpr,
        "Product_Line": valid_products_gpr,
        "Business_Line": valid_business_lines_gpr,
        "Client_Segment": valid_segments_gpr,
    }

    # valid_country_carrier_group = get_country_carrier_value(Initialization.engine, "GPR", "Country", "Carrier_Group")

    definitions_gpr: Dict[str, str] = {
        "Billing_Date": "The date on which the insurance premium was billed or invoiced to the client. It reflects the financial transaction timing and is used to derive temporal metrics such as year and month for analysis.",
        "Region": "A broad geographical classification that groups multiple countries or markets for strategic, reporting, or regulatory purposes (e.g., Asia, North America, MENA, LAC). Used for regional trend analysis and business performance segmentation.",
        "Country": "The specific country in which the insurance policy was issued, where the risk is located, or where the client is based. It is used for country-level reporting, regulatory compliance, and local market insights.",
        "Product_Line": "A high-level categorization of insurance products based on the type of risk covered (e.g., Property, Casualty, FINPRO etc). It helps group offerings into strategic portfolios for underwriting, reporting, and performance tracking.",
        "Business_Line": "A sub-classification within the Product Line that specifies the type of coverage or client solution offered (e.g., Marine Cargo under Property, D&O under Financial Lines). It provides finer granularity to understand the nature of the risk and coverage.",
        "Cover_Line": "The most granular level of insurance categorization, describing the specific type of coverage within a Business Line (e.g., Fire, Earthquake, Theft under Property). It is essential for claims analysis, underwriting practices, and loss trend tracking.",
        "SIC_Minor_Class": "A sub-category of the Standard Industrial Classification (SIC) code that provides a more detailed description of the client’s industry activity. It enables niche market segmentation and underwriting precision.",
        "SIC_Major_Class": "A broader classification within the SIC system that groups related SIC Minor Classes under a major industry umbrella (e.g., Services, Manufacturing). It is used for macro-level industry performance and trend analysis.",
        "Client_Segment": "A classification of clients based on size, revenue, risk profile, or strategic importance (e.g., Risk Management, Corporate, Commerical etc). This segmentation supports differentiated service models, pricing strategies, and account management.",
        "Premium": "The total gross amount charged to the client for the insurance coverage provided, typically measured in monetary terms (e.g., USD). It reflects the value of the policy and is a core metric for revenue and performance analysis.",
        "Carrier_Group": "A grouping of individual insurance carriers under a parent or holding entity (e.g., AIG includes various AIG companies). Used to consolidate reporting and analyze group-level performance across markets.",
        "Year": "The calendar year extracted from the Billing Date, used for year-over-year comparisons, trend analysis, and financial reporting.",
        "Month_Name": "The calendar month (e.g., January, February) derived from the Billing Date, used for seasonality analysis, monthly reporting, and premium trend evaluation.",
        "CLIENT_NAME": "The legal or standardized name of the insured entity (individual, company or organization) for which the insurnace policy is issued and premiums are recorded",
    }

    # ------------------------------------------------ GIMMI DATA----------------------------------------------------------------------------------

    gimmi_valid_values: Dict[str, list] = {
        "Region": ["US", "Canada", "Latam", "United Kingdom", "CE", "Asia", "Pacific"],
        "Product": ["Overall", "Casualty", "Property", "Cyber", "FINPRO"],
        "Year": [2024, 2023, 2022, 2025],
        "Quarter": ["Q1", "Q2", "Q3", "Q4"],
    }

    gimmi_definitions: Dict[str, str] = {
        "Product": "A high-level categorization of insurance products based on the type of risk covered (e.g., Property, Casualty, FINPRO etc). It helps group offerings into strategic portfolios for underwriting, reporting, and performance tracking.",
        "Market_Composite_Rate": "The Market composite rate (%) for particular product compared to last quarter",
        "Year": "The calendar year, used for year-over-year comparisons, trend analysis, and financial reporting.",
        "Quarter": "The calendar quarter (e.g. Q1, Q2, Q3, Q4) used for quartely reporting, trend evalution",
        "Region": "A broad geographical classification that groups multiple countries or markets for strategic, reporting, or regulatory purposes (e.g., Asia, North America, MENA, LAC). Used for market trend analysis and business performance segmentation.",
    }
