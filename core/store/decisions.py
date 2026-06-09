"""Decision Board persistence (user-scoped, fully separate from agent memory).

A *decision* is a manually-authored business record shown as a colour-coded
sticky card on a Kanban board. Mutations are diffed and written to an
append-only ``decision_revisions`` audit trail, so the board is reliable and
auditable without ever invoking the LLM. JSON-shaped fields (stakeholders,
evidence, links) are stored as Text blobs and (de)serialised here so callers
always deal in plain Python lists/dicts.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from sqlalchemy import delete, func, insert, select, update

from core.store.db import app_engine, decision_revisions, decisions
from logger import get_logger

logger = get_logger(__name__)

# Canonical statuses, in board column order.
STATUSES: tuple[str, ...] = (
    "planned",
    "under_review",
    "approved",
    "blocked",
    "archived",
)
PRIORITIES: tuple[str, ...] = ("high", "med", "low")

# Fields tracked individually in the revision audit trail when they change.
_TRACKED_FIELDS: tuple[str, ...] = (
    "title",
    "statement",
    "rationale",
    "discussion",
    "owner",
    "stakeholders",
    "status",
    "priority",
    "decision_date",
    "due_date",
    "evidence",
    "links",
)
_JSON_FIELDS = {"stakeholders": list, "evidence": list, "links": dict}


def _uid(user_id: int | str) -> Optional[int]:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def _loads(field: str, raw: Any) -> Any:
    """Deserialise a JSON-text field, falling back to its empty container."""
    default = _JSON_FIELDS[field]()
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _row_to_dict(row: Any) -> dict[str, Any]:
    """SQLAlchemy row -> plain decision dict with JSON fields decoded."""
    d = dict(row._mapping)
    for field in _JSON_FIELDS:
        d[field] = _loads(field, d.get(field))
    d["pinned"] = bool(d.get("pinned"))
    d["created_at"] = str(d.get("created_at"))
    d["updated_at"] = str(d.get("updated_at"))
    return d


def _encode(field: str, value: Any) -> Any:
    """Serialise JSON fields to text for storage; pass other fields through."""
    if field in _JSON_FIELDS:
        return json.dumps(value if value is not None else _JSON_FIELDS[field]())
    return value


# ── Reads ─────────────────────────────────────────────────────────────────────


def list_decisions(
    user_id: int | str,
    *,
    search: str | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    sort: str = "manual",
) -> list[dict[str, Any]]:
    """All decisions for a user, optionally filtered and sorted.

    ``sort`` is one of ``manual`` (pinned first, then sort_order),
    ``updated`` (newest edit first), ``created`` (newest first),
    ``priority`` (high→low), or ``due`` (soonest due date first).
    Pinned cards always float to the top of their group.
    """
    uid = _uid(user_id)
    if uid is None:
        return []
    with app_engine.connect() as conn:
        rows = conn.execute(
            select(decisions).where(decisions.c.user_id == uid)
        ).all()
    items = [_row_to_dict(r) for r in rows]

    if statuses:
        wanted = set(statuses)
        items = [d for d in items if d["status"] in wanted]
    if priorities:
        wanted = set(priorities)
        items = [d for d in items if d["priority"] in wanted]
    if search:
        needle = search.strip().lower()
        if needle:
            items = [d for d in items if _matches(d, needle)]

    _order = {"high": 0, "med": 1, "low": 2}
    keys = {
        "manual": lambda d: (not d["pinned"], d["sort_order"], d["title"].lower()),
        "updated": lambda d: (not d["pinned"], _desc(d["updated_at"])),
        "created": lambda d: (not d["pinned"], _desc(d["created_at"])),
        "priority": lambda d: (not d["pinned"], _order.get(d["priority"], 1)),
        "due": lambda d: (not d["pinned"], d["due_date"] or "9999-12-31"),
    }
    items.sort(key=keys.get(sort, keys["manual"]))
    return items


def _matches(d: dict[str, Any], needle: str) -> bool:
    """Case-insensitive substring search across the human-readable fields."""
    haystack = " ".join(
        str(d.get(f) or "")
        for f in ("title", "statement", "rationale", "discussion", "owner")
    )
    haystack += " " + " ".join(str(s) for s in d.get("stakeholders") or [])
    return needle in haystack.lower()


def _desc(value: str) -> str:
    """Sort helper: invert a string so ascending sort yields newest-first."""
    return "".join(chr(255 - ord(c)) for c in value)


def get_decision(user_id: int | str, decision_id: str) -> Optional[dict[str, Any]]:
    """A single decision owned by ``user_id``, or ``None``."""
    uid = _uid(user_id)
    if uid is None:
        return None
    with app_engine.connect() as conn:
        row = conn.execute(
            select(decisions).where(
                (decisions.c.id == decision_id) & (decisions.c.user_id == uid)
            )
        ).first()
    return _row_to_dict(row) if row is not None else None


def list_revisions(user_id: int | str, decision_id: str) -> list[dict[str, Any]]:
    """Audit trail for a decision, newest first (ownership-checked)."""
    if get_decision(user_id, decision_id) is None:
        return []
    with app_engine.connect() as conn:
        rows = conn.execute(
            select(decision_revisions)
            .where(decision_revisions.c.decision_id == decision_id)
            .order_by(decision_revisions.c.created_at.desc(), decision_revisions.c.id.desc())
        ).all()
    out = []
    for r in rows:
        rev = dict(r._mapping)
        rev["created_at"] = str(rev.get("created_at"))
        out.append(rev)
    return out


# ── Writes ──────────────────────────────────────────────────────────────────


def _log_revision(conn: Any, decision_id: str, uid: int, action: str, **kw: Any) -> None:
    conn.execute(
        insert(decision_revisions).values(
            decision_id=decision_id,
            user_id=uid,
            action=action,
            field=kw.get("field"),
            old_value=kw.get("old_value"),
            new_value=kw.get("new_value"),
            note=kw.get("note"),
        )
    )


def create_decision(user_id: int | str, fields: dict[str, Any]) -> Optional[str]:
    """Insert a new decision; returns its id. ``fields`` may set any column.

    A new card lands at the top of its column (lowest sort_order) and records a
    ``created`` revision.
    """
    uid = _uid(user_id)
    if uid is None:
        return None
    decision_id = uuid.uuid4().hex
    values: dict[str, Any] = {
        "id": decision_id,
        "user_id": uid,
        "title": (fields.get("title") or "Untitled decision").strip(),
        "statement": fields.get("statement") or "",
        "rationale": fields.get("rationale"),
        "discussion": fields.get("discussion"),
        "owner": fields.get("owner"),
        "stakeholders": _encode("stakeholders", fields.get("stakeholders")),
        "status": fields.get("status") if fields.get("status") in STATUSES else "planned",
        "priority": fields.get("priority") if fields.get("priority") in PRIORITIES else "med",
        "decision_date": fields.get("decision_date"),
        "due_date": fields.get("due_date"),
        "pinned": 1 if fields.get("pinned") else 0,
        "sort_order": _min_sort_order(uid) - 1,
        "evidence": _encode("evidence", fields.get("evidence")),
        "links": _encode("links", fields.get("links")),
    }
    try:
        with app_engine.begin() as conn:
            conn.execute(insert(decisions).values(**values))
            _log_revision(conn, decision_id, uid, "created", new_value=values["title"])
    except Exception:  # pragma: no cover - persistence must not crash the UI
        logger.exception("Failed to create decision")
        return None
    return decision_id


def _min_sort_order(uid: int) -> int:
    with app_engine.connect() as conn:
        lo = conn.execute(
            select(func.min(decisions.c.sort_order)).where(decisions.c.user_id == uid)
        ).scalar()
    return int(lo) if lo is not None else 0


def update_decision(
    user_id: int | str, decision_id: str, fields: dict[str, Any]
) -> bool:
    """Patch the given fields, writing one audit row per changed tracked field.

    A change to ``status`` is logged as ``status_changed`` rather than the
    generic ``updated`` so it stands out in the timeline.
    """
    uid = _uid(user_id)
    if uid is None:
        return False
    current = get_decision(uid, decision_id)
    if current is None:
        return False

    changes: dict[str, Any] = {}
    revisions: list[dict[str, Any]] = []
    for field in _TRACKED_FIELDS:
        if field not in fields:
            continue
        new_val = fields[field]
        old_val = current.get(field)
        if field == "status" and new_val not in STATUSES:
            continue
        if field == "priority" and new_val not in PRIORITIES:
            continue
        if new_val == old_val:
            continue
        changes[field] = _encode(field, new_val)
        revisions.append(
            {
                "action": "status_changed" if field == "status" else "updated",
                "field": field,
                "old_value": _audit_text(old_val),
                "new_value": _audit_text(new_val),
            }
        )

    # Pin toggling and reordering are housekeeping, not audited as edits.
    if "pinned" in fields:
        changes["pinned"] = 1 if fields["pinned"] else 0
    if "sort_order" in fields:
        changes["sort_order"] = int(fields["sort_order"])

    if not changes:
        return True
    try:
        with app_engine.begin() as conn:
            conn.execute(
                update(decisions)
                .where((decisions.c.id == decision_id) & (decisions.c.user_id == uid))
                .values(**changes)
            )
            for rev in revisions:
                _log_revision(conn, decision_id, uid, **rev)
    except Exception:  # pragma: no cover
        logger.exception("Failed to update decision %s", decision_id)
        return False
    return True


def _audit_text(value: Any) -> str:
    """Compact, human-readable rendering of a value for the audit trail."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str)
    return "" if value is None else str(value)


def change_status(user_id: int | str, decision_id: str, status: str) -> bool:
    """Convenience wrapper used by the board's status dropdowns / drag-drop."""
    return update_decision(user_id, decision_id, {"status": status})


def reopen_decision(
    user_id: int | str, decision_id: str, *, status: str = "under_review", note: str = ""
) -> bool:
    """Move an archived/blocked decision back into play with an audit note."""
    uid = _uid(user_id)
    if uid is None:
        return False
    current = get_decision(uid, decision_id)
    if current is None or status not in STATUSES:
        return False
    try:
        with app_engine.begin() as conn:
            conn.execute(
                update(decisions)
                .where((decisions.c.id == decision_id) & (decisions.c.user_id == uid))
                .values(status=status)
            )
            _log_revision(
                conn,
                decision_id,
                uid,
                "reopened",
                field="status",
                old_value=current["status"],
                new_value=status,
                note=note or None,
            )
    except Exception:  # pragma: no cover
        logger.exception("Failed to reopen decision %s", decision_id)
        return False
    return True


def toggle_pin(user_id: int | str, decision_id: str) -> bool:
    """Flip the pinned flag for a decision."""
    current = get_decision(user_id, decision_id)
    if current is None:
        return False
    return update_decision(user_id, decision_id, {"pinned": not current["pinned"]})


def delete_decision(user_id: int | str, decision_id: str) -> None:
    """Remove a decision and its audit trail (owner-checked)."""
    uid = _uid(user_id)
    if uid is None:
        return
    with app_engine.begin() as conn:
        conn.execute(
            delete(decision_revisions).where(
                decision_revisions.c.decision_id == decision_id
            )
        )
        conn.execute(
            delete(decisions).where(
                (decisions.c.id == decision_id) & (decisions.c.user_id == uid)
            )
        )
