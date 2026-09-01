"""The checkpoint between tagging and writing: is this worth summarising?

Two checks, in order of cost. The rule-based one is pure Python and always runs — too
few priority pairs, or too many unclassified bullets, means the tagging did not work
and the minutes would be thin, so the run stops rather than producing a bad document.
The LLM-as-judge pass then audits the selection and may correct individual bullets,
after which the priorities are re-scored.

A failure raises :class:`VerificationFailed`, which the workspace shows to the user.
The standalone version raised ``SystemExit`` here, which inside a web app would have
killed the request thread with no message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from logger import get_logger
from mom import config
from mom.llm import JsonCaller
from mom.tagger import Tag, TaggingResult, save_priorities, score_priorities

log = get_logger(__name__)

UNCLASSIFIED = config.UNCLASSIFIED


class VerificationFailed(RuntimeError):
    """The tagged output is not good enough to write minutes from."""


@dataclass(frozen=True)
class VerificationResult:
    """What one check found."""

    passed: bool
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    corrections: List[dict] = field(default_factory=list)  # [{id, umbrella_tag, sub_tag}]

    def log_to(self, logger) -> None:
        for warning in self.warnings:
            logger.warning("MoM verifier: %s", warning)
        for error in self.errors:
            logger.error("MoM verifier: %s", error)


# ── check 1: rules ────────────────────────────────────────────────────────────


def _unclassified_rate(tagged_bullets: Sequence[dict]) -> Tuple[int, float]:
    unclassified = sum(
        1 for b in tagged_bullets if b.get("sub_tag") in (UNCLASSIFIED, "", None)
    )
    return unclassified, (unclassified / len(tagged_bullets) if tagged_bullets else 0.0)


def verify_rules(
    top_pairs: Sequence[dict],
    tagged_bullets: Sequence[dict],
    *,
    min_pairs: int = config.VERIFIER_MIN_PAIRS,
    max_unclassified_pct: float = config.VERIFIER_MAX_UNCLASSIFIED_PCT,
    warn_unclassified_pct: float = config.VERIFIER_WARN_UNCLASSIFIED_PCT,
) -> VerificationResult:
    """Structural sanity checks. No LLM call, always fast."""
    errors: List[str] = []
    warnings: List[str] = []

    if len(top_pairs) < min_pairs:
        errors.append(
            f"Only {len(top_pairs)} priority pair(s) were produced (at least {min_pairs} "
            "are needed). Very little of the note or the deck matched the tag list."
        )

    unclassified, rate = _unclassified_rate(tagged_bullets)
    if tagged_bullets:
        message = (
            f"{unclassified}/{len(tagged_bullets)} meeting-note bullets are unclassified "
            f"({rate:.0%}). Check that the sub-tag names in the tag list fit this meeting."
        )
        if rate > max_unclassified_pct:
            errors.append(message)
        elif rate > warn_unclassified_pct:
            warnings.append(message)

    empty = [f"{p['umbrella_tag']} / {p['sub_tag']}" for p in top_pairs
             if not p.get("meeting_note_bullets") and not p.get("ppt_entries")]
    if empty:
        warnings.append(f"Priority pairs with no supporting content: {empty}")

    zero_score = [f"{p['umbrella_tag']} / {p['sub_tag']}" for p in top_pairs
                  if p.get("score", 0) == 0]
    if zero_score:
        warnings.append(f"Priority pairs scored zero: {zero_score}")

    return VerificationResult(passed=not errors, warnings=warnings, errors=errors)


# ── check 2: the model as judge ───────────────────────────────────────────────


def build_audit_prompt(
    top_pairs: Sequence[dict], meeting_data: dict, tagged_bullets: Sequence[dict]
) -> str:
    pair_lines = "\n".join(
        f"  {i + 1:2d}. {p['umbrella_tag']} / {p['sub_tag']}"
        f"  (score={p['score']}, mn={p['meeting_note_count']}, ppt={p['ppt_count']})"
        for i, p in enumerate(top_pairs[:10])
    )

    topic_lines: List[str] = []
    for point in meeting_data.get("discussion_points", [])[:6]:
        topic = point.get("topic", "")
        if topic:
            topic_lines.append(f"  Topic: {topic}")
            topic_lines += [f"    • {b}" for b in point.get("bullets", [])[:2]]
    topics = "\n".join(topic_lines) or "  (no topics extracted)"

    correction_block = ""
    if tagged_bullets:
        sample = "\n".join(
            f"  [{b['id']}] [{b['umbrella_tag']} / {b['sub_tag']}] {b['bullet']}"
            for b in tagged_bullets[:40]
        )
        correction_block = (
            "\n\nTagged meeting-note bullets (sample — up to 40):\n"
            f"{sample}\n\n"
            "For each bullet above that is clearly mis-tagged, include a correction in the "
            "`corrections` list. Only flag obvious mistakes — do not second-guess borderline cases."
        )

    return (
        "You are auditing the output of an automated tag-scoring pipeline for a "
        "Marsh ICG Quarterly Business Review.\n\n"
        "Meeting topics discussed:\n"
        f"{topics}\n\n"
        "The pipeline selected these top priority (umbrella / sub-tag) pairs "
        "for summary generation:\n"
        f"{pair_lines}\n"
        f"{correction_block}\n\n"
        "Your task:\n"
        "- Assess whether the priority pairs plausibly reflect the meeting's themes.\n"
        "- Flag any pair that seems clearly misaligned with the meeting content.\n"
        "- Flag any important theme from the meeting that is conspicuously absent.\n"
        "- Suggest corrections for obviously mis-tagged bullets (if bullet sample provided).\n"
        "- Be concise. Only flag genuine concerns — minor omissions are fine.\n\n"
        "Return ONLY valid JSON:\n"
        '{\n'
        '  "verdict": "pass",\n'
        '  "issues": [],\n'
        '  "notes": "brief explanation",\n'
        '  "corrections": [\n'
        '    {"id": "mn_0012", "umbrella_tag": "Strategy & Initiatives", "sub_tag": "Growth Plans"}\n'
        '  ]\n'
        '}\n'
        'Verdict must be one of: "pass" (looks good), "warn" (minor concerns), '
        '"fail" (significant misalignment).\n'
        'corrections is an empty list [] if nothing needs changing.'
    )


def verify_with_llm(
    top_pairs: Sequence[dict],
    meeting_data: dict,
    tagged_bullets: Sequence[dict],
    call_json: JsonCaller,
) -> VerificationResult:
    """One audit call. A failure to reach the model is a warning, never a blocker."""
    prompt = build_audit_prompt(top_pairs, meeting_data, tagged_bullets)
    try:
        result = call_json(prompt, label="verify_tagging", phase="verification")
    except Exception as exc:  # noqa: BLE001 - the audit is advisory
        return VerificationResult(
            passed=True, warnings=[f"The audit call failed ({exc}); continuing without it."]
        )

    verdict = str(result.get("verdict", "pass")).strip().lower()
    issues = list(result.get("issues", []))
    if result.get("notes"):
        log.info("MoM verifier note: %s", result["notes"])

    return VerificationResult(
        passed=verdict != "fail",
        warnings=issues if verdict == "warn" else [],
        errors=issues if verdict == "fail" else [],
        corrections=list(result.get("corrections", [])),
    )


# ── corrections ───────────────────────────────────────────────────────────────


def apply_corrections(
    corrections: Sequence[dict], tagged_bullets: List[dict], tags: Sequence[Tag]
) -> int:
    """Re-tag the bullets the audit flagged. Returns how many actually changed."""
    valid = {tag.pair for tag in tags}
    by_id = {bullet["id"]: bullet for bullet in tagged_bullets}
    applied = 0

    for fix in corrections:
        bullet_id = fix.get("id", "")
        pair = (fix.get("umbrella_tag", "").strip(), fix.get("sub_tag", "").strip())
        if not bullet_id or not all(pair):
            continue
        if pair not in valid:
            log.debug("MoM: correction ignored — %s / %s is not in the tag list", *pair)
            continue
        bullet = by_id.get(bullet_id)
        if bullet is None:
            log.debug("MoM: correction ignored — unknown bullet id %s", bullet_id)
            continue
        if (bullet["umbrella_tag"], bullet["sub_tag"]) == pair:
            continue
        bullet["umbrella_tag"], bullet["sub_tag"] = pair
        applied += 1

    return applied


# ── phase entry point ─────────────────────────────────────────────────────────


def run_checkpoint(
    tagging: TaggingResult,
    meeting_data: dict,
    *,
    tagged_dir: Path,
    priority_path: Path,
    call_json: Optional[JsonCaller] = None,
    llm_check: bool = config.VERIFIER_LLM_CHECK,
) -> TaggingResult:
    """Verify, optionally correct and re-score. Raises on a hard failure."""
    rules = verify_rules(tagging.top_pairs, tagging.tagged_bullets)
    rules.log_to(log)
    if not rules.passed:
        raise VerificationFailed(" ".join(rules.errors))

    if not (llm_check and call_json is not None):
        return tagging

    audit = verify_with_llm(
        tagging.top_pairs, meeting_data, tagging.tagged_bullets, call_json
    )
    audit.log_to(log)

    top_pairs = tagging.top_pairs
    applied = apply_corrections(audit.corrections, tagging.tagged_bullets, tagging.tags)
    if applied:
        log.info("MoM: applied %d tag correction(s); re-scoring", applied)
        top_pairs = score_priorities(tagging.tagged_bullets, tagged_dir, tagging.umbrellas)
        save_priorities(top_pairs, priority_path)

    if not audit.passed:
        raise VerificationFailed(
            " ".join(audit.errors) or "The audit judged the tagged output misaligned."
        )

    return TaggingResult(
        top_pairs=top_pairs, tagged_bullets=tagging.tagged_bullets, tags=tagging.tags
    )
