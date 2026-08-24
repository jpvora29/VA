"""LLM value resolver — the semantic half of the hybrid retriever (decision #4).

A single thin signature: given a column, the user's query, and the column's
real distinct values, return the subset the query refers to *by meaning*. This
is the rescue path for conceptual queries that string-distance cannot bridge —
"manufacturing companies" -> the relevant `SIC_Major_Class` values, "professional
liability" -> the matching `Cover_Line` values.

It is invoked ONLY by `EntityResolver` after fuzzy misses on a registry
`resolver: semantic` column, and ONLY when `CONTEXT_ENGINE_SEMANTIC` is on, so
the call is rare and scoped. The module imports without credentials; the tier's
client is resolved at call time.

Hard guard: the model can only ever *select from the supplied candidates*. Any
value it returns that is not in the candidate list is dropped, so the resolver
can never invent a filter value that isn't in the database.
"""
from __future__ import annotations

from typing import List, Sequence

from core.llm import InputField, OutputField, Predictor, Signature
from logger import get_logger

logger = get_logger(__name__)

# Cap how many candidates we show the model — keeps the rescue call cheap on a
# very high-card column. The fuzzy stage already failed, so this is a fallback.
MAX_CANDIDATES = 200


class SemanticValueMatch(Signature):
    """Select the column values a conceptual query refers to.

    The query describes a category or concept (e.g. an industry, a line of
    business, a client segment). Choose ALL and ONLY the `candidates` that fall
    under that concept. If none apply, return an empty list. Never return a value
    that is not in `candidates` verbatim.
    """

    column: str = InputField(desc="The column being filtered (for context).")
    query: str = InputField(desc="The user's natural-language query.")
    candidates: List[str] = InputField(
        desc="The column's exact valid values. Choose only from these."
    )
    selected: List[str] = OutputField(
        desc="The subset of `candidates` the query refers to; [] if none."
    )


# A mechanical selection: no chain-of-thought, and the deterministic client this
# rescue call has always used.
_MATCH = Predictor(SemanticValueMatch, tier="balanced", label="semantic_value_match",
                   node="entity_resolver")


def resolve_semantic_values(
    *, column: str, query: str, candidates: Sequence[str]
) -> List[str]:
    """Map `query` to the matching members of `candidates` via the LLM.

    Returns only values present in `candidates` (the model cannot invent one),
    and [] on any failure — the caller treats that as "no match" and degrades to
    the deterministic fallback sample.
    """
    candidate_list = [str(c) for c in candidates][:MAX_CANDIDATES]
    if not candidate_list:
        return []

    try:
        result = _MATCH(column=column, query=query, candidates=candidate_list)
        selected = result.selected or []
    except Exception as exc:  # noqa: BLE001 - rescue is best-effort, never fatal
        logger.debug("resolve_semantic_values(%s) failed: %s", column, exc)
        return []

    # Guard: keep only verbatim candidates, preserving the model's order.
    allowed = set(candidate_list)
    return [v for v in (str(s) for s in selected) if v in allowed]
