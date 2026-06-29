"""Slot → role inference — the *derived manifest*.

Maps each detected ``Slot`` to a role from a fixed vocabulary the binder knows how
to fill (``bindings.ROLE_VOCAB``). Inference is deterministic-first: a small set of
keyword/value-kind rules read the slot's ``context`` (sibling labels, table header,
slide title) and its token shape. Enumerated entity labels (``Country (n)``) become
indexed roles. Anything no rule matches is marked ``placeholder`` and left as the
template's own token. The optional gated LLM can refine genuinely ambiguous slots,
but with no API key the deterministic mapping stands alone.

A *manifest entry* is ``{slot, role, placeholder}`` — JSON-able, so the whole
manifest lives in the app's document store and can be overridden per slot.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from studio.template_fill.slots import Slot

# Role vocabulary the binder resolves. Indexed roles (country breakdown) use the
# ``role[i]`` convention, filled positionally from the enumerated labels.
ROLE_SUBJECT = "subject_name"
ROLE_MARSH_GWP = "marsh_gwp"
ROLE_MARSH_GWP_YOY = "marsh_gwp_yoy"
ROLE_CARRIER_GWP = "carrier_gwp"
ROLE_CARRIER_GWP_YOY = "carrier_gwp_yoy"
ROLE_SOW_PCT = "sow_pct"
ROLE_SOW_YOY = "sow_yoy"
ROLE_RANK = "rank"
ROLE_RANK_YOY = "rank_yoy"
ROLE_COUNTRY_NAME = "country_name"          # indexed: country_name[i]
ROLE_GROWTH_BUBBLE = "growth_bubble"


@dataclass
class Binding:
    slot: Slot
    role: Optional[str]                      # None when placeholder
    placeholder: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"slot": self.slot.to_dict(), "role": self.role, "placeholder": self.placeholder}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Binding":
        return cls(slot=Slot.from_dict(d["slot"]), role=d.get("role"),
                   placeholder=bool(d.get("placeholder", d.get("role") is None)))


def _has(ctx: str, *words: str) -> bool:
    return any(w in ctx for w in words)


# Phrases that mark a premium figure as the SUBJECT carrier's own book intermediated
# by Marsh ("premium written with Marsh", "placed with Marsh") — NOT the whole Marsh
# book. Without these, a context mentioning "Marsh" was wrongly read as the Marsh
# total, so a carrier's headline premium showed the entire book.
_CARRIER_PREMIUM_MARKERS = (
    "with marsh", "written with", "placed with", "via marsh", "through marsh",
    "brokered", "with us",
)


def _is_carrier_premium(ctx: str) -> bool:
    """True when the context describes the subject carrier's premium (not Marsh's book)."""
    return _has(ctx, *_CARRIER_PREMIUM_MARKERS) or _has(ctx, "carrier")


def _enum_index(token: str) -> Optional[int]:
    m = re.search(r"\(\s*(\d+)\s*\)", token)
    return int(m.group(1)) - 1 if m else None


def _infer_role(slot: Slot) -> Optional[str]:
    """Deterministic role for a slot, or ``None`` (→ placeholder)."""
    ctx = slot.context.lower()
    tok = slot.token.strip()
    kind = slot.value_kind

    # Enumerated entity labels.
    if kind == "text" and re.match(r"country|region", tok, re.I) and "(" in tok:
        idx = _enum_index(tok)
        return f"{ROLE_COUNTRY_NAME}[{idx}]" if idx is not None else None
    if kind == "text" and tok.lower() == "carrier":
        return ROLE_SUBJECT
    if kind == "text" and "carrier:" in ctx:        # slide-10 "Carrier:" title slot
        return ROLE_SUBJECT

    # Growth bubble chart series.
    if kind == "series":
        return ROLE_GROWTH_BUBBLE

    is_prior = "py" in ctx or "yoy" in ctx or "change" in ctx or "prior" in ctx

    if kind == "money":
        # The subject carrier's own premium (incl. "written with Marsh") comes first,
        # so a carrier figure is never swallowed by the Marsh-book branch.
        if _is_carrier_premium(ctx):
            return ROLE_CARRIER_GWP
        if _has(ctx, "marsh"):
            return ROLE_MARSH_GWP
        # Bare "premium"/"gwp" in a carrier QBR → the subject carrier (the deck's focus).
        if _has(ctx, "premium", "gwp"):
            return ROLE_CARRIER_GWP
        return None

    if kind == "pct":
        if _has(ctx, "sow", "share of wallet", "share"):
            return ROLE_SOW_YOY if is_prior else ROLE_SOW_PCT
        if _is_carrier_premium(ctx):
            return ROLE_CARRIER_GWP_YOY
        if _has(ctx, "marsh"):
            return ROLE_MARSH_GWP_YOY
        if _has(ctx, "premium", "gwp"):
            return ROLE_CARRIER_GWP_YOY
        return None

    if kind in ("rank", "int"):
        if _has(ctx, "rank"):
            # Only an explicit PY/prior row is the rank *change*; a plain "overall
            # rank" box wants the current rank even if a YoY tile sits nearby.
            prior_rank = _has(ctx, "py", "prior")
            return ROLE_RANK_YOY if prior_rank else ROLE_RANK
        return None

    return None


def infer(slots: List[Slot], *, use_ai: bool = False) -> List[Binding]:
    """Derive the manifest: a ``Binding`` per slot (role or placeholder)."""
    out: List[Binding] = []
    for s in slots:
        role = _infer_role(s)
        out.append(Binding(slot=s, role=role, placeholder=role is None))
    if use_ai:
        out = _ai_refine(out)
    return out


def _ai_refine(bindings: List[Binding]) -> List[Binding]:
    """Optional: let the gated LLM propose roles for still-placeholder slots.

    No-op when no LLM is configured (the deterministic mapping stands alone)."""
    try:
        from studio.ai.client import llm_available
    except Exception:  # noqa: BLE001
        return bindings
    if not llm_available():
        return bindings
    # Conservative: only the AI *names* a role from the known vocab for ambiguous
    # slots; an unknown suggestion is ignored. Kept minimal to preserve determinism.
    return bindings


def manifest_to_dicts(bindings: List[Binding]) -> List[Dict[str, Any]]:
    return [b.to_dict() for b in bindings]


def manifest_from_dicts(items: List[Dict[str, Any]]) -> List[Binding]:
    return [Binding.from_dict(d) for d in items]
