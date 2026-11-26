"""A small premium book built to break the QBR deck in every way a real book has.

The seed DB is too tidy to catch the deck's real-world bugs — every carrier writes all six
lines in every country and has a peer group. This book is the opposite:

* twelve lines of business, so a carrier's top-5 lines are NOT its six biggest;
* ``Subject Co`` leads two SMALL lines (#1-2 in Terrorism and Political Risk) while ranking
  outside the top 5 in its big ones, and sits deep (#15) in Environmental;
* ``Subject Co`` writes no Marine at all — the word the product template's titles carry;
* ``Subject Co`` has NO group in the Peers table, while ``Zurich`` has one.

Deterministic: every premium is a fixed function of (carrier, line, country, year, month).
"""

from __future__ import annotations

from pathlib import Path

SUBJECT = "Subject Co"
PEERED = "Zurich"
COUNTRIES = ("Singapore", "Japan")
YEARS = (2024, 2025)
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
OTHERS = (
    "Zurich",
    "AIG",
    "Allianz",
    "AXA XL",
    "Chubb",
    "QBE",
    "Sompo",
    "Tokio Marine",
    "Swiss Re",
    "Berkshire",
    "Liberty Specialty",
    "MS&AD",
    "Beazley",
    "Hiscox",
    "Markel",
)
BIG_LINES = (
    "Property",
    "Casualty",
    "Financial Lines",
    "Cyber",
    "Construction",
    "Aviation",
)
SMALL_LEADS = ("Terrorism", "Political Risk")  # Subject Co ranks #1 / #2 here
DEEP_LINE = "Environmental"  # Subject Co ranks behind every other carrier here
ABSENT_LINES = ("Marine Cargo", "Energy & Power", "Credit")  # Subject Co writes none
LINES = (*BIG_LINES, *SMALL_LEADS, DEEP_LINE, *ABSENT_LINES)

# Subject Co's annual premium per line (millions). Others write 8-40M in the big lines, so
# these land Subject Co between #8 and #14 there.
_SUBJECT_ANNUAL = {
    "Property": 25.0,
    "Casualty": 22.0,
    "Financial Lines": 20.0,
    "Cyber": 18.0,
    "Construction": 15.0,
    "Aviation": 12.0,
    "Terrorism": 3.0,
    "Political Risk": 2.4,
    "Environmental": 0.01,
}


def _other_annual(index: int, line: str) -> float:
    """Another carrier's annual premium (millions) in ``line`` — spread so ranks are clean."""
    if line in BIG_LINES:
        return 40.0 - index * 2.3  # 40.0 … 7.8 — Subject Co falls mid-table
    if line in SMALL_LEADS:
        base = 2.6 if line == "Political Risk" else 1.0  # one carrier beats Subject Co
        return max(base - index * 0.15, 0.05)
    return 4.0 - index * 0.2  # Environmental and the lines Subject Co is absent from


def rows() -> list[dict]:
    """Every premium row of the book."""
    out = []
    for year_i, year in enumerate(YEARS):
        growth = 1.0 + 0.08 * year_i
        for country_i, country in enumerate(COUNTRIES):
            scale = 1.0 - 0.3 * country_i
            for month in MONTHS:
                for line in LINES:
                    if line in _SUBJECT_ANNUAL:
                        out.append(
                            _row(
                                SUBJECT,
                                line,
                                country,
                                year,
                                month,
                                _SUBJECT_ANNUAL[line] * growth * scale,
                            )
                        )
                    for i, carrier in enumerate(OTHERS):
                        out.append(
                            _row(
                                carrier,
                                line,
                                country,
                                year,
                                month,
                                _other_annual(i, line) * scale,
                            )
                        )
    return out


def _row(
    carrier: str, line: str, country: str, year: int, month: str, annual_m: float
) -> dict:
    return {
        "Region": "Asia",
        "Country": country,
        "Carrier_Group": carrier,
        "Product_Line": line,
        "Business_Line": line,
        "Cover_Line": line,
        "Client_Segment": "Commercial",
        "SIC_Major_Class": "Manufacturing",
        "SIC_Minor_Class": "Manufacturing - General",
        "CLIENT_NAME": f"{carrier} client",
        "Premium": round(annual_m * 1_000_000 / 12, 2),
        "Billing_Date": f"{year}-{MONTHS.index(month) + 1:02d}-15",
        "Year": year,
        "Month_Name": month,
    }


def peers_rows() -> list[dict]:
    """Zurich has a peer group in both markets; Subject Co has none."""
    group = ("AIG", "Allianz", "AXA XL", "Chubb", "QBE")
    return [
        {
            "Carrier_Group": PEERED,
            "Carrier": PEERED,
            "Country": country,
            "Overall_Peer_Group": peer,
            "Peers": peer,
        }
        for country in COUNTRIES
        for peer in group
    ]


def build(path: Path):
    """Write the book to a SQLite file at ``path`` and return an engine on it."""
    import pandas as pd
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{path}")
    pd.DataFrame(rows()).to_sql("GPR", engine, index=False)
    pd.DataFrame(peers_rows()).to_sql("Peers", engine, index=False)
    return engine
