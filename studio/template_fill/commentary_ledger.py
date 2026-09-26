"""What happened to every commentary field in an assembled deck.

The finished ``.pptx`` cannot say which of its prose boxes the writer filled — a written
box is ordinary text, indistinguishable from the template's own copy — so Review could
only ever spot the boxes still showing their "fill me" mark. This ledger is taken at the
one moment the answer is known: after the prose is written and before the sub-decks are
filled. Each field is compared with the draft the composers left for it:

    written   the model's text (it differs from the draft)
    draft     the composers' deterministic text shipped as-is (no model, or ``auto`` fallback)
    empty     nothing reached the box — no finding survived, or there was nothing to say

and placed on the page it lands on in the MERGED deck, so Review can say "page 14,
Singapore · SWOT — Opportunities: not written" and take the author straight there.

Pure: sub-deck values and slide titles in, outcomes out. The sidecar helpers at the end
are the only IO, and they are best-effort by design.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

PROSE_PREFIXES = ("note:", "fbnote:")

WRITTEN = "written"
DRAFT = "draft"
EMPTY = "empty"

SIDECAR_SUFFIX = ".commentary.json"


@dataclass(frozen=True)
class TemplatePages:
    """What the ledger needs to know about one template's pages, read once per template."""

    titles: Tuple[str, ...] = ()
    sections: Tuple[str, ...] = ()                         # "feedback", "swot", ...
    headers: Mapping[Tuple[int, int], str] = field(default_factory=dict)  # (slide, shape)

    def title(self, slide: int) -> str:
        return self.titles[slide] if 0 <= slide < len(self.titles) else ""

    def section(self, slide: int) -> str:
        return self.sections[slide] if 0 <= slide < len(self.sections) else ""


@dataclass(frozen=True)
class FieldOutcome:
    """One commentary field of the delivered deck, and whether it was populated."""

    block: str              # "Overall", "Singapore", "Property" — the sub-deck it sits in
    template: str           # the sub-template it came from
    slide_no: int           # 1-based page in the MERGED deck
    page: str               # that page's title, as the template has it
    field: str              # what the field is for — "Key messages", "Opportunities"
    role: str               # the positional role, for tests and the log
    status: str             # WRITTEN | DRAFT | EMPTY
    lines: int = 0
    had_draft: bool = True  # False: the composers had nothing to say for this field
    section: str = ""       # the page's section -- "feedback" pages are qualitative

    @property
    def populated(self) -> bool:
        return self.status != EMPTY


def _slide_of(role: str) -> Optional[int]:
    """The template slide a prose role sits on — ``note:3:12:0`` / ``fbnote:3:12:p:0`` -> 3."""
    parts = str(role).split(":")
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None


def _shape_of(role: str) -> Optional[int]:
    parts = str(role).split(":")
    return int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None


def field_name(node: str) -> str:
    """A composer's node id as a reader would name the field."""
    text = str(node or "").strip()
    for prefix in ("feedback-", "feedback_", "commentary-", "commentary_"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    text = text.split(".")[-1].replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else "Commentary"


def _status(before: Any, after: Any) -> Tuple[str, int]:
    text = str(after or "") if isinstance(after, str) else str(after or "")
    lines = len([ln for ln in text.splitlines() if ln.strip()])
    if not lines:
        return EMPTY, 0
    draft = str(getattr(before, "draft", before) or "")
    return (DRAFT if text.strip() == draft.strip() else WRITTEN), lines


def _node_of(before: Any) -> str:
    """The composer's name for the field; a field that never got a draft has none."""
    return str(getattr(before, "node", "") or getattr(before, "topic", "") or "")


def page_offsets(slide_counts: Sequence[int]) -> List[int]:
    """Where each sub-deck starts in the merged deck (0-based), given its kept page counts."""
    out, at = [], 0
    for count in slide_counts:
        out.append(at)
        at += int(count)
    return out


def ledger(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]], *,
           blocks: Sequence[Tuple[str, str, Tuple[int, ...]]],
           pages: Mapping[str, TemplatePages]) -> List[FieldOutcome]:
    """Every prose field, in deck order.

    ``before`` / ``after`` are each sub-deck's values before and after the writer ran;
    ``blocks`` is ``(label, template, hidden pages)`` per sub-deck; ``pages`` describes each
    template's pages (:class:`TemplatePages`).
    """
    counts = []
    for _, template, hidden in blocks:
        total = len(pages.get(template, TemplatePages()).titles)
        counts.append(max(0, total - len({int(h) for h in hidden or () if 0 <= int(h) < total})))
    starts = page_offsets(counts)
    out: List[FieldOutcome] = []
    for i, (label, template, hidden) in enumerate(blocks):
        info = pages.get(template, TemplatePages())
        dropped = sorted(int(h) for h in hidden or ())
        for role, value in (before[i] if i < len(before) else {}).items():
            if not (isinstance(role, str) and role.startswith(PROSE_PREFIXES)):
                continue
            slide = _slide_of(role)
            if slide is None or slide in dropped:
                continue
            status, lines = _status(value, (after[i] if i < len(after) else {}).get(role))
            position = slide - sum(1 for h in dropped if h < slide)
            header = info.headers.get((slide, _shape_of(role) if _shape_of(role) is not None else -1), "")
            out.append(FieldOutcome(
                block=label or template.replace("_", " ").title(), template=template,
                slide_no=starts[i] + position + 1, page=info.title(slide),
                field=_field_label(header, _node_of(value), info.title(slide)), role=role,
                status=status, lines=lines,
                had_draft=bool(str(getattr(value, "draft", value) or "").strip()),
                section=info.section(slide),
            ))
    return sorted(out, key=lambda o: (o.slide_no, o.role))


def _field_label(header: str, node: str, page: str) -> str:
    """The header printed above the box, else the composer's name for it, else "Commentary"."""
    header = " ".join(str(header or "").split())
    if header and header != page:
        return header
    if node:
        return field_name(node)
    return "Commentary"


# ── the sidecar the assembled deck carries ───────────────────────────────────


def sidecar_path(deck_path: str) -> Path:
    return Path(str(deck_path) + SIDECAR_SUFFIX)


def write_sidecar(deck_path: str, outcomes: Sequence[FieldOutcome]) -> None:
    """Save the ledger beside the deck it describes. A failure costs Review a section,
    never the deck."""
    try:
        sidecar_path(deck_path).write_text(
            json.dumps([asdict(o) for o in outcomes], indent=1), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("commentary ledger: could not write beside %s: %s", deck_path, exc)


def read_sidecar(deck_path: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """The ledger saved beside ``deck_path`` — ``None`` for a deck built before it existed."""
    if not deck_path:
        return None
    path = sidecar_path(deck_path)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("commentary ledger: could not read %s: %s", path, exc)
        return None


def from_dicts(rows: Sequence[Mapping[str, Any]]) -> List[FieldOutcome]:
    fields = FieldOutcome.__dataclass_fields__
    return [FieldOutcome(**{k: v for k, v in dict(r).items() if k in fields}) for r in rows or []]
