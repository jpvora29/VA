"""The evidence a decision was taken on, captured from the answer that raised it.

"Create decision" under a chat answer used to carry two strings across: the
question as the title and the prose as the rationale. A month later the record
still said what was concluded, but nothing about *what it was concluded from* —
which carrier, which period, which dataset — so the reader had to find the
original conversation to judge whether the decision still held.

This module takes the snapshot instead. It is deliberately a snapshot and not a
live query: the scope and the figure recorded here are the ones the decision was
actually taken on, and they must not silently change when the dataset is
refreshed. An approved decision keeps the evidence that approved it.

Nothing is invented. Every field is read off the stamped answer — the lead
sentence, a figure the verifier already checked, the turn's own scope chips —
and a field the answer cannot supply is simply left blank.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from core.registry import get_flow_registry
from core.scope import chips_from_dicts, scope_line
from ui.components.answer_lead import split_lead

#: The evidence label is a caption under a number, not a paragraph.
_LABEL_MAX = 120
_DETAIL_MAX = 180


@dataclass(frozen=True)
class EvidenceSnapshot:
    """One piece of evidence as the decision brief prints it.

    ``value`` is the headline figure ("7.0%"); ``label`` says what it measures;
    ``detail`` is the qualifier beside it; ``scope`` and ``source`` say where it
    came from. Every one of them is optional — an item with only a ``label`` and
    a ``url`` is the plain attachment the board has always supported.
    """

    label: str = ""
    value: str = ""
    detail: str = ""
    scope: str = ""
    source: str = ""
    url: str = ""

    @property
    def is_empty(self) -> bool:
        return not any((self.label, self.value, self.detail, self.scope, self.source, self.url))

    @property
    def is_evidence(self) -> bool:
        """Whether this says where a number came from, and not just what it was.

        A caption on its own is a restatement; provenance is a figure, a scope,
        a dataset or a link. One of those has to be present for the snapshot to
        earn the "Evidence" heading it renders under.
        """
        return any((self.value, self.scope, self.source, self.url))

    def as_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "value": self.value,
            "detail": self.detail,
            "scope": self.scope,
            "source": self.source,
            "url": self.url,
        }


def snapshot_from_dict(raw: Mapping[str, Any]) -> EvidenceSnapshot:
    """Rebuild a snapshot from a stored evidence item.

    Tolerant by design: records written before this module existed hold only
    ``{label, url}``, and they must keep rendering as the attachment they are.
    """
    return EvidenceSnapshot(
        label=_text(raw.get("label")),
        value=_text(raw.get("value")),
        detail=_text(raw.get("detail")),
        scope=_text(raw.get("scope")),
        source=_text(raw.get("source")),
        url=_text(raw.get("url")),
    )


def snapshots(items: Sequence[Any] | None) -> list[EvidenceSnapshot]:
    """Every stored evidence item as a snapshot, skipping ones with nothing to say."""
    out = []
    for item in items or []:
        if isinstance(item, Mapping):
            snap = snapshot_from_dict(item)
        else:
            snap = EvidenceSnapshot(label=_text(item))
        if not snap.is_empty:
            out.append(snap)
    return out


# ── Capture from a chat answer ──────────────────────────────────────────────


def snapshot_from_answer(message: Mapping[str, Any] | None) -> Optional[EvidenceSnapshot]:
    """The evidence an answer supplies, or ``None`` when it supplies none.

    An answer's own sentence is not evidence — it is already the rationale, and
    repeating it under an "Evidence" heading would dress a restatement up as a
    source. So a snapshot is only produced when the answer carries at least one
    thing the rationale does not: a verified figure, the scope it was measured
    under, or the dataset it came from. Everything else returns ``None``, and the
    brief shows no evidence block rather than an empty card implying one was lost.
    """
    if not message:
        return None
    lead = split_lead(str(message.get("content") or ""))
    snap = EvidenceSnapshot(
        label=_clip(lead.headline, _LABEL_MAX),
        value=headline_figure(message.get("provenance")),
        detail=_clip(lead.standfirst, _DETAIL_MAX),
        scope=scope_line(chips_from_dicts(message.get("scope"))),
        source=source_line(message),
    )
    return snap if snap.is_evidence else None


def headline_figure(provenance: Mapping[str, Any] | None) -> str:
    """The first figure in the prose the verifier found in the rows.

    Only a *supported* figure is promoted to the big number on the brief. An
    unsupported one is exactly the figure nobody should be reading off a card as
    settled fact, and the answer's own trust panel is where it belongs.
    """
    for figure in (provenance or {}).get("figures") or []:
        if not isinstance(figure, Mapping):
            continue
        if figure.get("supported") and figure.get("checkable"):
            text = _text(figure.get("text"))
            if text:
                return text
    return ""


def source_line(message: Mapping[str, Any]) -> str:
    """"Premium · 9 Sep 2026" — the dataset that answered, and when it was asked."""
    parts = [route_label(_text(message.get("route"))), _asked_on(message.get("ts"))]
    return " · ".join(p for p in parts if p)


def route_label(route: str) -> str:
    """A dataset's business name, from the flow registry, else a tidied route id."""
    if not route:
        return ""
    try:
        spec = get_flow_registry().get(route)
    except Exception:  # pragma: no cover - a missing registry must not break a card
        spec = None
    if spec is not None and getattr(spec, "route_label", ""):
        return str(spec.route_label)
    return route.replace("_", " ").strip().capitalize()


def _asked_on(stamp: Any) -> str:
    """The date part of the answer's timestamp, whatever format it was stamped in."""
    text = _text(stamp)
    return text.split(",")[0].split("T")[0].strip() if text else ""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
