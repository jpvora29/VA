

# ============================== PREFERRED FILTER VALUES  ==================================================

PREFFERED_PITCH_COUNTRY: str = "Singapore"
PREFFERED_PITCH_CARRIER: str = "ZURICH"


# ============================== PITCH FILTERS MAPPING  ==================================================

PITCH_COLUMN_MAP: dict[str, dict[str, str]] = {
    "Carriers": {
        "country": "SurveyCountry",
        "carrier": "Carrier",
        "year": "Survey_Year",
    },
}