"""Deterministic faithfulness verifier for AI-written prose.

The 'LLM never emits a number that isn't in the data' rule, enforced after the
fact: every numeric token an agent writes must already appear in the deterministic
source it was given (the slide's takeaways / evidence / KPI values + the fact
store), and no individual peer/carrier name may appear (confidentiality — only the
subject and "Marsh" are nameable). Offending sentences are dropped; the caller
keeps whatever survives, else falls back to the deterministic text.

Pure — no LLM, no DB — so it is unit-testable with planted violations.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Set, Tuple

# A numeric token: optional #/sign/currency, digits (with commas/decimal), optional
# unit suffix (%, x, pts, m, bn, b, k).
_TOKEN_RE = re.compile(r"[#+\-]?\s*(?:usd\s*|\$)?\d[\d,]*(?:\.\d+)?\s*(?:%|x|pts|bn|b|m|k)?", re.I)
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def _norm(tok: str) -> str:
    """Normalise a numeric token for comparison ($/USD/commas/sign/# stripped)."""
    t = tok.lower().strip()
    for junk in ("usd", "$", ",", " ", "#", "+"):
        t = t.replace(junk, "")
    return t.lstrip("-").strip()


def allowed_numbers(*sources: str) -> Set[str]:
    """The set of normalised numeric tokens present in the deterministic sources."""
    out: Set[str] = set()
    for s in sources:
        for m in _TOKEN_RE.finditer(s or ""):
            norm = _norm(m.group(0))
            if norm:
                out.add(norm)
    return out


def _violations(sentence: str, allowed: Set[str], forbidden: Sequence[str]) -> List[str]:
    issues: List[str] = []
    for m in _TOKEN_RE.finditer(sentence):
        norm = _norm(m.group(0))
        if norm and norm not in allowed:
            issues.append(f"unsupported number '{m.group(0).strip()}'")
    low = sentence.lower()
    for name in forbidden:
        if name and name.lower() in low:
            issues.append(f"peer name '{name}'")
    return issues


def verify_text(
    text: str, allowed: Set[str], *, forbidden_names: Sequence[str] = ()
) -> Tuple[str, List[str]]:
    """Drop sentences with an unsupported number or a forbidden peer name.

    Returns ``(clean_text, issues)``. A short fragment with no sentence punctuation
    is treated as a single unit.
    """
    if not text:
        return "", []
    sentences = _SENT_RE.split(text.strip())
    kept: List[str] = []
    issues: List[str] = []
    for sent in sentences:
        v = _violations(sent, allowed, forbidden_names)
        if v:
            issues.extend(v)
            continue
        if sent.strip():
            kept.append(sent.strip())
    return " ".join(kept), issues


def verify_bullets(
    bullets: Iterable[str], allowed: Set[str], *, forbidden_names: Sequence[str] = ()
) -> Tuple[List[str], List[str]]:
    """Filter a list of bullets to the faithful ones; collect issues."""
    clean: List[str] = []
    issues: List[str] = []
    for b in bullets:
        v = _violations(b or "", allowed, forbidden_names)
        if v:
            issues.extend(v)
        elif (b or "").strip():
            clean.append(b.strip())
    return clean, issues
