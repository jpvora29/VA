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
import re
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz, process, utils
from sqlalchemy.sql import text

from core.agents.common import assert_read_only, dry_run_explain
from core.data.general import GeneralFunctions
from core.data.valid_values import GetValidData
from core.initialization import Initialization
from core.registry import get_flow_registry
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
# Sourced from the central flow registry (`core/registry/flows.yaml`) so adding a
# dataset means one registry entry, not editing this map. Equals the former
# hardcoded {survey: [Carriers, Peers], gpr: [GPR, Peers], gimmi: [GIMMI]}.
_SCHEMA_TABLES_BY_FLOW: Dict[str, List[str]] = {
    name: list(get_flow_registry().get(name).allowed_tables)
    for name in get_flow_registry().flows()
}

# Distinct-value cache for columns not covered by the precomputed valid_values
# dicts (e.g. SIC_Major_Class, SIC_Minor_Class, Cover_Line). Keyed by (flow, column).
_DISTINCT_CACHE: Dict[tuple, List[str]] = {}


def _route(flow: str) -> str:
    return _ROUTE_BY_FLOW.get(flow, flow)


# Matches the `Carrier_Name` identifier (bare, bracketed, or quoted) but only
# OUTSIDE single-quoted string literals — handled by splitting on quotes below.
_CARRIER_NAME_IDENT = re.compile(r"(?i)\bCarrier_Name\b")


def _enforce_gpr_carrier_group(sql: str, *, node: Optional[str] = None) -> str:
    """Deterministically rewrite `Carrier_Name` -> `Carrier_Group` in GPR SQL.

    "Always use Carrier_Group, never Carrier_Name" is a hard GPR business rule
    carried in every planner/SQL skill and the fixer rules, yet the LLM still
    emits `Carrier_Name` on some turns — silently returning wrong rows when the
    column exists. Prose can't guarantee a never-do constraint, so we enforce it
    at the single shared execute chokepoint instead. The rewrite only touches the
    column identifier outside string literals, so values like '... Carrier_Name
    ...' inside quotes are left untouched.
    """
    if "carrier_name" not in sql.lower():
        return sql
    # Replace only in the segments OUTSIDE single-quoted literals (even indexes).
    segments = sql.split("'")
    changed = False
    for i in range(0, len(segments), 2):
        new_segment = _CARRIER_NAME_IDENT.sub("Carrier_Group", segments[i])
        if new_segment != segments[i]:
            changed = True
            segments[i] = new_segment
    if changed:
        log_event(
            logger,
            "gpr_carrier_name_rewritten",
            route="premium",
            node=node or "gpr_execute_sql",
        )
    return "'".join(segments)


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
    if flow == "gpr":
        sql = _enforce_gpr_carrier_group(sql, node=node)
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
    """Valid column values for grounding filters, per flow.

    Routed through the flow registry. Unknown flows fall back to survey — the
    exact behavior of the former gpr/gimmi/else branch.
    """
    registry = get_flow_registry()
    spec = registry.get(flow) or registry.get("survey")
    return spec.valid_values()


def get_definitions(flow: str) -> Dict[str, str]:
    """Business definitions for columns, per flow (via the flow registry)."""
    registry = get_flow_registry()
    spec = registry.get(flow) or registry.get("survey")
    return spec.definitions()


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


# Generic corporate/legal/insurance tokens that carry no identifying signal. A
# plain `partial_ratio` lets these dominate alignment, so "Zurich Insurance"
# wrongly matches "KB Insurance" and "AIG Insurance" matches "MUANG THAI
# INSURANCE". Stripping them before scoring makes the distinctive token ("zurich",
# "aig") decide the match. Kept broad but safe — these never disambiguate a value.
_GENERIC_TOKENS = frozenset(
    {
        "insurance", "insurer", "insurers", "assurance", "reinsurance",
        "group", "holdings", "holding", "company", "companies", "co",
        "ltd", "limited", "corporation", "corp", "incorporated", "inc",
        "plc", "pcl", "ag", "sa", "nv", "se", "general", "public",
        "and", "of", "the", "&",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def _clean_for_match(value: str) -> str:
    """Lowercase, drop punctuation, and remove generic corporate tokens.

    Falls back to the punctuation-stripped string if every token is generic
    (e.g. a value literally named "Group"), so it never returns empty.
    """
    lowered = _NON_ALNUM.sub(" ", value.lower())
    tokens = [t for t in lowered.split() if t and t not in _GENERIC_TOKENS]
    return " ".join(tokens) if tokens else lowered.strip()


# A salient token is "carried" by the other side when some token there is a near
# string match. Below this, the token is genuinely absent — a discriminating
# difference, not noise.
_TOKEN_COVERAGE_CUTOFF = 85


def _token_absent(token: str, ref_tokens: List[str]) -> bool:
    """True when no token in `ref_tokens` is a near match for `token`."""
    return all(fuzz.ratio(token, ref) < _TOKEN_COVERAGE_CUTOFF for ref in ref_tokens)


def _mutually_distinct(term_tokens: List[str], candidate_tokens: List[str]) -> bool:
    """True when each side has a salient token the other lacks.

    This is the discriminating-token guard: a high `token_set_ratio` / `WRatio`
    can clear the cutoff on a *shared* token alone ("accident travel" vs
    "accident health" both keep "accident"), masking that "travel" and "health"
    are different. We reject only when the mismatch is mutual — the term has a
    token absent from the candidate AND the candidate has one absent from the
    term — so a user's shorter subset ("Swiss" -> "SWISS RE") still resolves.
    """
    term_has_extra = any(_token_absent(t, candidate_tokens) for t in term_tokens)
    candidate_has_extra = any(_token_absent(c, term_tokens) for c in candidate_tokens)
    return term_has_extra and candidate_has_extra


def match_column_values(
    flow: str,
    column: str,
    term: str,
    *,
    top_n: int = 10,
    score_cutoff: int = 80,
) -> List[str]:
    """Fuzzy-match a user term to the valid values of ANY column.

    Works for carriers (`Carrier_Group` / `Carrier`), industry
    (`SIC_Major_Class`), `Product_Line`, `Business_Line`, `Cover_Line`,
    `Client_Segment`, `Region`, survey `Sections` / `Attributes`, etc.

    Resolution order, most-specific first:
      0. Value-synonym expansion -> the term is rewritten to its canonical value
         when the registry declares it (e.g. "UK" -> "United Kingdom"), so the
         acronym cases string-distance can't bridge resolve deterministically.
      1. Exact case-insensitive match -> returned alone (no fuzzy noise).
      2. Composite fuzzy score over *generic-token-stripped* strings:
         `max(token_set_ratio, WRatio)`. token_set handles word reordering and
         common-word collisions (the failure mode of plain partial_ratio);
         WRatio rescues abbreviations/typos. Plain `ratio` breaks ties so the
         tightest full match (e.g. "SWISS RE" for "Swiss Reinsurance") ranks
         above looser ones ("SWISS LIFE"). A discriminating-token guard then
         drops candidates that clear the cutoff only on a shared token while
         differing on a salient one ("Accident & Travel" must NOT match the
         sibling "Accident & Health").

    Returns the best matches in descending score order, deduplicated, empty when
    the column is unknown or nothing clears the cutoff.
    """
    candidates = _candidate_values(flow, column)
    if not candidates:
        return []

    term_norm = (term or "").strip()
    if not term_norm:
        return []

    # 0) Expand a declared value-synonym/acronym to its canonical value, then let
    #    the exact + fuzzy passes re-match it against the real stored values.
    spec = get_flow_registry().get(flow)
    canonical = spec.canonical_value(column, term_norm) if spec else None
    if canonical:
        term_norm = canonical

    # 1) Exact case-insensitive hit wins outright.
    for candidate in candidates:
        if candidate.lower() == term_norm.lower():
            return [candidate]

    cleaned_term = _clean_for_match(term_norm)
    if not cleaned_term:
        return []
    term_tokens = cleaned_term.split()

    scored: List[tuple[str, float, float]] = []
    for candidate in candidates:
        cleaned_candidate = _clean_for_match(candidate)
        score = max(
            fuzz.token_set_ratio(cleaned_term, cleaned_candidate),
            fuzz.WRatio(cleaned_term, cleaned_candidate),
        )
        if score < score_cutoff:
            continue
        if _mutually_distinct(term_tokens, cleaned_candidate.split()):
            continue
        tiebreak = fuzz.ratio(cleaned_term, cleaned_candidate)
        scored.append((candidate, score, tiebreak))

    scored.sort(key=lambda item: (item[1], item[2]), reverse=True)

    result: List[str] = []
    for candidate, _score, _tb in scored:
        if candidate not in result:
            result.append(candidate)
        if len(result) >= top_n:
            break
    return result


# String-literal filter shapes an LLM emits: bare/quoted/bracketed identifiers,
# optionally wrapped in UPPER()/LOWER(), compared via =, IN (...), or LIKE.
_IDENT = r"(?:UPPER|LOWER)?\(?\s*[\"\[]?(\w+)[\"\]]?\s*\)?"
_EQ_FILTER = re.compile(rf"{_IDENT}\s*=\s*'([^']+)'", re.IGNORECASE)
_LIKE_FILTER = re.compile(rf"{_IDENT}\s+LIKE\s+'([^']+)'", re.IGNORECASE)
_IN_FILTER = re.compile(rf"{_IDENT}\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
_IN_ITEM = re.compile(r"'([^']*)'")


_DATE_LITERAL = re.compile(r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?$")


def _is_numeric_literal(value: str) -> bool:
    """Numbers and dates are not name-like filters — absence of rows for a
    year/date is genuine absence, never a spelling problem."""
    if _DATE_LITERAL.match(value):
        return True
    try:
        float(value)
        return True
    except ValueError:
        return False


def audit_sql_filters(flow: str, sql: str) -> List[Dict[str, Any]]:
    """Find string-literal filters in `sql` whose value doesn't exist in its column.

    The zero-row guard: a SELECT that *succeeds* with 0 rows is only evidence of
    "no data" when its filter values are real. A query like
    ``WHERE Country = 'UK'`` succeeds with 0 rows because the stored value is
    'United Kingdom' — and downstream prose then asserts a false negative.

    For each ``col = 'val'`` / ``col IN (...)`` / ``col LIKE '...'`` filter whose
    column has known valid values, this checks the literal against them
    (case-insensitive; LIKE checks wildcard-stripped containment) and returns one
    ``{"column", "value", "suggestions"}`` entry per miss, with up to 5 fuzzy
    suggestions. Empty list == every checkable filter value is real. Columns with
    no known value list (numerics, dates, unknown columns) are skipped — this
    audit can flag only what it can verify.
    """
    suspects: List[Dict[str, Any]] = []
    seen: set = set()

    def _check(column: str, value: str, *, like: bool = False) -> None:
        value = (value or "").strip()
        if not value or _is_numeric_literal(value):
            return
        key = (column.lower(), value.lower(), like)
        if key in seen:
            return
        seen.add(key)
        candidates = _candidate_values(flow, column)
        # Unverifiable (no value list) or unbounded (date/id-like) columns are
        # skipped — this audit can flag only what it can reliably verify.
        if not candidates or len(candidates) > 2000:
            return
        if like:
            fragment = value.replace("%", "").replace("_", " ").strip().lower()
            if not fragment:
                return
            if any(fragment in c.lower() for c in candidates):
                return
            term = fragment
        else:
            if any(c.lower() == value.lower() for c in candidates):
                return
            term = value
        suspects.append(
            {
                "column": column,
                "value": value,
                "suggestions": match_column_values(
                    flow, column, term, top_n=5, score_cutoff=60
                ),
            }
        )

    for column, value in _EQ_FILTER.findall(sql):
        _check(column, value)
    for column, value in _LIKE_FILTER.findall(sql):
        _check(column, value, like=True)
    for column, items in _IN_FILTER.findall(sql):
        for value in _IN_ITEM.findall(items):
            _check(column, value)
    return suspects


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
