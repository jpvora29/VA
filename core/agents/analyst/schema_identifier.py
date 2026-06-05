"""Schema-relationship-identifier agent.

A single-shot structured node that, given the plan's sub-questions, names the
minimal table/column/join surface and the dimension filters that need grounding.
The node then resolves those filters deterministically (one
`match_column_values` call each) so the downstream solvers receive exact valid
strings instead of rediscovering them through exploratory tool calls — the
biggest source of wasted iterations in the old monolithic loop.
"""
from __future__ import annotations

import json
import logging
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage

from core.initialization import Initialization
from core.mcp.tools import get_schema, get_valid_values, match_column_values
from core.observability import log_event
from core.schemas.analyst_subgraph import SchemaIdentification, SchemaSlice
from logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are the Schema-Relationship Identifier in an insurance
analytics system. You do NOT write SQL or answer the question. Given a set of
analytical sub-questions plus the database schema and valid values, identify the
minimal grounding the downstream solvers need:

1. `tables` — only the tables actually required (e.g. ["GPR", "Peers"]).
2. `join_keys` — short notes on how those tables relate. For peer work, remember:
   the `Overall_Peer_Group` values in `Peers` ARE `Carrier_Group` names, so
   `GPR.Carrier_Group` is filtered against them directly — there is NO row-join.
3. `values_to_resolve` — EVERY dimension FILTER the sub-questions name, given as
   the exact column + the user's loose wording. This is critical: the stored
   values are rarely what users type (e.g. "Zurich" is stored as "ZURICH GROUP",
   "Chubb" as "CHUBB LIMITED"), so a carrier/country left unresolved produces a
   query that silently returns nothing. ALWAYS include:
     - the carrier(s) the question names -> column "Carrier_Group" (GPR) or
       "Carrier" (survey), even when the name looks already correct;
     - any country/region named;
     - industry / SIC_Major_Class, Product_Line, Cover_Line, Business_Line,
       Client_Segment, survey Sections / Attributes, etc.
   Do NOT list metrics, aggregations, or numbers/years. Use "Marsh" as-is — it is
   the broker, never a carrier, so never flag it for resolution.
4. `notes` — any other one-line grounding hint (optional).

Be minimal and precise. Never invent columns or tables not in the schema."""


def identify_schema(
    *, question: str, sub_questions: List[str], flow: str
) -> SchemaSlice:
    """Run the identifier and return a grounded `SchemaSlice` for the solvers."""
    schema = get_schema(flow)
    valid_values = get_valid_values(flow)

    human = (
        f"[PRIMARY FLOW] {flow}\n\n"
        f"[USER QUESTION]\n{question}\n\n"
        f"[SUB-QUESTIONS TO GROUND]\n"
        + "\n".join(f"- {sq}" for sq in sub_questions if sq)
        + f"\n\n[SCHEMA]\n{json.dumps(schema, default=str)}\n\n"
        f"[VALID VALUES (sample of grounded dimensions)]\n"
        f"{json.dumps({k: v for k, v in list(valid_values.items())}, default=str)}"
    )

    try:
        structured = Initialization.llm.with_structured_output(SchemaIdentification)
        identification = structured.invoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human)]
        )
    except Exception as exc:  # noqa: BLE001 - grounding is best-effort; degrade gracefully
        log_event(
            logger,
            "schema_identifier_error",
            logging.ERROR,
            node="schema_identifier",
            flow=flow,
            error=str(exc),
        )
        # Fall back to the flow's default table family so solvers still have a slice.
        return SchemaSlice(tables=list(schema.keys()))

    # Resolve the flagged terms deterministically into exact valid values.
    resolved: dict[str, List[str]] = {}
    for item in identification.values_to_resolve:
        if not item.column or not item.term:
            continue
        matches = match_column_values(flow, item.column, item.term)
        if matches:
            resolved.setdefault(item.column, [])
            for m in matches:
                if m not in resolved[item.column]:
                    resolved[item.column].append(m)

    slice_ = SchemaSlice(
        tables=identification.tables or list(schema.keys()),
        join_keys=identification.join_keys,
        resolved_values=resolved,
        notes=identification.notes,
    )
    log_event(
        logger,
        "schema_identified",
        node="schema_identifier",
        flow=flow,
        tables=slice_.tables,
        resolved_columns=list(resolved.keys()),
    )
    return slice_
