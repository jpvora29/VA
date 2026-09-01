"""The MoM pipeline, readable top to bottom.

    note + deck  ->  meeting data  ->  deck entries  ->  tagged & scored
                 ->  verified      ->  minutes (.docx)

Each step is one named function in its own module; this file is the order they run in
and the data that moves between them. The mode (:mod:`mom.modes`) changes three
arguments, never the sequence.

Every dependency that touches the outside world — the model, the progress sink — is
passed in, so the whole pipeline runs in a test with a stub caller and no credentials.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from logger import get_logger
from mom import config, deck, notes, summariser, tagger, verifier
from mom.llm import JsonCaller, make_json_caller
from mom.modes import MoMMode, resolve_mode
from mom.progress import Reporter, silent
from mom.run_log import RunLog
from mom.run_log_excel import write_run_log

log = get_logger(__name__)


@dataclass(frozen=True)
class MoMRequest:
    """What the user asked for: two files, a mode, and where to work."""

    note_path: Path
    deck_path: Path
    mode: MoMMode
    paths: config.RunPaths


@dataclass(frozen=True)
class MoMResult:
    """What the run produced."""

    docx_path: Path
    summary_json_path: Path
    run_log_path: Path
    client: str
    priority_pairs: List[dict]
    llm_calls: int
    total_tokens: int


# ── steps ─────────────────────────────────────────────────────────────────────


def read_meeting_data(request: MoMRequest, call_json: JsonCaller) -> dict:
    """The note parsed, then overridden by whatever the deck states authoritatively.

    The deck's cover and agenda slides are the source of truth for who the client is,
    when the meeting was and who attended — the note only guesses at those.
    """
    meeting_data = notes.run(request.note_path, request.paths.meeting_note_json, call_json)

    from_deck = deck.extract_ppt_metadata(str(request.deck_path))
    for key in ("client", "subject", "meeting_date", "attendees"):
        if from_deck.get(key):
            meeting_data[key] = from_deck[key]
    meeting_data["ppt_agenda_items"] = from_deck.get("agenda_items", [])

    # ``notes.run`` already saved the parsed note; re-save so the file on disk is the
    # enriched record every later phase actually works from.
    request.paths.meeting_note_json.write_text(
        json.dumps(meeting_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return meeting_data


def read_deck(request: MoMRequest, meeting_data: dict) -> List[dict]:
    """Every slide (or section) of the deck as a JSON file. Rule-based, no LLM."""
    topics = [p["topic"] for p in meeting_data.get("discussion_points", []) if p.get("topic")]
    return deck.run(
        str(request.deck_path),
        carrier_name=meeting_data.get("client", ""),
        meeting_topics=topics,
        output_dir=str(request.paths.raw_data),
        granularity=request.mode.granularity,
    )


def sections_from_manifest(manifest: Sequence[dict], granularity: str) -> List[dict]:
    """The deck's sections, whichever granularity the manifest is in.

    A section manifest already IS the section list; a slide manifest names its section
    on every row, so consecutive rows collapse into one entry with a slide range.
    """
    if granularity == "section":
        return [
            {"section_number": row["section_number"],
             "section_title": row["section_title"],
             "slide_range": list(row["slide_range"])}
            for row in manifest
        ]

    sections: List[dict] = []
    by_number: dict[int, dict] = {}
    for row in sorted(manifest, key=lambda r: (r["section_number"], r["slide_number"])):
        number = row["section_number"]
        if number not in by_number:
            by_number[number] = {
                "section_number": number,
                "section_title": row["section_title"],
                "slide_range": [row["slide_number"], row["slide_number"]],
            }
            sections.append(by_number[number])
        else:
            by_number[number]["slide_range"][1] = row["slide_number"]
    return sections


def tag_and_score(
    request: MoMRequest, meeting_data: dict, manifest: Sequence[dict], call_json: JsonCaller
) -> tagger.TaggingResult:
    """Both sources tagged against the tag list, and the priority pairs scored."""
    return tagger.run(
        meeting_data=meeting_data,
        item_paths=[Path(row["file"]) for row in manifest],
        tag_list_path=config.tag_list_path(),
        carrier_name=meeting_data.get("client", ""),
        tagged_dir=request.paths.tagged_data,
        output_path=request.paths.priority_data,
        unit=request.mode.granularity,
        call_json=call_json,
    )


def minutes_filename(deck_path: Path) -> str:
    """The document is named after the deck it summarises."""
    return f"{Path(deck_path).stem}_Meeting_Notes.docx"


def write_minutes(
    request: MoMRequest,
    meeting_data: dict,
    tagging: tagger.TaggingResult,
    sections: Sequence[dict],
    call_json: JsonCaller,
) -> Path:
    """The body written and the DOCX saved."""
    return summariser.run(
        meeting_data=meeting_data,
        top_pairs=tagging.top_pairs,
        ppt_sections=sections,
        mode=request.mode.summary,
        summary_json_path=request.paths.summary_json,
        docx_path=request.paths.output_dir / minutes_filename(request.deck_path),
        call_json=call_json,
    )


# ── the pipeline ──────────────────────────────────────────────────────────────


def run_mom_pipeline(
    request: MoMRequest,
    *,
    call_json: Optional[JsonCaller] = None,
    report: Reporter = silent,
    run_log: Optional[RunLog] = None,
) -> MoMResult:
    """Two uploaded files in, one minutes document out."""
    run_log = run_log or RunLog(run_id=request.paths.root.name)
    call_json = call_json or make_json_caller(run_log)
    request.paths.create()

    report("notes", f"Reading {request.note_path.name}")
    run_log.start_phase("notes")
    meeting_data = read_meeting_data(request, call_json)
    run_log.end_phase("notes")
    client = meeting_data.get("client") or "Unknown client"
    run_log.run_id = f"{datetime.now():%Y%m%d_%H%M%S}_{client.replace(' ', '_')[:20]}"

    report("deck", f"Reading {request.deck_path.name}")
    run_log.start_phase("deck")
    manifest = read_deck(request, meeting_data)
    sections = sections_from_manifest(manifest, request.mode.granularity)
    run_log.end_phase("deck")

    report("tagging", f"Tagging {len(manifest)} {request.mode.granularity}(s) and the note")
    run_log.start_phase("tagging")
    tagging = tag_and_score(request, meeting_data, manifest, call_json)
    run_log.end_phase("tagging")

    report("verification", f"Checking {len(tagging.top_pairs)} priority topic(s)")
    run_log.start_phase("verification")
    tagging = verifier.run_checkpoint(
        tagging,
        meeting_data,
        tagged_dir=request.paths.tagged_data,
        priority_path=request.paths.priority_data,
        call_json=call_json,
    )
    run_log.end_phase("verification")

    report("summary", "Writing the minutes")
    run_log.start_phase("summary")
    docx_path = write_minutes(request, meeting_data, tagging, sections, call_json)
    run_log.end_phase("summary")

    summary = run_log.summary()
    log.info(
        "MoM: %s complete — %d LLM call(s), %d token(s)",
        docx_path.name, summary.total_llm_calls, summary.total_tokens,
    )
    return MoMResult(
        docx_path=docx_path,
        summary_json_path=request.paths.summary_json,
        run_log_path=write_run_log(summary, request.paths.run_log),
        client=client,
        priority_pairs=tagging.top_pairs,
        llm_calls=summary.total_llm_calls,
        total_tokens=summary.total_tokens,
    )


def build_request(
    note_path: Path, deck_path: Path, mode_id: str, paths: Optional[config.RunPaths] = None
) -> MoMRequest:
    """A request from what the workspace holds: two saved files and the chosen mode."""
    return MoMRequest(
        note_path=Path(note_path),
        deck_path=Path(deck_path),
        mode=resolve_mode(mode_id),
        paths=paths or config.new_run_paths(),
    )
