"""Phase 4 — the priority pairs become the body of the minutes.

One LLM call. What it is asked for, and what it returns, is the only thing the two
modes disagree about, so each mode owns a :class:`SummaryShape`: a prompt builder and
the keys the answer must have. Writing the document is :mod:`mom.minutes_docx`'s job.

The model writes prose; it never decides what the numbers are. Every figure it can use
is already in the evidence block built from the tagged note and deck.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

from logger import get_logger
from mom import config
from mom.llm import JsonCaller

log = get_logger(__name__)

# Party labels the model sometimes prepends despite being told not to ("Carrier: …").
_LEADING_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/]{0,38}[:\-] +(?=[A-Z])")

NOTHING_FOUND = "No material content identified."


# ── the evidence the model writes from ────────────────────────────────────────


def build_evidence_block(top_pairs: Sequence[dict], max_ppt_lines: int) -> str:
    """The tagged note bullets and deck entries, grouped by priority pair."""
    lines: List[str] = []
    for rank, pair in enumerate(top_pairs, start=1):
        lines.append(
            f"\n--- Priority {rank}: {pair['umbrella_tag']} / {pair['sub_tag']}"
            f"  (score={pair['score']}) ---"
        )
        bullets = pair.get("meeting_note_bullets", [])
        if bullets:
            lines.append("  [Meeting Note Bullets]")
            lines += [f"  ({b.get('bullet_owner', 'Marsh')}) {b['bullet']}" for b in bullets]

        entries = pair.get("ppt_entries", [])[:max_ppt_lines]
        if entries:
            lines.append("  [PPT Entries]")
            lines += [
                f"  ({e.get('slide_owner', 'Unknown')}) [{e.get('slide_title', '')}] {e.get('text', '')}"
                for e in entries
            ]
    return "\n".join(lines)


# ── prompts, one per output shape ─────────────────────────────────────────────


def build_skill_prompt(top_pairs: Sequence[dict], max_ppt_lines: int) -> str:
    """Three sections, one per umbrella tag."""
    return (
        "You are writing meeting minutes for a Marsh ICG Quarterly Business Review.\n"
        "The output is organised into THREE sections matching the umbrella tag categories:\n\n"
        "  1. strategy_and_initiatives  — tagged umbrella: 'Strategy & Initiatives'\n"
        "  2. country_product_region    — tagged umbrella: 'Country / Product / Region'\n"
        "  3. key_takeaways             — tagged umbrella: 'Key Takeaways'\n\n"
        "Rules for ALL sections:\n"
        "- Concise standalone bullet points — no sub-headings within sections.\n"
        "- Each section covers ONLY content whose umbrella tag matches that section.\n"
        "- Lead each bullet with the DISCUSSION content (meeting note = what was said).\n"
        "- Where PPT data adds a specific number, figure, or account name, weave it in.\n"
        "- Do NOT write 'the PPT shows' or 'per the meeting note'. Plain minutes style.\n"
        "- Do NOT prefix bullets with party labels like 'Carrier:', 'Marsh:', 'AIG -', etc.\n"
        "  Write each bullet as a plain standalone sentence.\n"
        "- Drop procedural or self-evident points. Combine overlapping points.\n"
        "- Do not start bullets with the carrier's name or 'Marsh' as a subject\n"
        "  (e.g. avoid 'Zurich said...', 'Marsh presented...', 'AIG indicated...').\n"
        "- Aim for 8-12 bullets per section. Total ≈ 2 pages.\n\n"
        "Section guidance:\n"
        "strategy_and_initiatives: strategic priorities, new initiatives, digital/innovation,\n"
        "  service quality and survey feedback discussed during the meeting.\n"
        "country_product_region: what is working well, challenges, growth opportunities,\n"
        "  pipeline accounts, and regional/product/country-level performance.\n"
        "key_takeaways: headline KPIs (GWP, SoW, rank, retention), outperformers and\n"
        "  underperformers, rate and pricing environment, market conditions.\n\n"
        "Input (ordered by priority score, umbrella tag shown for each):\n"
        f"{build_evidence_block(top_pairs, max_ppt_lines)}\n\n"
        "Return ONLY valid JSON with exactly these three keys:\n"
        "{\n"
        "  \"strategy_and_initiatives\": [\"bullet.\", ...],\n"
        "  \"country_product_region\":    [\"bullet.\", ...],\n"
        "  \"key_takeaways\":             [\"bullet.\", ...]\n"
        "}"
    )


def build_carrier_marsh_prompt(top_pairs: Sequence[dict], max_ppt_lines: int) -> str:
    """Two sections, split by who owns the content."""
    return (
        "You are writing meeting minutes for a Marsh ICG Quarterly Business Review.\n"
        "The output is split into \"Marsh Update\" and \"Carrier Update\".\n\n"
        "Rules for BOTH sections:\n"
        "- Concise standalone bullet points — no sub-headings within sections.\n"
        "- Cover Priority 1 pairs most thoroughly, then Priority 2, etc.\n"
        "- Lead each bullet with the DISCUSSION content (meeting note = what was said).\n"
        "- Where PPT data adds a specific number, figure, or account name, weave it in.\n"
        "- Do NOT write 'the PPT shows' or 'per the meeting note'. Plain minutes style.\n"
        "- Do NOT prefix bullets with 'Carrier:', 'Marsh:', 'Carrier Update:', or any\n"
        "  owner/source label. Write each bullet as a plain standalone sentence.\n"
        "- Drop procedural or self-evident points. Combine overlapping points.\n"
        "- Aim for 15-17 bullets per section. Total ≈ 2 pages.\n"
        "- Do not start every point with the Carrier's Name or Marsh, e.g. Zurich said,\n"
        "  AIG indicated, Marsh presented, Marsh spoke about etc.\n\n"
        "Rules for CARRIER UPDATE:\n"
        "- Only content where slide_owner = 'Carrier' or bullet_owner = 'Carrier'.\n"
        "- Focus: carrier's performance, strategy, market positioning, and updates.\n\n"
        "Rules for MARSH UPDATE:\n"
        "- Only content where slide_owner = 'Marsh' or bullet_owner = 'Marsh'.\n"
        "- Focus: Marsh's placement strategy, priorities, feedback, and initiatives.\n\n"
        "Input (ordered by priority score):\n"
        f"{build_evidence_block(top_pairs, max_ppt_lines)}\n\n"
        "Return ONLY valid JSON:\n"
        "{\"carrier_update\": [\"bullet.\", ...], \"marsh_update\": [\"bullet.\", ...]}"
    )


@dataclass(frozen=True)
class SummaryShape:
    """How one mode asks for the body, and what keys come back."""

    prompt: Callable[[Sequence[dict], int], str]
    keys: Tuple[str, ...]


SHAPES: Dict[str, SummaryShape] = {
    "skill": SummaryShape(
        build_skill_prompt,
        ("strategy_and_initiatives", "country_product_region", "key_takeaways"),
    ),
    "carrier_marsh": SummaryShape(
        build_carrier_marsh_prompt, ("carrier_update", "marsh_update")
    ),
}


# ── the call ──────────────────────────────────────────────────────────────────


def clean_bullets(bullets: Sequence) -> List[str]:
    """Drop empties and strip any party label the model prepended anyway."""
    written = [_LEADING_LABEL.sub("", b).strip() for b in bullets if b and str(b).strip()]
    return written or [NOTHING_FOUND]


def write_summary(top_pairs: Sequence[dict], shape: SummaryShape, call_json: JsonCaller) -> dict:
    """One LLM call: priority pairs in, a bullet list per section out."""
    prompt = shape.prompt(top_pairs, config.MAX_PPT_LINES_PER_TAG)
    result = call_json(prompt, label="summary_generation", phase="summary")
    return {key: clean_bullets(result.get(key, [])) for key in shape.keys}


# ── the saved record ──────────────────────────────────────────────────────────


def _body_for_json(summary: dict, mode: str, carrier_name: str) -> dict:
    """The summary as the JSON record names it — carrier_update takes the carrier's name."""
    if mode != "carrier_marsh":
        return dict(summary)
    return {
        carrier_name or "Carrier Update": summary["carrier_update"],
        "marsh_update": summary["marsh_update"],
    }


def save_summary_json(
    meeting_data: dict, summary: dict, top_pairs: Sequence[dict], mode: str, path: Path
) -> None:
    """The machine-readable twin of the DOCX, alongside it in the run directory."""
    record = {
        "meeting_metadata": {
            "client": meeting_data.get("client"),
            "subject": meeting_data.get("subject"),
            "meeting_date": meeting_data.get("meeting_date"),
            "author": meeting_data.get("author"),
        },
        "top_pairs": [
            {"umbrella_tag": p["umbrella_tag"], "sub_tag": p["sub_tag"], "score": p["score"]}
            for p in top_pairs
        ],
        **_body_for_json(summary, mode, meeting_data.get("client") or ""),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


# ── phase entry point ─────────────────────────────────────────────────────────


def run(
    *,
    meeting_data: dict,
    top_pairs: Sequence[dict],
    ppt_sections: Sequence[dict],
    mode: str,
    summary_json_path: Path,
    docx_path: Path,
    call_json: JsonCaller,
) -> Path:
    """Write the body, save the JSON record, and produce the DOCX. Returns its path."""
    from mom.minutes_docx import write_minutes

    shape = SHAPES.get(mode)
    if shape is None:
        raise ValueError(f"mode must be one of {tuple(SHAPES)}, got {mode!r}")

    summary = write_summary(top_pairs, shape, call_json)
    save_summary_json(meeting_data, summary, top_pairs, mode, summary_json_path)
    return write_minutes(
        meeting_data=meeting_data,
        summary=summary,
        top_pairs=top_pairs,
        ppt_sections=ppt_sections,
        mode=mode,
        path=docx_path,
    )
