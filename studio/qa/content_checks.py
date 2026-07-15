"""Content-tier QA — facts, commentary, rules, confidentiality (Phase 6).

Pure functions over verified commentary + the EvidencePack. Severity policy:

  * a surviving sentence citing an unknown fact, or an unsupported number that
    slipped through → CRITICAL (must never export);
  * sentences the verifier dropped → WARNING (already handled, but visible);
  * recorded data gaps → WARNING with the honest reason;
  * a named peer in any final sentence → CRITICAL under no_peer_names.
"""
from __future__ import annotations

from typing import List, Sequence

from studio.ai.verifier import _norm, _TOKEN_RE
from studio.commentary.agent import SlideCommentary
from studio.commentary.verify import _allowed_number_tokens
from studio.content.evidence_pack import EvidencePack
from studio.qa.report import CRITICAL, INFO, WARNING, QAIssue

# Verifier codes that mean invented content (critical if ever present in output).
_CRITICAL_CODES = {"unsupported_number", "unknown_fact", "peer_name"}


def check_commentary_citations(
    commentary: Sequence[SlideCommentary], pack: EvidencePack
) -> List[QAIssue]:
    """Final safety net: every exported sentence's facts + numbers re-checked."""
    issues: List[QAIssue] = []
    for slide in commentary:
        for sent in slide.sentences:
            missing = [f for f in sent.fact_ids if f not in pack.items]
            if missing:
                issues.append(QAIssue(
                    "commentary_unknown_fact", CRITICAL,
                    f"sentence cites unknown fact id(s) {missing}", f"slide {slide.slide_idx}"))
                continue
            allowed = _allowed_number_tokens(pack, sent.fact_ids)
            bad = [m.group(0).strip() for m in _TOKEN_RE.finditer(sent.text)
                   if _norm(m.group(0)) and _norm(m.group(0)) not in allowed]
            if bad:
                issues.append(QAIssue(
                    "commentary_unsupported_number", CRITICAL,
                    f"number(s) {bad} not backed by cited facts", f"slide {slide.slide_idx}"))
    return issues


def check_commentary_verification(commentary: Sequence[SlideCommentary]) -> List[QAIssue]:
    """Surface what the verifier dropped, and record honest data gaps."""
    issues: List[QAIssue] = []
    for slide in commentary:
        for v in slide.issues:
            severity = WARNING if v.code in _CRITICAL_CODES else INFO
            issues.append(QAIssue(
                f"commentary_{v.code}", severity,
                f"verifier dropped content: {v.message}", f"slide {slide.slide_idx}"))
        if slide.data_gap:
            issues.append(QAIssue(
                "commentary_data_gap", WARNING,
                f"no commentary written: {slide.data_gap}", f"slide {slide.slide_idx}"))
    return issues


def check_confidentiality(
    commentary: Sequence[SlideCommentary], banned_names: Sequence[str]
) -> List[QAIssue]:
    """No individual peer name in any final, carrier-facing sentence."""
    issues: List[QAIssue] = []
    lowered = [(n, n.lower()) for n in banned_names if n]
    for slide in commentary:
        low = slide.text.lower()
        for name, name_low in lowered:
            if name_low in low:
                issues.append(QAIssue(
                    "peer_name_leak", CRITICAL,
                    f"individual peer name {name!r} in slide commentary",
                    f"slide {slide.slide_idx}"))
    return issues


def check_evidence_gaps(pack: EvidencePack) -> List[QAIssue]:
    """Blocked capabilities become recorded gaps, never generic filler."""
    return [
        QAIssue("capability_gap", INFO,
                f"section {cap.section!r} not supported: {cap.reason}", cap.section)
        for cap in pack.gaps()
    ]
