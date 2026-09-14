"""Committing evidence by stable identity, and merging it idempotently.

The analyst subgraph fans solvers out in parallel and may re-run a step after a
failure. With an append-only channel, both of those produce duplicates: the same
query recorded twice reads downstream as two independent confirmations of the
same number, and a repaired step leaves its broken predecessor sitting in the
evidence the writer quotes from.

The fix is identity. An evidence record is keyed by what it IS — flow, tool,
parameters, executed scope — not by when it arrived. Committing the same record
twice is a no-op; committing a newer version of it replaces the old one in place
and keeps its position, so a repair changes a number without reshuffling the
answer around it.

Pure and dependency-light on purpose: no database, no model, no graph. The
reducer this module provides is what the subgraph's `evidence` channel uses in
place of `operator.add`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from core.schemas.analyst_subgraph import Evidence

#: A record that ran, returned rows, and passed its checks.
VALIDATED = "validated"
#: Ran cleanly and returned nothing. NOT an error, and NOT a zero.
NO_DATA = "no_data"
#: Raised, timed out, or returned something unusable.
FAILED = "failed"
#: Never attempted, with a reason.
SKIPPED = "skipped"

STATUSES = frozenset({VALIDATED, NO_DATA, FAILED, SKIPPED})

#: Statuses whose rows may be quoted in an answer.
QUOTABLE = frozenset({VALIDATED})


def _canonical(value: Any) -> Any:
    """A JSON-stable rendering, so identity does not depend on dict ordering."""
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=str)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def evidence_id(
    *,
    flow: str,
    tool: str,
    parameters: Optional[Mapping[str, Any]] = None,
    actual_scope: Optional[Mapping[str, Any]] = None,
    sql: str = "",
) -> str:
    """Stable identity for one retrieval.

    Deliberately excludes the rows, the timestamp and the step that asked: the
    same query under the same scope is the same evidence however often it runs
    and whoever asked for it, and that is exactly what makes a retry idempotent.
    `sql` participates only when no structured parameters exist, so a
    whitespace-only change to generated SQL does not mint a new record.
    """
    payload = {
        "flow": flow,
        "tool": tool,
        "parameters": _canonical(parameters or {}),
        "actual_scope": _canonical(actual_scope or {}),
        "sql": "" if parameters else " ".join((sql or "").split()),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"ev_{digest[:16]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_evidence(
    *,
    flow: str,
    rows: Sequence[Any],
    lens: str = "",
    tool: str = "",
    sql: str = "",
    parameters: Optional[Mapping[str, Any]] = None,
    requested_scope: Optional[Mapping[str, Any]] = None,
    actual_scope: Optional[Mapping[str, Any]] = None,
    step_id: str = "",
    metric: str = "",
    unit: str = "",
    period_coverage: Optional[Sequence[Any]] = None,
    source_version: str = "",
    status: str = "",
    note: str = "",
    redacted_peers: Sequence[str] = (),
    facts: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Evidence:
    """One evidence record, with its identity and provenance filled in.

    `status` is derived when the caller does not state one: rows mean validated,
    no rows mean `no_data`. A caller that knows better — a tool that raised —
    passes `FAILED` explicitly, because an exception and an empty result are
    different findings and only the caller can tell them apart.
    """
    actual = dict(actual_scope if actual_scope is not None else (requested_scope or {}))
    record: Evidence = {
        "flow": flow,
        "sql": sql,
        "rows": list(rows),
        "lens": lens,
        "evidence_id": evidence_id(
            flow=flow, tool=tool, parameters=parameters, actual_scope=actual, sql=sql
        ),
        "step_id": step_id,
        "tool": tool or ("run_sql" if sql else ""),
        "parameters": dict(parameters or {}),
        "scope": dict(requested_scope or {}),
        "actual_scope": actual,
        "metric": metric,
        "unit": unit,
        "period_coverage": list(period_coverage or []),
        "retrieved_at": now_iso(),
        "status": status or (VALIDATED if rows else NO_DATA),
        "note": note,
        "version": 1,
    }
    if source_version:
        record["source_version"] = source_version
    if redacted_peers:
        record["redacted_peers"] = tuple(redacted_peers)
    if facts is not None:
        record["facts"] = [dict(f) for f in facts]
    return record


def identity_of(record: Mapping[str, Any]) -> str:
    """The record's id, computed from its content when it carries none.

    Lets a record built before this module existed take part in a merge without
    a migration — the fallback derives the same id the builder would have.
    """
    existing = record.get("evidence_id")
    if existing:
        return str(existing)
    return evidence_id(
        flow=str(record.get("flow", "")),
        tool=str(record.get("tool", "")),
        parameters=record.get("parameters"),
        actual_scope=record.get("actual_scope") or record.get("scope"),
        sql=str(record.get("sql", "")),
    )


def supersedes(incoming: Mapping[str, Any], existing: Mapping[str, Any]) -> bool:
    """Whether `incoming` should replace `existing` for the same identity.

    A higher version always wins — that is a deliberate re-run. At equal
    versions a validated record replaces one that failed or found nothing, which
    is how a repaired step's result takes the place of the failure that prompted
    it. Otherwise the first writer keeps the slot, so two parallel solvers that
    happen to run the same query cannot flip the answer between them.
    """
    if int(incoming.get("version", 1)) > int(existing.get("version", 1)):
        return True
    if int(incoming.get("version", 1)) < int(existing.get("version", 1)):
        return False
    return (
        incoming.get("status") == VALIDATED and existing.get("status") != VALIDATED
    )


def merge_evidence(
    existing: Optional[Sequence[Evidence]], incoming: Optional[Sequence[Evidence]]
) -> List[Evidence]:
    """Idempotent union, preserving first-seen order.

    This is the reducer the subgraph's `evidence` channel uses instead of
    `operator.add`. Committing the same record twice changes nothing; committing
    a newer version replaces the old one WHERE IT STANDS, so a repair does not
    reorder the evidence an answer was built from.
    """
    merged: List[Evidence] = list(existing or [])
    positions = {identity_of(record): index for index, record in enumerate(merged)}
    for record in incoming or []:
        key = identity_of(record)
        if key not in positions:
            positions[key] = len(merged)
            merged.append(record)
            continue
        index = positions[key]
        if supersedes(record, merged[index]):
            merged[index] = record
    return merged


def revise(record: Evidence, **changes: Any) -> Evidence:
    """A new version of one record, keeping its identity.

    The identity is deliberately NOT recomputed: a repair that re-runs the same
    query with a corrected filter is a different query and mints its own record,
    while a repair that only re-reads or re-validates the same query must stay
    the same record or the merge will treat it as a second confirmation.
    """
    revised: Evidence = {**record, **changes}
    revised["version"] = int(record.get("version", 1)) + 1
    revised["retrieved_at"] = now_iso()
    revised["evidence_id"] = identity_of(record)
    return revised


def quotable(records: Iterable[Mapping[str, Any]]) -> List[Evidence]:
    """Records whose rows an answer may cite.

    A record with no `status` predates the contract and is judged by its rows,
    so existing callers keep working. Everything else must say it is validated.
    """
    return [
        record  # type: ignore[misc]
        for record in records or []
        if (record.get("status") or (VALIDATED if record.get("rows") else NO_DATA))
        in QUOTABLE
    ]


def scope_divergence(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Filters the turn asked for that the executed query did not apply.

    An empty result means the query ran on the scope it was given. A non-empty
    one is the finding: the number is real and it is not the number that was
    asked for, which is the single most dangerous kind of wrong answer because
    nothing about it looks wrong.
    """
    requested = record.get("scope") or {}
    actual = record.get("actual_scope")
    if actual is None:
        return {}
    return {
        column: value
        for column, value in requested.items()
        if actual.get(column) != value
    }
