"""Deterministic seed database for Studio development.

The production GPR/Survey tables live in an external SQLite DB supplied via the
``DB_PATH`` / ``STUDIO_DB_PATH`` env var. When neither is set (local dev, CI, this
repo), ``ensure_seed_db`` builds a realistic, fully-deterministic GPR + Peers
database so the page computes REAL numbers through the same primitives the live app
uses. Schema matches ``core/registry/flows.yaml`` exactly.

Determinism: a fixed RNG seed → identical numbers every run, so screenshots and
tests are stable.
"""
from __future__ import annotations

import calendar
import random
from pathlib import Path
from typing import Dict, List

from sqlalchemy import create_engine

_SEED_PATH = Path(__file__).resolve().parent / "_seed" / "studio_seed.db"
_RNG_SEED = 20260619

CARRIERS = [
    "Zurich", "AIG", "Chubb", "Allianz", "AXA XL", "Tokio Marine",
    "Liberty Specialty", "QBE", "Sompo", "MS&AD", "Berkshire", "Swiss Re",
]
SUBJECT = "Zurich"  # the carrier most of the dev views centre on

COUNTRIES = ["Singapore", "Hong Kong", "Japan", "Australia"]
REGION_OF = {"Singapore": "Asia", "Hong Kong": "Asia", "Japan": "Asia", "Australia": "Pacific"}

# (industry, market-weight, zurich-writes?) — three industries are deliberately
# whitespace for the subject: market is material, Zurich writes nothing.
INDUSTRIES = [
    ("Manufacturing", 1.00, True),
    ("Financial Services", 0.92, True),
    ("Construction & Engineering", 0.74, True),
    ("Technology & Telecom", 0.66, True),
    ("Healthcare & Life Sciences", 0.55, True),
    ("Retail & Wholesale", 0.48, True),
    ("Transportation & Logistics", 0.42, True),
    ("Agriculture", 0.20, True),
    ("Hospitality & Leisure", 0.17, True),
    ("Public Administration", 0.14, True),
    ("Mining & Metals", 0.12, True),
    ("Education", 0.09, True),
    ("Renewable Energy", 0.60, False),    # whitespace
    ("Pharmaceuticals", 0.45, False),     # whitespace
    ("Aviation & Aerospace", 0.30, False),  # whitespace
]

# product_line -> (business_line, cover_line, weight)
PRODUCTS: Dict[str, List] = {
    "Property": [("Commercial Property", "Fire & Perils", 1.0), ("Commercial Property", "Business Interruption", 0.7)],
    "Casualty": [("General Liability", "Public Liability", 0.85), ("General Liability", "Employers Liability", 0.6)],
    "Financial Lines": [("D&O", "Professional Indemnity", 0.7), ("D&O", "Crime", 0.4)],
    "Marine": [("Cargo", "Hull", 0.55), ("Cargo", "Theft", 0.3)],
    "Cyber": [("Cyber", "Data Breach", 0.5)],
    "Energy": [("Energy", "Onshore", 0.45)],
}
SEGMENTS = ["Risk Management", "Corporate", "Commercial"]
YEARS = [2023, 2024, 2025]
# Per-carrier strength multiplier (subject is a strong-but-not-leading #6-ish).
_CARRIER_STRENGTH = {c: w for c, w in zip(CARRIERS, [0.85, 1.15, 1.05, 0.95, 0.8, 0.7, 0.6, 0.55, 0.5, 0.48, 0.65, 0.9])}
# Industries where the subject is growing fast (drives the >100% YoY rule demo).
_SUBJECT_HOT = {"Cyber": 1.9, "Financial Lines": 1.55}

# Deterministic intra-year seasonal curve (12 weights) — a gentle rising ramp with
# a mid-year lift, so MoM / QoQ / TTM have real, non-flat signal. Normalised at use
# so the 12 monthly rows always sum to the row's annual premium (yearly totals,
# YoY and every existing breakdown stay byte-identical to the annual seed).
_SEASON = [0.72, 0.78, 0.86, 0.92, 1.00, 1.08, 1.12, 1.06, 0.98, 1.04, 1.10, 1.18]


def _premium(rng, *, carrier, industry_w, product_w, year, hot=1.0) -> float:
    base = 9_000_000 * industry_w * product_w * _CARRIER_STRENGTH[carrier]
    growth = {2023: 0.82, 2024: 0.93, 2025: 1.0}[year] * (hot if year == 2025 else 1.0)
    noise = rng.uniform(0.7, 1.3)
    return round(base * growth * noise, 2)


def _monthly_split(annual: float) -> List[float]:
    """Split an annual premium into 12 deterministic monthly amounts summing to it."""
    weight_total = sum(_SEASON)
    return [round(annual * w / weight_total, 2) for w in _SEASON]


def build_seed(path: Path = _SEED_PATH) -> Path:
    """(Re)build the seed DB at ``path`` and return it."""
    import pandas as pd

    rng = random.Random(_RNG_SEED)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    rows: List[dict] = []
    for carrier in CARRIERS:
        for country in COUNTRIES:
            for industry, ind_w, zurich_writes in INDUSTRIES:
                if carrier == SUBJECT and not zurich_writes:
                    continue  # whitespace: subject writes nothing here
                for product, lines in PRODUCTS.items():
                    business, cover, prod_w = lines[0]
                    for year in YEARS:
                        hot = _SUBJECT_HOT.get(product, 1.0) if carrier == SUBJECT else 1.0
                        annual = _premium(
                            rng, carrier=carrier, industry_w=ind_w, product_w=prod_w, year=year, hot=hot
                        )
                        # Draw the descriptive fields once per group/year, then emit
                        # one row per calendar month carrying its split of the annual.
                        segment = rng.choice(SEGMENTS)
                        client = f"{carrier} client {rng.randint(1000, 9999)}"
                        for month, monthly in enumerate(_monthly_split(annual), start=1):
                            rows.append(
                                {
                                    "Region": REGION_OF[country],
                                    "Country": country,
                                    "Carrier_Group": carrier,
                                    "Product_Line": product,
                                    "Business_Line": business,
                                    "Cover_Line": cover,
                                    "Client_Segment": segment,
                                    "SIC_Major_Class": industry,
                                    "SIC_Minor_Class": industry + " — General",
                                    "CLIENT_NAME": client,
                                    "Premium": monthly,
                                    "Billing_Date": f"{year}-{month:02d}-15",
                                    "Year": year,
                                    "Month_Name": calendar.month_name[month],
                                }
                            )
    gpr = pd.DataFrame(rows)

    # Peers: subject's peer set = nearest-strength carriers (aggregate-only use).
    peer_rows = [
        {"Carrier_Group": SUBJECT, "Overall_Peer_Group": p}
        for p in ["AXA XL", "Allianz", "Chubb", "AIG"]
    ]
    for c in CARRIERS:  # a small generic mapping for the rest
        if c == SUBJECT:
            continue
        for p in rng.sample([x for x in CARRIERS if x != c], 4):
            peer_rows.append({"Carrier_Group": c, "Overall_Peer_Group": p})
    peers = pd.DataFrame(peer_rows)

    engine = create_engine(f"sqlite:///{path}")
    gpr.to_sql("GPR", engine, index=False, if_exists="replace")
    peers.to_sql("Peers", engine, index=False, if_exists="replace")
    engine.dispose()
    return path


def ensure_seed_db(path: Path = _SEED_PATH) -> str:
    """Return the seed DB path, building it once if absent."""
    if not path.exists():
        build_seed(path)
    return str(path)


if __name__ == "__main__":
    p = build_seed()
    print(f"seed db built: {p}")
