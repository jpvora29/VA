from __future__ import annotations

import logging
from typing import Any
from sqlalchemy import text
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection, Engine

from config.callbacks_config import (
    PITCH_COLUMN_MAP,
)
from config.db_config import engine
from logger import get_logger

logger = get_logger(__name__)

# --- Types ---
OptionList = list[dict[str, str]]
Row = Any  # SQLAlchemy row


def _available_pitch_tables() -> list[str]:
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        return [table for table in PITCH_COLUMN_MAP if table in table_names]
    except Exception:
        logger.exception(f" Failed to load pitch country options")
        return []


def _sort_pitch_values(values: set[str]) -> OptionList:
    def sort_key(value):
        try:
            return (0, int(value))
        except ValueError:
            return (1, value.lower())

    return [{"label": value, "value": value} for value in sorted(values, key=sort_key)]


def _clean_rows(rows: list[Row]) -> set[str]:
    """Extract non-null, non-empty string values from query rows."""
    return {str(row.value) for row in rows if row.value not in (None, "")}


# --- Single reusable query executor ---
def _fetch_distinct_values(
    conn: Connection,
    table_name: str,
    column: str,
    filters: dict[str, str] | None = None,
) -> set[str]:
    """
    Fetch DISTINCT non-null values for a column from a table,
    with optional equality filters (parameterized).
    """
    where_parts = [f'"{column}" IS NOT NULL']
    params: dict[str, str] = {}

    if filters:
        for key, value in filters.items():
            where_parts.append(f'LOWER("{key}") = LOWER(:{key})')
            params[key] = value

    query = text(
        f'SELECT DISTINCT "{column}" AS value '
        f'FROM "{table_name}" '
        f'WHERE {" AND ".join(where_parts)} '
        f'ORDER BY "{column}"'
    )

    rows = conn.execute(query, params).fetchall()
    return _clean_rows(rows)


# --- Table iteration helper ---
def _collect_across_tables(
    conn: Connection,
    tables: list[str],
    column_key: str,
    filters: dict[str, str] | None = None,
) -> set[str]:
    """Collect distinct values for a column key across all pitch tables."""
    values: set[str] = set()
    for table_name in tables:
        columns = PITCH_COLUMN_MAP[table_name]
        column = columns[column_key]
        values |= _fetch_distinct_values(conn, table_name, column, filters)
    return values


# ── PUBLIC FUNCTIONS  ───────────────────────────────────────────────────────────────────────────


def distinct_pitch_countries():
    values = set()
    try:
        with engine.connect() as conn:
            for table_name in _available_pitch_tables():
                columns = PITCH_COLUMN_MAP[table_name]
                logger.debug(columns)
                column = columns["country"]
                rows = conn.execute(
                    text(
                        f'SELECT DISTINCT "{column}" AS value FROM "{table_name}" WHERE "{column}" IS NOT NULL ORDER BY "{column}"'
                    )
                ).fetchall()
                values.update(
                    str(row.value) for row in rows if row.value not in (None, "")
                )

    except Exception as e:
        logger.exception(f"Unable to load pitch country options: {e}")

    return _sort_pitch_values(values)


def distinct_pitch_carriers(country):
    values = set()
    try:
        with engine.connect() as conn:
            for table_name in _available_pitch_tables():
                columns = PITCH_COLUMN_MAP[table_name]
                column = columns["carrier"]
                print(country)
                rows = conn.execute(
                    text(
                        f'SELECT DISTINCT "{column}" AS value FROM "{table_name}" WHERE "{column}" IS NOT NULL AND LOWER("{columns["country"]}") = LOWER(:country) '
                        f'ORDER BY "{column}"'
                    ),
                    {"country": country},
                ).fetchall()
                values.update(
                    str(row.value) for row in rows if row.value not in (None, "")
                )

    except Exception as e:
        logger.exception(f"Unable to load pitch carrier options: {e}")

    return _sort_pitch_values(values)


def distinct_pitch_years(country=None, carrier=None):
    values = set()
    try:
        with engine.connect() as conn:
            for table_name in _available_pitch_tables():
                columns = PITCH_COLUMN_MAP[table_name]
                where_parts = [f'"{columns["year"]}" IS NOT NULL']
                params = {"country": country, "carrier": carrier}
                if country:
                    where_parts.append(
                        f'LOWER("{columns["country"]}") = LOWER(:country)'
                    )
                if carrier:
                    where_parts.append(
                        f'LOWER("{columns["carrier"]}") = LOWER(:carrier)'
                    )

                rows = conn.execute(
                    text(
                        f'SELECT DISTINCT "{columns["year"]}" AS value '
                        f' FROM "{table_name}" '
                        f' WHERE {" AND ".join(where_parts)}'
                        f' ORDER BY "{columns["year"]}"'
                    ),
                    params,
                ).fetchall()
                values.update(
                    str(row.value) for row in rows if row.value not in (None, "")
                )

    except Exception as e:
        logger.exception(f"Unable to load pitch year options: {e}")

    return _sort_pitch_values(values)


def default_option_value(
    options: list[dict[str, str]],
    current_value: str | None = None,
    preferred_value: str | None = None,
) -> str | int | None:

    values: set[str] = {option["value"] for option in options}

    if preferred_value:
        for value in values:
            if str(value).strip().lower() == str(preferred_value).strip().lower():
                return value

    if current_value in values:
        return current_value

    return options[0]["value"] if options else None


def latest_option_value(options: list[dict[str, str]]) -> int | None:

    def year_key(option) -> str | int:
        value = option["value"]
        try:
            return (1, int(value))
        except (TypeError, ValueError):
            return (0, str(value))

    return max(options, key=year_key)["value"] if options else None


def pitch_cache(cache: dict[str, Any]) -> dict[str, Any]:

    cache = dict(cache or {})
    cache.setdefault("countries", [])
    cache.setdefault("carriers", {})
    cache.setdefault("years", {})
    cache.setdefault("selection", {})
    return cache


def pitch_cache_key(*parts: list[str]):
    return "||".join(str(part or "") for part in parts)


def has_pitch_filters(country: str | None, carrier: str | None, year: int | None):
    return bool(country and carrier and year)
