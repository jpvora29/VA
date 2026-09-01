"""Tuning constants and the per-run directory layout.

The standalone pipeline kept every path in module globals and wrote into the folder
it was launched from, so two runs shared one ``data/`` directory and the second
overwrote the first. Here a run owns a directory (:class:`RunPaths`) that is passed
down explicitly, which is what lets two MoM runs sit side by side in one app.

Credentials are NOT here — the model client comes from ``core.llm.clients``, so MoM
uses the same Azure deployment and the same ``.env`` as the rest of the application.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ── scoring weights ───────────────────────────────────────────────────────────
MEETING_NOTE_WEIGHT = 2       # points per tagged meeting-note bullet
PPT_WEIGHT = 1                # points per tagged PPT entry
TOP_N_PAIRS = 10              # top (umbrella, sub-tag) pairs sent to the summary LLM
UMBRELLA_CAP = 3              # max sub-tags per umbrella in the top N
MAX_PPT_LINES_PER_TAG = 50    # PPT line cap per priority pair in the summary prompt

# ── verifier checkpoint ───────────────────────────────────────────────────────
VERIFIER_MIN_PAIRS = 3                # minimum priority pairs required to proceed
VERIFIER_MAX_UNCLASSIFIED_PCT = 0.30  # fail if more meeting-note bullets are unclassified
VERIFIER_WARN_UNCLASSIFIED_PCT = 0.15 # warn above this
VERIFIER_LLM_CHECK = True             # run the LLM-as-judge pass (1 extra call)

# ── tagging ───────────────────────────────────────────────────────────────────
UNCLASSIFIED = "Other / Unclassified"  # label for a bullet or entry nothing fits
TAG_PARALLELISM = 10                   # concurrent slide/section tagging calls

# The tag vocabulary. Ships with the package so a fresh checkout runs; point
# ``MOM_TAG_LIST`` at a .csv/.xlsx to use a different one.
DEFAULT_TAG_LIST = Path(__file__).resolve().parent / "data" / "tag_list.csv"


def tag_list_path() -> Path:
    """The tag list this installation tags against."""
    override = os.getenv("MOM_TAG_LIST", "").strip()
    return Path(override) if override else DEFAULT_TAG_LIST


def runs_root() -> Path:
    """Where run directories are created. ``MOM_RUNS_DIR`` overrides."""
    override = os.getenv("MOM_RUNS_DIR", "").strip()
    return Path(override) if override else Path("outputs") / "mom"


@dataclass(frozen=True)
class RunPaths:
    """Every file one pipeline run reads or writes, under one directory."""

    root: Path

    @property
    def inputs(self) -> Path:
        return self.root / "inputs"

    @property
    def raw_data(self) -> Path:
        """Phase 2 output: one JSON per slide, or per section."""
        return self.root / "data" / "raw_data"

    @property
    def tagged_data(self) -> Path:
        """Phase 3 output: the same JSONs with tags applied."""
        return self.root / "data" / "tagged_data"

    @property
    def meeting_note_json(self) -> Path:
        return self.root / "data" / "meeting_note.json"

    @property
    def priority_data(self) -> Path:
        return self.root / "data" / "priority_data.json"

    @property
    def summary_json(self) -> Path:
        return self.root / "output" / "summary_data.json"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def run_log(self) -> Path:
        return self.root / "output" / "run_log.xlsx"

    def create(self) -> "RunPaths":
        """Make every directory the pipeline writes into. Returns self, so it chains."""
        for directory in (self.inputs, self.raw_data, self.tagged_data, self.output_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def new_run_paths(run_id: str | None = None) -> RunPaths:
    """A fresh, created run directory.

    The generated id is a timestamp for the human reading the folder listing, plus a
    random suffix for the machine: Windows' clock resolution is coarse enough that two
    runs started together can land on the same microsecond, and two runs sharing one
    directory is the exact failure this layout exists to prevent.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return RunPaths(runs_root() / (run_id or f"{stamp}_{uuid.uuid4().hex[:8]}")).create()
