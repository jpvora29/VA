"""Small, hand-checked golden row sets for analytics unit tests.

Deliberately tiny so expected outputs can be verified by eye — the regression
backstop that makes the primitives trustworthy. Columns mirror the real `GPR` and
`Carriers` (survey) schemas (see ``core/data/valid_values.py``).
"""
from __future__ import annotations

# GPR (premium) — Zurich vs a peer across products and two years.
GPR_ROWS = [
    {"Carrier_Group": "Zurich", "Country": "Canada", "Product_Line": "Property", "Year": 2023, "Premium": 100.0},
    {"Carrier_Group": "Zurich", "Country": "Canada", "Product_Line": "Cyber", "Year": 2023, "Premium": 20.0},
    {"Carrier_Group": "Zurich", "Country": "Canada", "Product_Line": "Property", "Year": 2024, "Premium": 140.0},
    {"Carrier_Group": "AIG", "Country": "Canada", "Product_Line": "Cyber", "Year": 2024, "Premium": 80.0},
]

# Survey (perception) — scores by practice/attribute across two survey years.
SURVEY_ROWS = [
    {"Carrier": "Zurich", "SurveyCountry": "Canada", "SurveyPractice": "Property", "Attribute": "Responsiveness", "Survey_Year": 2023, "Score": 6.2},
    {"Carrier": "Zurich", "SurveyCountry": "Canada", "SurveyPractice": "Property", "Attribute": "Accuracy", "Survey_Year": 2024, "Score": 6.5},
    {"Carrier": "AIG", "SurveyCountry": "Canada", "SurveyPractice": "Cyber", "Attribute": "Responsiveness", "Survey_Year": 2024, "Score": 7.1},
]

# Single-period set — timeline gating should NOT fire a multi-year timeline here.
SINGLE_YEAR_ROWS = [
    {"Carrier_Group": "Zurich", "Product_Line": "Property", "Year": 2024, "Premium": 140.0},
    {"Carrier_Group": "Zurich", "Product_Line": "Cyber", "Year": 2024, "Premium": 20.0},
]
