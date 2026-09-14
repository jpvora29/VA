"""Builds the evaluation fixture warehouse: an in-memory SQLite database whose
tables and column names mirror the production schema declared in
`core/registry/flows.yaml`.

Mirroring matters. The primitives resolve columns through the flow spec, so a
fixture with convenient invented column names would exercise a different code
path than production and prove nothing. Everything here is derived from
`scenario.py`; this module adds no numbers of its own.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Sequence

from sqlalchemy import create_engine, text

from tests.evaluation import scenario
from tests.evaluation.scenario import PremiumCell, SurveyCell

GPR_COLUMNS = (
    "Region TEXT",
    "Country TEXT",
    "Carrier_Group TEXT",
    "Product_Line TEXT",
    "Business_Line TEXT",
    "Client_Segment TEXT",
    "SIC_Major_Class TEXT",
    "CLIENT_NAME TEXT",
    "Billing_Date TEXT",
    "Year INTEGER",
    "Month_Name TEXT",
    "Premium REAL",
)

PEERS_COLUMNS = (
    "Carrier_Group TEXT",
    "Overall_Peer_Group TEXT",
    "Country TEXT",
)

CARRIERS_COLUMNS = (
    "Region TEXT",
    "SurveyCountry TEXT",
    "Carrier TEXT",
    "SurveyPractice TEXT",
    "SurveySegment TEXT",
    "Section TEXT",
    "Attribute TEXT",
    "Survey_Year INTEGER",
    "ResponseId TEXT",
    "Score REAL",
    '"NPS Score" REAL',
)

REGION = "Asia"
SEGMENT = "Large Corporate"


def billing_date(year: int, quarter: int) -> str:
    """The representative billing date for a quarter, as the warehouse stores it."""
    month, _name = scenario.MONTH_OF_QUARTER[quarter]
    return f"{year}-{month:02d}-15"


def month_name(quarter: int) -> str:
    _month, name = scenario.MONTH_OF_QUARTER[quarter]
    return name


def gpr_row(cell: PremiumCell) -> dict:
    """One premium cell as a GPR row."""
    return {
        "Region": REGION,
        "Country": cell.country,
        "Carrier_Group": cell.carrier,
        "Product_Line": cell.product,
        "Business_Line": cell.product,
        "Client_Segment": SEGMENT,
        "SIC_Major_Class": cell.industry,
        "CLIENT_NAME": f"{cell.industry} Holdings",
        "Billing_Date": billing_date(cell.year, cell.quarter),
        "Year": cell.year,
        "Month_Name": month_name(cell.quarter),
        "Premium": cell.premium,
    }


def carriers_row(cell: SurveyCell) -> dict:
    """One survey response as a Carriers row."""
    return {
        "Region": REGION,
        "SurveyCountry": cell.country,
        "Carrier": cell.carrier,
        "SurveyPractice": cell.practice,
        "SurveySegment": SEGMENT,
        "Section": cell.section,
        "Attribute": cell.attribute,
        "Survey_Year": cell.year,
        "ResponseId": cell.response_id,
        "Score": cell.score,
        "NPS Score": cell.nps,
    }


def peers_rows() -> List[dict]:
    """The subject's peer group in the evaluated market."""
    return [
        {
            "Carrier_Group": scenario.CARRIER,
            "Overall_Peer_Group": peer,
            "Country": scenario.COUNTRY,
        }
        for peer in scenario.PEERS
    ]


def _create(conn: Any, table: str, columns: Sequence[str]) -> None:
    conn.execute(text(f'CREATE TABLE "{table}" ({", ".join(columns)})'))


def _insert(conn: Any, table: str, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    names = list(rows[0])
    targets = ", ".join(f'"{name}"' for name in names)
    binds = ", ".join(f":p{index}" for index, _ in enumerate(names))
    statement = text(f'INSERT INTO "{table}" ({targets}) VALUES ({binds})')
    conn.execute(
        statement,
        [{f"p{index}": row[name] for index, name in enumerate(names)} for row in rows],
    )


def build_engine(url: str = "sqlite:///:memory:") -> Any:
    """A SQLAlchemy engine holding the full evaluation warehouse.

    Use one engine per test that mutates nothing — the primitives only read.
    """
    engine = create_engine(url)
    with engine.begin() as conn:
        _create(conn, "GPR", GPR_COLUMNS)
        _create(conn, "Peers", PEERS_COLUMNS)
        _create(conn, "Carriers", CARRIERS_COLUMNS)
        _insert(conn, "GPR", (gpr_row(cell) for cell in scenario.all_cells()))
        _insert(conn, "Peers", peers_rows())
        _insert(conn, "Carriers", (carriers_row(cell) for cell in scenario.survey_cells()))
    return engine
