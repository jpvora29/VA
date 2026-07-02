"""Shared configuration and the single DB engine for the authoring app."""
from __future__ import annotations

from pathlib import Path

from studio.data import get_engine

# Static assets live next to the repo root (``authoring_app.py``), two levels up.
ASSETS = str(Path(__file__).resolve().parents[2] / "assets")

# The default breakdowns and the "treat as unset" sentinels for form values.
BREAKDOWNS = ["Product_Line", "SIC_Major_Class"]
BLANK = (None, "", [], "all", "All")

# Sensible defaults so the Setup form is pre-filled and a deck is one click away.
DEFAULT_FILTERS = {"carrier": "Zurich", "country": ["Singapore"], "year": 2025}

# One engine, opened once and shared by every helper (cheap: runs no query).
engine = get_engine()
