"""Single, validated data/SQL tool contract for Virtual Analyst.

Every execution path — the deterministic subgraph `*_execute_sql` nodes, the
analytical agent (Phase D), the pitch workflow, and (later) external MCP
clients — funnels through these functions. That gives one read-only-enforced
choke point and one typed error contract instead of three near-duplicate
execute bodies.

These are plain Python callables; `core/mcp/server.py` registers them on a
FastMCP server, and the agent binds them as LangChain tools. The bodies wrap
the existing layer (`GeneralFunctions`, `GetValidData`, `assert_read_only`,
`dry_run_explain`, `BaseSQLFixerNode`) — no logic is duplicated here.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz, process, utils
from sqlalchemy.sql import text

from core.agents.common import assert_read_only, dry_run_explain
from core.data.general import GeneralFunctions
from core.data.valid_values import GetValidData
from core.initialization import Initialization
from core.observability import latency_timer, log_event, sql_metadata
from core.schemas.mcp import ExecuteSQLResult
from logger import get_logger

logger = get_logger(__name__)

# Overflow threshold mirrors the historical per-node `len(...) > 40` check.
OVERFLOW_ROW_LIMIT = 40

# Flow -> observability route label used by the legacy execute nodes.
_ROUTE_BY_FLOW: Dict[str, str] = {
    "survey": "survey",
    "gpr": "premium",
    "gimmi": "gimmi",
}

# Flow -> the table-family slices each flow grounds against. The FIRST table is
# the flow's primary fact table (used as the default source for distinct values).
_SCHEMA_TABLES_BY_FLOW: Dict[str, List[str]] = {
    "survey": ["Carriers", "Peers"],
    "gpr": ["GPR", "Peers"],
    "gimmi": ["GIMMI"],
}

# Distinct-value cache for columns not covered by the precomputed valid_values
# dicts (e.g. SIC_Major_Class, SIC_Minor_Class, Cover_Line). Keyed by (flow, column).
_DISTINCT_CACHE: Dict[tuple, List[str]] = {}


def _route(flow: str) -> str:
    return _ROUTE_BY_FLOW.get(flow, flow)


def execute_sql(
    flow: str,
    sql: str,
    *,
    node: Optional[str] = None,
    validate: bool = True,
) -> ExecuteSQLResult:
    """Validate and execute a single read-only SELECT, returning a typed result.

    Consolidates the read-only guard, EXPLAIN dry-run, execution, overflow flag,
    and the start/validation/end/error observability events that each
    `*_execute_sql` node previously inlined. Never raises into the caller; all
    failures come back as `ExecuteSQLResult.error`.
    """
    sql = (sql or "").strip()
    route = _route(flow)
    node = node or f"{flow}_execute_sql"
    session = Initialization.Session()

    log_event(
        logger,
        "sql_execute_start",
        route=route,
        node=node,
        sql=sql_metadata(sql),
    )

    timing: Dict[str, float] = {}
    try:
        if validate:
            validation_error = assert_read_only(sql) or dry_run_explain(session, sql)
            if validation_error:
                log_event(
                    logger,
                    "sql_validation_error",
                    logging.WARNING,
                    route=route,
                    node=node,
                    sql=sql_metadata(sql),
                    error=validation_error,
                )
                return ExecuteSQLResult(error=validation_error)

        try:
            with latency_timer() as timing:
                result = session.execute(text(sql))
                rows = result.fetchall()
                columns = list(result.keys())

            query_rows = [dict(zip(columns, row)) for row in rows] if rows else []
            overflow = len(query_rows) > OVERFLOW_ROW_LIMIT

            log_event(
                logger,
                "sql_execute_end",
                route=route,
                node=node,
                sql=sql_metadata(
                    sql,
                    row_count=len(query_rows),
                    duration_ms=timing.get("duration_ms"),
                ),
                overflow=overflow,
            )
            return ExecuteSQLResult(
                rows=query_rows,
                columns=columns,
                overflow=overflow,
                row_count=len(query_rows),
            )

        except Exception as exc:  # noqa: BLE001 - surface message to the fixer loop
            log_event(
                logger,
                "sql_execute_error",
                logging.ERROR,
                route=route,
                node=node,
                sql=sql_metadata(sql, duration_ms=timing.get("duration_ms")),
                error=str(exc),
            )
            return ExecuteSQLResult(error=str(exc))

    finally:
        session.close()


def get_schema(flow: Optional[str] = None) -> Dict[str, Any]:
    """Full database schema, or just the table slices relevant to `flow`."""
    schema = GeneralFunctions.get_database_schema(engine=Initialization.engine)
    if flow is None:
        return schema
    tables = _SCHEMA_TABLES_BY_FLOW.get(flow, [])
    return {table: schema.get(table, []) for table in tables}


def get_valid_values(flow: str) -> Dict[str, Any]:
    """Valid column values for grounding filters, per flow."""
    if flow == "gpr":
        return GetValidData.valid_values_gpr
    if flow == "gimmi":
        return GetValidData.gimmi_valid_values
    return GetValidData.valid_values


def get_definitions(flow: str) -> Dict[str, str]:
    """Business definitions for columns, per flow."""
    if flow == "gpr":
        return GetValidData.definitions_gpr
    if flow == "gimmi":
        return GetValidData.gimmi_definitions
    return GetValidData.definitions


def match_entities(flow: str, user_query: str) -> Dict[str, Any]:
    """Fuzzy-match country/carrier mentions in `user_query` to valid values."""
    valid_values = get_valid_values(flow)
    valid_countries = valid_values.get("Country", [])
    carrier_key = "Carrier_Group" if flow == "gpr" else "Carrier"
    # The country->carrier dictionary is precomputed on GetValidData where available;
    # fall back to the flat carrier list so callers still get a best-effort match.
    country_carrier = getattr(
        GetValidData,
        "valid_country_carrier_gpr" if flow == "gpr" else "valid_country_carrier",
        {},
    ) or {}
    country, carriers = GetValidData.matching_values(
        user_query, valid_countries, country_carrier
    )
    return {"country": country, carrier_key: carriers}


def _table_for_column(flow: str, column: str) -> Optional[str]:
    """First table in `flow`'s schema that actually contains `column`.

    Also serves as the injection guard for `get_distinct_values`: only a column
    that genuinely exists in a known table is ever interpolated into SQL.
    """
    for table, cols in get_schema(flow).items():
        names = {c.get("Column Name") for c in cols}
        if column in names:
            return table
    return None


def get_distinct_values(flow: str, column: str) -> List[str]:
    """Distinct non-null values of `column` from `flow`'s table (cached).

    Backs columns that the precomputed `valid_values` dicts don't cover —
    e.g. SIC_Major_Class (industry), SIC_Minor_Class, Cover_Line. Runs through
    the validated `execute_sql` path; returns [] for an unknown column.
    """
    key = (flow, column)
    if key in _DISTINCT_CACHE:
        return _DISTINCT_CACHE[key]

    table = _table_for_column(flow, column)
    if table is None:
        _DISTINCT_CACHE[key] = []
        return []

    # `column` and `table` are verified schema identifiers (not user input);
    # double-quote them for SQLite and let assert_read_only/EXPLAIN still vet it.
    sql = (
        f'SELECT DISTINCT "{column}" AS value FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL ORDER BY "{column}"'
    )
    result = execute_sql(flow, sql, node="get_distinct_values")
    values = (
        [str(row["value"]) for row in result.rows]
        if result.ok and result.rows
        else []
    )
    _DISTINCT_CACHE[key] = values
    return values


def _candidate_values(flow: str, column: str) -> List[str]:
    valid_values = get_valid_values(flow)
    if column in valid_values and valid_values[column]:
        return [str(v) for v in valid_values[column]]
    return get_distinct_values(flow, column)


def match_column_values(
    flow: str,
    column: str,
    term: str,
    *,
    top_n: int = 10,
    score_cutoff: int = 60,
) -> List[str]:
    """Fuzzy-match a user term to the valid values of ANY column.

    Works for industry (`SIC_Major_Class`), `SIC_Minor_Class`, `Business_Line`,
    `Cover_Line`, `Product_Line`, `Client_Segment`, `Region`, survey `Sections`
    / `Attributes`, etc. Candidates come from the precomputed valid_values when
    available, otherwise from `get_distinct_values`. Returns the best matches in
    descending score order (empty if the column is unknown or nothing clears the
    cutoff).
    """
    candidates = _candidate_values(flow, column)
    if not candidates:
        return []
    matches = process.extract(
        term,
        candidates,
        scorer=fuzz.partial_ratio,
        processor=utils.default_process,
        limit=top_n,
        score_cutoff=score_cutoff,
    )
    return [match[0] for match in matches]


def fix_sql(
    flow: str,
    *,
    user_query: str,
    schema_tables: Any,
    peer_schema: Any,
    sql_query: str,
    error_message: Any,
    extra_rules: str = "",
) -> str:
    """Correct an invalid SQL query. Thin pass-through to `BaseSQLFixerNode`.

    Imported lazily so importing this module does not pull the agent/LLM layer.
    """
    from core.agents.common import BaseSQLFixerNode

    fixer = BaseSQLFixerNode(flow=flow, extra_rules=extra_rules)
    return fixer.fix(
        user_query=user_query,
        schema_tables=schema_tables,
        peer_schema=peer_schema,
        sql_query=sql_query,
        error_message=error_message,
        valid_values=get_valid_values(flow),
        definitions=get_definitions(flow),
    )
