"""Shared building blocks for the analyst sub-agents.

Holds the read-only LangChain tools, the 3-attempt SQL auto-repair, the
domain-rule loader (same source the deterministic rails use), and the bounded
ReAct ``run_solver`` that both the peer and generic solvers drive. Keeping these
here means the solver nodes differ only in their tool allowlist, prompt focus,
and step budget — not in their machinery.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Sequence

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from core.agents.analyst.middleware import build_solver_middleware
from core.context.bundle import schema_outline
from core.context.engine import engine_enabled
from core.initialization import Initialization
from core.agents.analyst.analytics_tool import build_compute_tool
from core.agents.common.analytics_tools import (
    analytics_tools_enabled,
    compute_first_directive,
)
from core.agents.common.peer_privacy import PeerRedactor, redactor_for
from core.agents.common.peers import custom_peer_directive, pinned_peers
from core.analysis import get_lens_library
from core.mcp.tools import (
    audit_sql_filters,
    execute_sql,
    fix_sql,
    get_distinct_values,
    get_schema,
    get_valid_values,
)
from core.observability import log_event
from core.rules.gpr import GPRRules
from core.rules.survey import SurveyRules
from core.schemas.analyst_subgraph import Evidence, SchemaSlice
from core.skills.loader import get_skill_loader
from logger import get_logger

logger = get_logger(__name__)

# Rows returned to the model per tool call (keeps context bounded); the full
# rows are still captured as evidence for the UI table.
_TOOL_ROW_PREVIEW = 50

# How many times run_sql auto-repairs + re-runs a failing query before giving up.
# Mirrors the deterministic subgraphs' 3-attempt SQL-fixer loop.
_SQL_MAX_ATTEMPTS = 3

# Per-flow nudges handed to the SQL fixer, matching the deterministic nodes.
_FIXER_EXTRA_RULES = {
    "gpr": "- Always use the `Carrier_Group` column instead of `Carrier_Name`.",
}

# Legacy rule fallbacks per flow: (planner_rules, query_rules) — the exact
# bundles the deterministic subgraph nodes fall back to when no skill matches.
_LEGACY_RULES = {
    "gpr": (GPRRules.planner_rules, GPRRules.query_rules),
    "survey": (SurveyRules.planner_rules, SurveyRules.query_rules),
}


def autofix_sql(flow: str, question: str, sql: str, error: str) -> str | None:
    """Best-effort repair of a failing query via the shared LLM SQL fixer.

    Returns the corrected SQL, or None if the fixer itself errors (in which case
    the caller simply re-runs the previous SQL — covering transient DB errors).
    """
    try:
        schema_tables = get_schema(flow)  # e.g. {"GPR": [...], "Peers": [...]}
        return fix_sql(
            flow,
            user_query=question,
            schema_tables=schema_tables,
            peer_schema=schema_tables.get("Peers", []),
            sql_query=sql,
            error_message=error,
            extra_rules=_FIXER_EXTRA_RULES.get(flow, ""),
        )
    except Exception as exc:  # noqa: BLE001 - never let a fix attempt crash the turn
        log_event(
            logger,
            "run_sql_autofix_error",
            logging.ERROR,
            node="analyst_solver",
            flow=flow,
            error=str(exc),
        )
        return None


def build_tools(
    evidence: List[Evidence],
    question: str,
    lens: str,
    *,
    peer_only: bool = False,
    guard_zero_rows: bool = False,
    flow: str = "gpr",
    peers: Sequence[str] = (),
    redactor: PeerRedactor | None = None,
):
    """Read-only LangChain tools for a solver; `evidence` collects executed rows.

    `redactor` enforces peer confidentiality at the evidence boundary: the tool's
    REPLY to the model keeps real peer names (it needs them to write the next
    query), while the rows recorded in `evidence` -- the only thing the writer,
    the shown table and the charts ever see -- name no individual peer. Omitting
    it records rows unredacted, which is only ever right in a unit test.

    `peer_only` trims the toolset to what the peer-comparison path actually needs
    (compute_metric + run_sql + resolve_value + consult_skill), so that
    specialist's context isn't cluttered with list/show-values tools it never
    calls. `compute_metric` is the one it should reach for first: the peer-average
    definition is the one this path most often gets wrong by hand.

    `flow` + `peers` scope the `compute_metric` tool: `peers` is the session's
    pinned custom peer set, so a computed peer average benchmarks exactly the group
    the prompt directive pins for hand-written SQL.

    `guard_zero_rows` arms the zero-row guard (a 0-row result whose filter value
    looks wrong is returned as a "re-run with an exact value" warning instead of
    "no data"). It fires AT MOST ONCE per solver — a second 0-row is taken at
    face value — so a bad filter can't drive the solver into a re-run loop.
    """
    from langchain_core.tools import tool

    # One-shot latch for the zero-row guard (see `guard_zero_rows`). Mutable so
    # the `run_sql` closure can flip it after the single re-check it's allowed.
    guard = {"tripped": False}

    @tool
    def run_sql(flow: str, sql: str) -> str:
        """Execute a single read-only SELECT and return JSON rows.

        `flow` is one of "survey", "gpr", "gimmi" (which table family to query).
        Returns a JSON object {row_count, rows}. Write/DDL statements are
        rejected. If the query fails, it is automatically repaired and re-run up
        to 3 times before any error is returned, so an "ERROR:" reply means the
        query could not be made to run — NOT that the data is missing. A
        successful reply with row_count 0 is the only signal of genuinely no data.
        """
        attempt_sql = (sql or "").strip()
        last_error = ""
        for attempt in range(1, _SQL_MAX_ATTEMPTS + 1):
            result = execute_sql(flow, attempt_sql)
            if not result.error:
                # Zero-row guard: 0 rows is only evidence of "no data" when the
                # filter values are real. WHERE Country='UK' succeeds with 0 rows
                # because the stored value is 'United Kingdom' — without this
                # check the turn confidently reports a false "no premium in UK".
                #
                # Gated + one-shot: it arms only when this turn left a user entity
                # unresolved (`guard_zero_rows`), and trips at most once. After the
                # first re-check the next 0-row is accepted as genuine "no data",
                # so a stubborn-but-valid empty result never loops the solver.
                if result.row_count == 0 and guard_zero_rows and not guard["tripped"]:
                    suspects = audit_sql_filters(flow, attempt_sql)
                    if suspects:
                        guard["tripped"] = True
                        log_event(
                            logger,
                            "run_sql_zero_row_suspect_filter",
                            logging.WARNING,
                            node="analyst_solver",
                            flow=flow,
                            suspects=suspects,
                        )
                        # Not appended as evidence: an empty result from a wrong
                        # filter value must never reach the insight-writer as a
                        # "no data" fact.
                        return json.dumps(
                            {
                                "row_count": 0,
                                "rows": [],
                                "warning": (
                                    "0 rows, but these filter values do NOT exist "
                                    "in their columns — this is a WRONG FILTER "
                                    "VALUE, not missing data. Do NOT conclude "
                                    "'no data'. Re-run with an exact valid value "
                                    "(use the suggestions, or resolve_value / "
                                    "list_values)."
                                ),
                                "suspect_filters": suspects,
                            },
                            default=str,
                        )
                # Confidentiality boundary: `evidence` feeds the writer, the
                # shown table and the charts, so it is redacted here. The reply
                # below is not -- the solver needs the real names to build the
                # next query's IN (...) list.
                evidence.append(
                    {
                        "flow": flow,
                        "sql": attempt_sql,
                        "rows": redactor.rows(result.rows) if redactor else result.rows,
                        "lens": lens,
                    }
                )
                return json.dumps(
                    {
                        "row_count": result.row_count,
                        "rows": result.rows[:_TOOL_ROW_PREVIEW],
                    },
                    default=str,
                )
            last_error = result.error
            log_event(
                logger,
                "run_sql_retry",
                logging.WARNING,
                node="analyst_solver",
                flow=flow,
                attempt=attempt,
                error=last_error,
            )
            if attempt < _SQL_MAX_ATTEMPTS:
                attempt_sql = autofix_sql(flow, question, attempt_sql, last_error) or attempt_sql
        return (
            f"ERROR (failed after {_SQL_MAX_ATTEMPTS} auto-repaired attempts): "
            f"{last_error}. This is a SQL-construction problem, not missing data — "
            f"rewrite the query with a different shape and call run_sql again. Do "
            f"NOT conclude that no data exists from this error."
        )

    @tool
    def resolve_value(flow: str, column: str, term: str) -> str:
        """Match a loose term to the exact valid values of a column.

        Use BEFORE filtering on dimensions like SIC_Major_Class (industry),
        SIC_Minor_Class, Product_Line, Business_Line, Cover_Line, Client_Segment,
        Region, or survey Sections / Attributes. Returns a JSON list of matches.

        Resolution is hybrid (decision #4): deterministic fuzzy first; for a
        registry `resolver: semantic` column (industry/SIC, product/cover/business
        line, segment, attributes) a fuzzy miss escalates to an LLM resolver that
        maps the *concept* to real values ("manufacturing" -> the SIC classes) —
        only when CONTEXT_ENGINE_SEMANTIC is on. Default off -> pure fuzzy.
        """
        from core.context.retriever import build_resolver  # lazy

        return json.dumps(build_resolver(flow).match(column, term), default=str)

    @tool
    def consult_skill(name: str) -> str:
        """Load the full rules of a skill listed in 'ADDITIONAL RULES AVAILABLE ON
        DEMAND'. Pass the exact skill name. Returns the rule text, or a not-found
        note if the name is unknown."""
        body = get_skill_loader().body(name)
        log_event(
            logger,
            "consult_skill",
            node="analyst_solver",
            lens=lens,
            skill=name,
            found=bool(body),
        )
        if not body:
            return f"No skill named {name!r}. Use an exact name from the on-demand list."
        return body

    # The deterministic library, offered alongside run_sql (same flag as the rails):
    # for a covered metric the solver asks for the calculation by name instead of
    # writing its SQL. Peer solvers get it too — the peer-average definition is the
    # one this most often gets wrong by hand.
    computed = []
    if analytics_tools_enabled():
        # `peers` carries a pinned custom peer set, so a computed peer average
        # benchmarks the same group the prompt directive pins for run_sql.
        computed = [
            build_compute_tool(
                evidence, lens, flow=flow, peers=peers, redactor=redactor
            )
        ]

    if peer_only:
        return [run_sql, *computed, resolve_value, consult_skill]

    @tool
    def list_values(flow: str, column: str) -> str:
        """List the distinct valid values of a column (e.g. all industries)."""
        return json.dumps(get_distinct_values(flow, column), default=str)

    @tool
    def show_valid_values(flow: str) -> str:
        """Return the precomputed valid column values for a flow."""
        return json.dumps(get_valid_values(flow), default=str)

    return [run_sql, *computed, resolve_value, consult_skill, list_values, show_valid_values]


def domain_rules(route: str, primary_flow: str, trigger_text: str) -> str:
    """Domain planning + SQL-construction rules, from the SAME source the rails use.

    Uses the skill loader (scopes "planner" + "sql"), falling back to the legacy
    `core.rules.*` bundles when no skill matches — identical to the subgraph
    nodes. For a "both" route we load both flows. `trigger_text` is the question
    plus the sub-question(s), so a skill triggered by any step is included.
    """
    loader = get_skill_loader()
    flows = ["gpr", "survey"] if route == "both" else [primary_flow]
    blocks: List[str] = []
    for flow in flows:
        if flow not in _LEGACY_RULES:  # gimmi handles its own rules elsewhere
            continue
        legacy_planner, legacy_sql = _LEGACY_RULES[flow]
        planner_rules = loader.planner(flow, trigger_text) or legacy_planner
        sql_rules = loader.sql(flow, trigger_text) or legacy_sql
        blocks.append(
            f"### {flow.upper()} — planning rules\n{planner_rules}\n\n"
            f"### {flow.upper()} — SQL construction rules\n{sql_rules}"
        )
    return "\n\n".join(blocks)


def skill_catalog(route: str, primary_flow: str, trigger_text: str) -> str:
    """Menu of skills that APPLY to this flow but whose triggers did NOT fire.

    The statically-injected `domain_rules` only carries skills a trigger matched.
    This lists the rest by name + description so the solver can pull any of them
    on demand via the `consult_skill` tool — closing trigger gaps without bloating
    the prompt with every body up front (progressive disclosure). Returns "" when
    nothing extra is available.
    """
    loader = get_skill_loader()
    flows = ["gpr", "survey"] if route == "both" else [primary_flow]
    scopes = ("planner", "sql")
    already: set[str] = set()
    available: dict[str, str] = {}
    for flow in flows:
        for scope in scopes:
            already.update(s.name for s in loader.matching(flow, scope, trigger_text))
            for s in loader.applicable(flow, scope):
                available.setdefault(s.name, s.description)
    menu = {n: d for n, d in available.items() if n not in already}
    if not menu:
        return ""
    lines = "\n".join(f"- {name}: {desc}" for name, desc in sorted(menu.items()))
    return (
        "[ADDITIONAL RULES AVAILABLE ON DEMAND — these are NOT loaded above. If "
        "one looks relevant to the sub-question, call consult_skill(name) to read "
        "its full rules BEFORE writing the query.]\n" + lines
    )


_CONFIDENTIALITY = """[CONFIDENTIALITY — non-negotiable]
- Peers are ALWAYS aggregated. NEVER expose an individual peer/carrier name in
  any output. Refer to peers only in aggregate ("peer average", "the peer set",
  "vs. peers") even if a tool returned individual names. Marsh's GPR book is the
  market proxy (no carrier filter); it is fine to name Marsh."""


def _solver_prompt(
    *,
    role: str,
    question: str,
    sub_question: str,
    lens: str,
    flow: str,
    route: str,
    schema_slice: SchemaSlice,
    prior_digest: str,
    custom_peers: Dict | None = None,
    custom_peers_active: bool = False,
) -> str:
    library = get_lens_library()
    lens_body = library.body(lens) or "(no specific lens — answer the sub-question directly)"
    trigger_text = f"{question} {sub_question}"
    rules = domain_rules(route, flow, trigger_text)
    catalog = skill_catalog(route, flow, trigger_text)

    # ContextEngine solver view (step 5): the grounded `schema_slice` above is the
    # primary schema signal; the FULL per-column metadata dump that historically
    # followed it was redundant and the single biggest line in this prompt. When
    # the engine is on, replace it with the compact name-only outline (columns
    # the slice didn't surface stay discoverable, without the metadata bulk).
    # Default off -> the legacy full dump, byte-identical.
    use_outline = engine_enabled()

    def _schema_repr(target_flow: str) -> str:
        raw = get_schema(target_flow)
        return json.dumps(schema_outline(raw) if use_outline else raw, default=str)

    schema = _schema_repr(flow)

    # For a "both" route the perception lens may need the survey tables too, so
    # surface that schema as a secondary source (the GPR/premium flow stays primary).
    secondary_block = ""
    if route == "both" and flow != "survey":
        secondary_block = (
            '\n[SECONDARY SCHEMA for flow="survey" — query this flow only for a '
            "perception/score sub-question]\n"
            f"{_schema_repr('survey')}\n"
        )

    # The named calculations, rendered where the solver picks its approach.
    # Empty when the library is off, which restores the prompt's pure-SQL form.
    directive = compute_first_directive(flow, route)
    compute_block = f"{directive}\n\n" if directive else ""

    prior_block = (
        f"\n[RESULTS FROM EARLIER STEPS — build on these]\n{prior_digest}\n"
        if prior_digest
        else ""
    )

    # Session-pinned custom peers (from the UI) override the Peers-table resolution.
    peer_override = custom_peer_directive(
        custom_peers, flow, active=custom_peers_active
    )
    custom_peers_block = f"\n{peer_override}\n" if peer_override else ""

    return f"""{role}

You do NOT write the final answer. Your ONLY job is to gather the evidence that
answers the one sub-question below by calling tools, then stop. Keep your final
message to a one-line note of what you found — the insight-writer turns the
gathered rows into prose later.

[SUB-QUESTION — answer only this]
{sub_question}

{compute_block}[LENS TO APPLY — follow this shape and interpretation. Where a named
calculation above covers a step, call it; the lens's SQL shape is the
fallback for the parts no calculation covers.]
{lens_body}

[PRIMARY FLOW] {flow}  (route="{route}"). Query this flow. The GPR
table IS Marsh's book of business (the market proxy).

[GROUNDED SCHEMA SLICE — the schema-identifier already resolved this for you]
{schema_slice.as_prompt()}

[SCHEMA for flow="{flow}" — columns available beyond the grounded slice]
{schema}
{secondary_block}
[DOMAIN RULES — the same business + SQL-construction rules the deterministic
path uses: Carrier_Group handling, peer averages via the Peers table,
Share-of-Wallet / appetite math, Marsh premium, rolling-12M, ranking, etc.
These describe how to BUILD such a query by hand. When a named calculation
covers the step, it already encodes these rules — call it instead.]
{rules}

{catalog}
{custom_peers_block}{prior_block}
[RULES]
- Get every number from a tool; never invent one you did not retrieve.
- Reach for compute_metric FIRST: if a calculation in [CALCULATIONS AVAILABLE
  BY NAME] answers the sub-question, call it rather than writing the query
  yourself. Fall back to run_sql only for what it does not cover.
- Prefer the pre-resolved filter values above; only call resolve_value for a
  dimension value not already resolved for you.
- run_sql auto-repairs and re-runs a failing query up to 3 times on its own; if
  it still returns an ERROR, the SQL was wrong — try a DIFFERENT query shape,
  never give up after one failure.
- "No data" is ONLY valid when a tool SUCCEEDS with row_count 0. Never report
  missing data on the basis of an ERROR. An empty compute_metric result usually
  means the filters missed, not that the data is absent — check them, or fall
  back to run_sql, before concluding anything.
- Stay tightly focused on the sub-question; do not wander into other analyses.

{_CONFIDENTIALITY}"""


def stamp_redactions(
    evidence: List[Evidence], redactor: PeerRedactor
) -> List[Evidence]:
    """Record on each evidence item which peer names were hidden from it.

    Carried forward so the writer's prose can be scrubbed against exactly the
    names this turn touched, rather than against a global list of every carrier
    in the market. Returns the same list (the items are mutated in place).
    """
    hidden = redactor.redacted
    if not hidden:
        return evidence
    for item in evidence:
        item["redacted_peers"] = hidden
    return evidence


def run_solver(
    *,
    model,
    role: str,
    question: str,
    sub_question: str,
    lens: str,
    flow: str,
    route: str,
    schema_slice: SchemaSlice,
    recursion_limit: int,
    peer_only: bool = False,
    prior_digest: str = "",
    custom_peers: Dict | None = None,
    custom_peers_active: bool = False,
) -> List[Evidence]:
    """Run one bounded ReAct solver and return the evidence it gathered.

    Each call uses its OWN local evidence list so parallel solver nodes never
    share mutable state — the caller merges the returned lists via the graph's
    add-reducer. The solver's prose output is intentionally discarded; only the
    executed rows matter.
    """
    evidence: List[Evidence] = []
    # Who this turn may name: the carriers the schema-identifier resolved for the
    # question, plus the pinned set's subject. Everyone else found in a carrier
    # column is a peer, and is anonymised on the way into `evidence`.
    redactor = redactor_for(flow, schema_slice.resolved_values, custom_peers)
    tools = build_tools(
        evidence,
        question,
        lens,
        peer_only=peer_only,
        guard_zero_rows=schema_slice.guard_zero_rows,
        flow=flow,
        peers=pinned_peers(custom_peers, flow, active=custom_peers_active),
        redactor=redactor,
    )
    system_prompt = _solver_prompt(
        role=role,
        question=question,
        sub_question=sub_question,
        lens=lens,
        flow=flow,
        route=route,
        schema_slice=schema_slice,
        prior_digest=prior_digest,
        custom_peers=custom_peers,
        custom_peers_active=custom_peers_active,
    )
    agent = create_agent(
        model,
        tools,
        system_prompt=system_prompt,
        middleware=build_solver_middleware(
            model, flow=flow, lens=lens, summary_model=Initialization.llm_summary
        ),
    )
    try:
        agent.invoke(
            {"messages": [HumanMessage(content=sub_question)]},
            config={"recursion_limit": recursion_limit},
        )
    except GraphRecursionError as exc:
        # Budget exhausted — the rows gathered so far are still valid evidence.
        log_event(
            logger,
            "analyst_solver_recursion_limit",
            logging.WARNING,
            node="analyst_solver",
            lens=lens,
            flow=flow,
            tool_calls=len(evidence),
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - never crash the turn; keep partial evidence
        log_event(
            logger,
            "analyst_solver_error",
            logging.ERROR,
            node="analyst_solver",
            lens=lens,
            flow=flow,
            error=str(exc),
        )
    return stamp_redactions(evidence, redactor)


def digest_evidence(evidence: List[Evidence], *, limit: int = _TOOL_ROW_PREVIEW) -> str:
    """Compact JSON digest of gathered evidence for a dependent step or the writer."""
    return json.dumps(
        [
            {
                "lens": e.get("lens", ""),
                "flow": e["flow"],
                "sql": e["sql"],
                "rows": e["rows"][:limit],
            }
            for e in evidence
        ],
        default=str,
    )
