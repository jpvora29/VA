"""
main.py

Command-line entry point for the Recap engine.

    python -m recap.main run --file decks/client_q2_2026.pptx --client "Acme Corp" ...
    python -m recap.main run-batch --manifest decks/manifest.json
    python -m recap.main query --store outputs/recap/<run>/data/insight_store.json
    python -m recap.main trace --store <store.json> --insight-id <id>

`run` is the same call the Recap workspace makes — :func:`recap.run.run_recap_pipeline`
— so the deck this prints the path of is the deck the app would produce. Several
`--file` arguments make ONE recap covering all of them; `run-batch` is the other
shape, one run (and one recap) per manifest entry.

Credentials come from the application's `.env` through ``core.llm.clients``; there is
nothing to configure here.

Manifest JSON format:
    [
      {
        "file_path": "decks/q1_2026.pptx",
        "client_name": "Acme Corp",
        "meeting_date": "2026-01-15",
        "quarter": "Q1",
        "year": "2026"
      }
    ]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Sequence

from recap.config import RunPaths, new_run_paths, settings
from recap.metadata import DeckMetadata, read_cover
from recap.progress import label_for
from recap.run import RecapRequest, RecapResult, run_recap_pipeline
from recap.store.insight_store import InsightStore


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _report(stage: str, message: str = "") -> None:
    """Progress on the console: the same stage ids the workspace's bar reads."""
    print(f"  [{stage:<12}] {message or label_for(stage)}")


# ---------------------------------------------------------------------------
# Building a request
# ---------------------------------------------------------------------------

def _metadata_from(args: argparse.Namespace, decks: Sequence[Path]) -> DeckMetadata:
    """What was typed, falling back to what the first deck's cover slide says."""
    detected = read_cover(decks[0].read_bytes()) if decks else DeckMetadata()
    return DeckMetadata(
        client_name=args.client or detected.client_name,
        company_name=args.company or detected.company_name,
        period_label=args.period or detected.period_label,
        quarter=args.quarter or detected.quarter,
        year=str(args.year or detected.year or ""),
        meeting_date=args.date or detected.meeting_date,
    )


def _run_paths(output: str | None) -> RunPaths:
    return RunPaths(Path(output)).create() if output else new_run_paths()


def _resolve_decks(paths: Sequence[str]) -> List[Path]:
    decks = [Path(p) for p in paths]
    missing = [str(d) for d in decks if not d.is_file()]
    if missing:
        print(f"ERROR: no such deck: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    return decks


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> None:
    """One recap over one or more decks."""
    decks = _resolve_decks(args.file)
    request = RecapRequest(
        deck_paths=tuple(decks),
        metadata=_metadata_from(args, decks),
        paths=_run_paths(args.output),
        template_path=Path(args.template) if args.template else None,
        glossary_path=Path(args.glossary) if args.glossary else None,
    )
    _print_result(run_recap_pipeline(request, report=_report))


def cmd_run_batch(args: argparse.Namespace) -> None:
    """One run — and one recap — per manifest entry."""
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in entries:
        decks = _resolve_decks([entry["file_path"]])
        request = RecapRequest(
            deck_paths=tuple(decks),
            metadata=DeckMetadata.from_store(
                {**read_cover(decks[0].read_bytes()).as_store(),
                 **{k: str(v) for k, v in entry.items() if k != "file_path" and v}}
            ),
            paths=new_run_paths(),
            glossary_path=Path(args.glossary) if args.glossary else None,
        )
        print(f"\n{'=' * 60}\n{decks[0].name}")
        _print_result(run_recap_pipeline(request, report=_report))


def cmd_query(args: argparse.Namespace) -> None:
    """Query a saved insight store."""
    store = InsightStore.load(args.store)
    print(f"Loaded {store.count} insights from {args.store}\n")

    results = store.query(
        umbrella=args.umbrella,
        lob=args.lob,
        region=args.region,
        performance_direction=args.direction,
        is_action_item=True if args.action_items_only else None,
        urgency=args.urgency,
        min_confidence=float(args.min_confidence) if args.min_confidence else None,
    )

    print(f"Matched {len(results)} insights:\n")
    for insight in results:
        flag = (
            f"[ACTION:{insight.action_item.urgency.value.upper()}]"
            if insight.action_item.is_action_item
            else ""
        )
        print(
            f"  [{insight.content_unit_id}] Slide {insight.slide_number} "
            f"| {', '.join(insight.umbrella_labels) or 'unclassified'} {flag}\n"
            f"  {insight.content[:120]}\n"
        )


def cmd_trace(args: argparse.Namespace) -> None:
    """Print the full provenance trace for a single insight."""
    store = InsightStore.load(args.store)
    print(json.dumps(store.trace(args.insight_id), indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def _print_result(result: RecapResult) -> None:
    separator = "=" * 60
    print(f"\n{separator}")
    print(f"RECAP  {result.client or result.deck_id}  |  {result.period}")
    print(separator)
    for title in result.takeaway_titles:
        print(f"• {title}")
    print(
        f"\n{result.insight_count} insight(s) read · "
        f"{result.action_item_count} action item(s) · "
        f"confidence {result.confidence:.2f}"
    )
    print(f"\nDeck           -> {result.pptx_path}")
    print(f"Recap JSON     -> {result.recap_json_path}")
    print(f"Insight store  -> {result.insight_store_path}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recap",
        description="Turn business review decks into an auditable recap",
    )
    parser.add_argument(
        "--log-level", default=settings.log_level,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # run -----------------------------------------------------------------
    run_p = sub.add_parser("run", help="Recap one or more decks together")
    run_p.add_argument("--file", required=True, action="append",
                       help="Path to a .pptx file (repeat for several decks)")
    run_p.add_argument("--client", default=None, help="Client name")
    run_p.add_argument("--company", default=None, help="Company name")
    run_p.add_argument("--date", default=None, help="Meeting date (ISO-8601)")
    run_p.add_argument("--quarter", default=None, help="Quarter e.g. Q2")
    run_p.add_argument("--year", default=None, help="Year e.g. 2026")
    run_p.add_argument("--period", default=None, help="Period label")
    run_p.add_argument("--glossary", default=None, help="Path to glossary JSON/YAML")
    run_p.add_argument("--output", default=None,
                       help="Run directory (default: a fresh one under outputs/recap)")
    run_p.add_argument("--template", default=None,
                       help="Path to QBR Recap Template.pptx (overrides assets default)")

    # run-batch -----------------------------------------------------------
    batch_p = sub.add_parser("run-batch", help="One recap per manifest entry")
    batch_p.add_argument("--manifest", required=True, help="Path to manifest JSON")
    batch_p.add_argument("--glossary", default=None)

    # query ---------------------------------------------------------------
    query_p = sub.add_parser("query", help="Query a saved insight store")
    query_p.add_argument("--store", required=True)
    query_p.add_argument("--umbrella", default=None)
    query_p.add_argument("--lob", default=None)
    query_p.add_argument("--region", default=None)
    query_p.add_argument("--direction", default=None)
    query_p.add_argument("--urgency", default=None)
    query_p.add_argument("--min-confidence", default=None, dest="min_confidence")
    query_p.add_argument("--action-items-only", action="store_true",
                         dest="action_items_only")

    # trace ---------------------------------------------------------------
    trace_p = sub.add_parser("trace", help="Trace provenance for a specific insight")
    trace_p.add_argument("--store", required=True)
    trace_p.add_argument("--insight-id", required=True, dest="insight_id")

    return parser


COMMANDS = {
    "run": cmd_run,
    "run-batch": cmd_run_batch,
    "query": cmd_query,
    "trace": cmd_trace,
}


def main() -> None:
    args = _build_parser().parse_args()
    _configure_logging(args.log_level)
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
