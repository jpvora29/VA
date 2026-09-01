"""Phase 3 — tag both sources against the ICG tag list, then score priorities.

Two sources go in: the meeting note's bullets (one LLM call for all of them) and the
deck's entries (one call per slide, or per section, fanned out across a thread pool).
Both come back carrying an ``(umbrella_tag, sub_tag)`` pair drawn from the tag list —
never a pair the model invented, which is what ``_apply_tags`` enforces.

Scoring then ranks the pairs: a meeting-note bullet is worth more than a deck entry,
because the note records what was actually discussed. The top pairs are what the
minutes get written from.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

from logger import get_logger
from mom import config
from mom.examples import FEW_SHOT_EXAMPLES
from mom.llm import JsonCaller

log = get_logger(__name__)

UNCLASSIFIED = config.UNCLASSIFIED


@dataclass(frozen=True)
class Tag:
    """One row of the tag list: a sub-tag, its umbrella, and what it means."""

    umbrella_tag: str
    sub_tag: str
    definition: str = ""

    @property
    def pair(self) -> Tuple[str, str]:
        return (self.umbrella_tag, self.sub_tag)


# ── tag list ──────────────────────────────────────────────────────────────────


def _read_rows_csv(path: Path) -> List[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [
            {(key or "").lower().strip(): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
            if any(row.values())
        ]


def _read_rows_excel(path: Path) -> List[dict]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows, headers = [], None
    for raw in sheet.iter_rows(values_only=True):
        cells = [str(cell or "").strip() for cell in raw]
        if headers is None:
            headers = [head.lower() for head in cells]
            continue
        if any(cells):
            rows.append(dict(zip(headers, cells)))
    return rows


_ROW_READERS: Dict[str, Callable[[Path], List[dict]]] = {
    ".csv": _read_rows_csv,
    ".xlsx": _read_rows_excel,
    ".xls": _read_rows_excel,
}


def load_tag_list(path: str | Path) -> List[Tag]:
    """The tag vocabulary, from a .csv or .xlsx with umbrella_tag / sub_tag columns."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Tag list not found: {path}")

    rows = _ROW_READERS.get(path.suffix.lower(), _read_rows_csv)(path)
    if not rows or not {"umbrella_tag", "sub_tag"}.issubset(rows[0]):
        found = sorted(rows[0]) if rows else []
        raise ValueError(
            f"Tag list {path.name} needs umbrella_tag and sub_tag columns. Found: {found}"
        )
    if "definition" not in rows[0]:
        log.warning("MoM: tag list has no definition column; tagging on sub-tag names only")

    return [
        Tag(row["umbrella_tag"], row["sub_tag"], row.get("definition", ""))
        for row in rows
        if row.get("umbrella_tag") and row.get("sub_tag")
    ]


def scored_umbrellas(tags: Sequence[Tag]) -> frozenset[str]:
    """Which umbrellas count towards a priority score — every one in the tag list.

    Reading this off the vocabulary rather than a hard-coded set is what lets a new
    umbrella be added by editing the CSV instead of the pipeline.
    """
    return frozenset(tag.umbrella_tag for tag in tags if tag.umbrella_tag != UNCLASSIFIED)


def build_tag_prompt_block(tags: Sequence[Tag]) -> str:
    """The tag list as the prompt shows it: ``Umbrella / Sub-tag: definition``."""
    return "\n".join(
        f"  {tag.umbrella_tag} / {tag.sub_tag}" + (f": {tag.definition}" if tag.definition else "")
        for tag in tags
    )


# ── meeting note ──────────────────────────────────────────────────────────────


def _bullet_owner(topic: str, carrier_name: str) -> str:
    """Whose update a topic belongs to. Anything not clearly the carrier's is Marsh's."""
    carrier = (carrier_name or "").lower().strip()
    return carrier_name if carrier and carrier in topic.lower().strip() else "Marsh"


def collect_bullets(meeting_data: dict, carrier_name: str) -> List[dict]:
    """Every discussion bullet, flattened and given a stable id."""
    bullets = []
    for point in meeting_data.get("discussion_points", []):
        topic = point.get("topic", "Unknown")
        owner = _bullet_owner(topic, carrier_name)
        for text in point.get("bullets", []):
            if text and text.strip():
                bullets.append({
                    "id": f"mn_{len(bullets) + 1:04d}",
                    "topic": topic,
                    "bullet": text.strip(),
                    "bullet_owner": owner,
                })
    return bullets


def build_meeting_note_prompt(bullets: Sequence[dict], tags: Sequence[Tag]) -> str:
    lines = "\n".join(f"[{b['id']}] {b['bullet']}" for b in bullets)
    return (
        "You are tagging bullet points from a QBR meeting note against a hierarchical\n"
        "business tag list for Marsh ICG.\n\n"
        "Each tag has the format: \"Umbrella / Sub-tag: definition\"\n"
        "Assign each bullet the single best-matching sub-tag.\n"
        "Use the umbrella tag only as context — do not assign umbrella tags alone.\n\n"
        "Tag list:\n"
        f"{build_tag_prompt_block(tags)}\n\n"
        f"{FEW_SHOT_EXAMPLES}\n"
        "Now tag the following bullets:\n\n"
        f"{lines}\n\n"
        "Rules:\n"
        "- Assign exactly ONE sub-tag per bullet.\n"
        "- Every id must appear exactly once in your response.\n"
        f"- If nothing fits: \"{UNCLASSIFIED}\".\n\n"
        "Return ONLY valid JSON:\n"
        '{"results": [{"id": "mn_0001", "umbrella_tag": "Key Takeaways", '
        '"sub_tag": "KPIs & Performance Headlines"}, ...]}'
    )


def tag_meeting_note(
    meeting_data: dict, tags: Sequence[Tag], carrier_name: str, call_json: JsonCaller
) -> List[dict]:
    """Tag every discussion bullet. One LLM call."""
    bullets = collect_bullets(meeting_data, carrier_name)
    if not bullets:
        log.warning("MoM: the meeting note produced no bullets to tag")
        return []

    result = call_json(
        build_meeting_note_prompt(bullets, tags), label="tag_meeting_note", phase="tagging"
    )
    assigned = _read_assignments(result, "id", tags)

    tagged = []
    for bullet in bullets:
        umbrella, sub_tag = assigned.get(bullet["id"], (UNCLASSIFIED, UNCLASSIFIED))
        if umbrella == UNCLASSIFIED:
            log.debug("MoM: bullet %s came back unclassified", bullet["id"])
        tagged.append({**bullet, "umbrella_tag": umbrella, "sub_tag": sub_tag})
    return tagged


# ── deck entries ──────────────────────────────────────────────────────────────


def compress_entry(entry: dict) -> str | None:
    """One deck entry as a single line for the prompt, or None when it carries nothing."""
    content_type = entry.get("content_type", "")
    if content_type in ("table", "table_label"):
        return None

    if content_type == "table_row" and not entry.get("text", "").strip():
        cells = entry.get("cells", [])
        parts = [f"{c['column_name']}: {c['value']}" for c in cells if c.get("column_name")]
        label = entry.get("row_label", "")
        text = (f"{label} — " if label else "") + "; ".join(parts)
    else:
        text = entry.get("text", "")

    text = (text or "").strip()
    return text if len(text) >= 3 else None


def _slide_header(data: dict) -> str:
    number = data.get("slide_number", "?")
    title = data.get("slide_title") or f"Slide {number}"
    section = data.get("section_title", "")
    slide_range = data.get("slide_range", [number, number])
    return (
        f"Slide {number}: \"{title}\"\n"
        f"Section: \"{section}\" (slides {slide_range[0]}–{slide_range[1]})\n\n"
    )


def _section_header(data: dict) -> str:
    slide_range = data.get("slide_range", [0, 0])
    return f"Section: \"{data.get('section_title', '')}\" (slides {slide_range[0]}–{slide_range[1]})\n\n"


def _slide_entry_line(entry_id: str, entry: dict, text: str) -> str:
    return f"[{entry_id}] ({entry.get('content_type', '')}, owner: {entry.get('slide_owner', '?')}) {text}"


def _section_entry_line(entry_id: str, entry: dict, text: str) -> str:
    return (
        f"[{entry_id}] (slide {entry.get('slide_number', '?')}, "
        f"{entry.get('content_type', '')}, owner: {entry.get('slide_owner', '?')}) {text}"
    )


# The unit of tagging is the only difference between the two modes: a header line and
# how much context each entry line carries.
_UNIT_PROMPTS: Dict[str, Tuple[Callable[[dict], str], Callable[[str, dict, str], str]]] = {
    "slide": (_slide_header, _slide_entry_line),
    "section": (_section_header, _section_entry_line),
}


def build_deck_prompt(data: dict, tags: Sequence[Tag], unit: str) -> str | None:
    """The tagging prompt for one slide or section — None when it has no content."""
    header, entry_line = _UNIT_PROMPTS[unit]
    lines = [
        entry_line(entry["entry_id"], entry, text)
        for entry in data.get("entries", [])
        if (text := compress_entry(entry))
    ]
    if not lines:
        return None

    return (
        "You are tagging PPT content from a Marsh ICG QBR against a hierarchical business\n"
        "tag list.\n\n"
        f"{header(data)}"
        "Each tag: \"Umbrella / Sub-tag: definition\"\n"
        "Assign each entry the single best-matching sub-tag.\n\n"
        "Tag list:\n"
        f"{build_tag_prompt_block(tags)}\n\n"
        f"{FEW_SHOT_EXAMPLES}\n"
        "Now tag the following entries:\n\n"
        + "\n".join(lines)
        + "\n\nRules:\n"
        "- Assign exactly ONE sub-tag per entry.\n"
        "- Every entry_id must appear exactly once.\n"
        f"- Whitespace-only or very short entries → \"{UNCLASSIFIED}\".\n\n"
        "Return ONLY valid JSON:\n"
        '{"results": [{"entry_id": "entry_0001", "umbrella_tag": "...", '
        '"sub_tag": "..."}, ...]}'
    )


def tag_deck_item(
    item_path: Path,
    tags: Sequence[Tag],
    call_json: JsonCaller,
    *,
    unit: str,
    tagged_dir: Path,
) -> dict:
    """Tag one slide or section file and save the tagged copy. At most one LLM call."""
    data = json.loads(Path(item_path).read_text(encoding="utf-8"))
    name = Path(item_path).name

    prompt = build_deck_prompt(data, tags, unit)
    if prompt is None:
        log.debug("MoM: %s has no taggable entries — skipping the call", name)
        return _save_tagged({**data, "tagged": True}, item_path, tagged_dir)

    try:
        label = f"tag_{unit}:{(data.get('slide_title') or data.get('section_title') or name)[:30]}"
        result = call_json(prompt, label=label, phase="tagging")
    except Exception as exc:  # noqa: BLE001 - one bad slide must not lose the run
        log.warning("MoM: tagging failed for %s (%s) — leaving it untagged", name, exc)
        return _save_tagged({**data, "tagged": False}, item_path, tagged_dir)

    _apply_tags(result, data.get("entries", []), tags)
    return _save_tagged({**data, "tagged": True}, item_path, tagged_dir)


def tag_deck(
    item_paths: Sequence[Path],
    tags: Sequence[Tag],
    call_json: JsonCaller,
    *,
    unit: str,
    tagged_dir: Path,
) -> None:
    """Tag every slide or section, bounded by ``config.TAG_PARALLELISM``."""
    if not item_paths:
        return
    log.info("MoM: tagging %d %s(s)", len(item_paths), unit)
    workers = max(1, min(len(item_paths), config.TAG_PARALLELISM))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(tag_deck_item, path, tags, call_json, unit=unit, tagged_dir=tagged_dir): path
            for path in item_paths
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("MoM: could not tag %s: %s", Path(futures[future]).name, exc)


def _save_tagged(data: dict, original_path: Path, tagged_dir: Path) -> dict:
    tagged_dir = Path(tagged_dir)
    tagged_dir.mkdir(parents=True, exist_ok=True)
    (tagged_dir / Path(original_path).name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return data


# ── applying the model's answer ───────────────────────────────────────────────


def _read_assignments(result: dict, id_key: str, tags: Sequence[Tag]) -> Dict[str, Tuple[str, str]]:
    """The model's answer, with any pair that is not in the tag list rejected."""
    valid = {tag.pair for tag in tags}
    assignments = {}
    for item in result.get("results", []):
        pair = (item.get("umbrella_tag", UNCLASSIFIED), item.get("sub_tag", UNCLASSIFIED))
        assignments[item.get(id_key, "")] = pair if pair in valid else (UNCLASSIFIED, UNCLASSIFIED)
    return assignments


def _apply_tags(result: dict, entries: List[dict], tags: Sequence[Tag]) -> None:
    """Write the tags onto the entry dicts in place."""
    assignments = _read_assignments(result, "entry_id", tags)
    for entry in entries:
        umbrella, sub_tag = assignments.get(entry["entry_id"], (UNCLASSIFIED, UNCLASSIFIED))
        if entry["entry_id"] not in assignments:
            log.debug("MoM: entry %s missing from the response", entry["entry_id"])
        entry["umbrella_tag"], entry["sub_tag"] = umbrella, sub_tag


# ── scoring ───────────────────────────────────────────────────────────────────


def _blank_score() -> dict:
    return {
        "score": 0,
        "meeting_note_count": 0,
        "ppt_count": 0,
        "meeting_note_bullets": [],
        "ppt_entries": [],
    }


def _iter_tagged_entries(tagged_dir: Path) -> Iterable[dict]:
    """Every tagged deck entry on disk, skipping files that will not parse."""
    for path in sorted(Path(tagged_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("MoM: could not read tagged file %s: %s", path.name, exc)
            continue
        yield from data.get("entries", [])


def score_priorities(
    tagged_bullets: Sequence[dict], tagged_dir: Path, umbrellas: frozenset[str]
) -> List[dict]:
    """Rank ``(umbrella, sub-tag)`` pairs by weighted evidence, capped per umbrella."""
    scores: Dict[Tuple[str, str], dict] = defaultdict(_blank_score)

    def countable(item: dict) -> Tuple[str, str] | None:
        umbrella = item.get("umbrella_tag", UNCLASSIFIED)
        if umbrella not in umbrellas or umbrella == UNCLASSIFIED:
            return None
        return (umbrella, item.get("sub_tag", UNCLASSIFIED))

    for bullet in tagged_bullets:
        key = countable(bullet)
        if key is None:
            continue
        scores[key]["score"] += config.MEETING_NOTE_WEIGHT
        scores[key]["meeting_note_count"] += 1
        scores[key]["meeting_note_bullets"].append({
            "bullet": bullet["bullet"],
            "topic": bullet["topic"],
            "bullet_owner": bullet["bullet_owner"],
        })

    for entry in _iter_tagged_entries(tagged_dir):
        key = countable(entry)
        if key is None:
            continue
        scores[key]["score"] += config.PPT_WEIGHT
        scores[key]["ppt_count"] += 1
        text = entry.get("text", "").strip()
        if len(text) >= 3:
            scores[key]["ppt_entries"].append({
                "text": text,
                "slide_owner": entry.get("slide_owner", "Unknown"),
                "slide_title": entry.get("slide_title", ""),
            })

    return _select_top_pairs(scores)


def _select_top_pairs(scores: Dict[Tuple[str, str], dict]) -> List[dict]:
    """The top N pairs by score, with no umbrella allowed to fill the list."""
    ranked = sorted(scores.items(), key=lambda item: item[1]["score"], reverse=True)
    per_umbrella: Dict[str, int] = defaultdict(int)
    top_pairs: List[dict] = []

    for (umbrella, sub_tag), data in ranked:
        capped = per_umbrella[umbrella] >= config.UMBRELLA_CAP
        if capped or len(top_pairs) >= config.TOP_N_PAIRS:
            log.debug("MoM: %s / %s not selected (score=%s)", umbrella, sub_tag, data["score"])
            continue
        per_umbrella[umbrella] += 1
        top_pairs.append({
            "umbrella_tag": umbrella,
            "sub_tag": sub_tag,
            "score": data["score"],
            "meeting_note_count": data["meeting_note_count"],
            "ppt_count": data["ppt_count"],
            "meeting_note_bullets": data["meeting_note_bullets"],
            "ppt_entries": data["ppt_entries"][: config.MAX_PPT_LINES_PER_TAG],
        })
    return top_pairs


def save_priorities(top_pairs: Sequence[dict], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(list(top_pairs), indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── phase entry point ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaggingResult:
    """What Phase 3 hands to the checkpoint and the summariser."""

    top_pairs: List[dict]
    tagged_bullets: List[dict]
    tags: List[Tag]

    @property
    def umbrellas(self) -> frozenset[str]:
        return scored_umbrellas(self.tags)


def run(
    *,
    meeting_data: dict,
    item_paths: Sequence[Path],
    tag_list_path: Path,
    carrier_name: str,
    tagged_dir: Path,
    output_path: Path,
    unit: str,
    call_json: JsonCaller,
) -> TaggingResult:
    """Load the vocabulary, tag both sources, score, and save the priority data."""
    tags = load_tag_list(tag_list_path)
    log.info("MoM: loaded %d sub-tags from %s", len(tags), Path(tag_list_path).name)

    tagged_bullets = tag_meeting_note(meeting_data, tags, carrier_name, call_json)
    log.info("MoM: tagged %d meeting-note bullet(s)", len(tagged_bullets))

    tag_deck(item_paths, tags, call_json, unit=unit, tagged_dir=tagged_dir)

    top_pairs = score_priorities(tagged_bullets, tagged_dir, scored_umbrellas(tags))
    save_priorities(top_pairs, output_path)
    log.info("MoM: %d priority pair(s) selected", len(top_pairs))

    return TaggingResult(top_pairs=top_pairs, tagged_bullets=tagged_bullets, tags=list(tags))
