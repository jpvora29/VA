"""Recap's own settings: the lookup tables, the tuning knobs, and a run's directory.

**Credentials are not here.** The standalone app carried its own Azure endpoint, key
and deployment names; in the merged application the model client comes from
``core.llm.clients``, so Recap reads the same ``.env`` as Studio, the Chatbot and MoM
and there is one place a deployment is configured. See :mod:`recap.llm.llm_client`.

What remains is the three things that ARE Recap's own:

    lookup tables   the canonical carrier / LoB / country / region / segment labels an
                    enrichment prompt asks the model to snap to, plus the standing
                    Marsh + ICG context block. Edited in ``assets/config.yaml``.
    tuning          concurrency, retries, thresholds — read from the environment so a
                    slow tenant can be throttled without a code change.
    per-stage LLM   each model call is tagged with a stage name, and each stage's token
                    budget and reasoning effort can be set on its own. The variables are
                    ``RECAP_``-prefixed so they never collide with the application-wide
                    ``<TIER>_EFFORT`` knobs in :mod:`core.llm.clients`:

                        RECAP_REASONING_EFFORT            every recap stage
                        RECAP_REASONING_EFFORT_<STAGE>    one stage, wins over the above
                        RECAP_TOKENS_<STAGE>              one stage's output budget

                    With no RECAP_ effort set, a stage runs exactly as its tier is
                    configured — so an unset variable changes nothing.

A run owns a directory (:class:`RunPaths`), the same shape :mod:`mom.config` uses and
for the same reason: two runs writing into one ``outputs/`` folder overwrote each other.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv

# The per-stage settings below are read from the environment at call time, and a recap
# stage can ask for them before anything has imported ``core.llm.clients`` (which is
# what loads ``.env`` for the rest of the app). Loading here too is a no-op when it has
# already run, and never overrides a variable exported in the real environment.
load_dotenv()

ASSETS = Path(__file__).resolve().parent / "assets"


# ---------------------------------------------------------------------------
# Lookup tables loaded from assets/config.yaml
# ---------------------------------------------------------------------------

def _load_asset_config() -> dict:
    """Load assets/config.yaml relative to this file."""
    path = ASSETS / "config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


_ASSET_CONFIG: dict = _load_asset_config()


# ---------------------------------------------------------------------------
# Canonical / alias helpers for lookup-table entries
# ---------------------------------------------------------------------------
#
# Lookup lists such as lines_of_business and segments may be defined either
# as a flat list of strings (legacy shape) or as a list of
# {canonical: str, aliases: [str, ...]} dicts (current shape). These helpers
# normalise both shapes so the rest of the code only deals with canonical
# names and a single alias -> canonical index.

def _entry_canonical(entry) -> str:
    """Return the canonical display name for one lookup-list entry."""
    if isinstance(entry, dict):
        return str(entry.get("canonical", "")).strip()
    return str(entry).strip()


def _entry_aliases(entry) -> List[str]:
    """Return the alias list for one lookup-list entry (empty if none)."""
    if isinstance(entry, dict):
        return [str(a).strip() for a in (entry.get("aliases") or []) if str(a).strip()]
    return []


def _build_alias_index(entries: list) -> dict:
    """
    Build a case-insensitive {alias_or_canonical_lower: canonical} index
    from a lookup-list. Both the canonical name and every alias map to the
    canonical name, so callers can resolve any known variant in one lookup.
    """
    index: dict = {}
    for entry in entries:
        canonical = _entry_canonical(entry)
        if not canonical:
            continue
        index[canonical.lower()] = canonical
        for alias in _entry_aliases(entry):
            index[alias.lower()] = canonical
    return index


# ---------------------------------------------------------------------------
# Per-stage token budgets
# ---------------------------------------------------------------------------
#
# Every model call in the pipeline is tagged with a short stage name. Classification
# stages are kept lean (short, templated JSON); enrichment and recap synthesis get more
# headroom because they compose free text and — on a reasoning deployment — internal
# reasoning tokens are drawn from this same budget before any visible output.

_STAGE_TOKEN_DEFAULTS = {
    # Classification — short boolean/JSON verdicts
    "umbrella_classification": 512,
    "subcategory_classification": 512,
    "action_item_classification": 512,
    # Enrichment — structured metadata extraction
    "enrichment_context": 600,
    "enrichment_kpi": 1024,
    # Recap generation — free-text synthesis, largest budgets
    "recap_takeaway": 2000,
    "recap_dedup": 5000,
    "recap_force_compress": 3000,
    "recap_exec_summary": 1000,
    "recap_overlap": 5000,
    "recap_fact_check_slide1": 5000,
    "recap_fact_check_slide2": 5000,
    "recap_action_ranker": 1500,
    "recap_country_summary_per_sentence": 500,
}

#: The budget for a stage name that is not in the table above.
_FALLBACK_TOKEN_BUDGET = 1024

#: Values that leave a stage's effort to its tier, the same words core.llm.clients uses.
_NO_EFFORT = {"", "none", "off"}


def _recap_env(name: str) -> str:
    return (os.environ.get(f"RECAP_{name}") or "").strip()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings:
    """
    Runtime settings.

    Lookup tables: loaded from assets/config.yaml (edit that file, not here).
    Tuning:        read from environment variables with safe defaults.
    """

    # ----------------------------------------------------------------
    # Lookup tables (from assets/config.yaml)
    # ----------------------------------------------------------------

    @property
    def carriers(self) -> List[str]:
        """Canonical carrier names for metadata matching."""
        return _ASSET_CONFIG.get("carriers", [])

    @property
    def lines_of_business(self) -> List[str]:
        """
        Canonical LoB labels for metadata matching.

        Supports both the {canonical, aliases} config shape and the legacy
        flat list of strings, so older config.yaml files keep working.
        """
        return [_entry_canonical(e) for e in _ASSET_CONFIG.get("lines_of_business", [])]

    @property
    def lob_alias_index(self) -> dict:
        """
        Case-insensitive lookup mapping every alias AND canonical name to
        its canonical LoB name, e.g. {"d&o": "Directors & Officers (D&O)"}.
        Used to canonicalize free-text LoB values returned by the LLM.
        """
        return _build_alias_index(_ASSET_CONFIG.get("lines_of_business", []))

    @property
    def countries(self) -> List[str]:
        """Canonical country names for metadata matching."""
        return _ASSET_CONFIG.get("countries", [])

    @property
    def regions(self) -> List[str]:
        """Canonical region labels for metadata matching."""
        return _ASSET_CONFIG.get("regions", [])

    @property
    def segments(self) -> List[str]:
        """
        Canonical ICG client segment labels for metadata matching.
        Supports both the {canonical, aliases} shape and the legacy flat list.
        """
        return [_entry_canonical(e) for e in _ASSET_CONFIG.get("segments", [])]

    @property
    def segment_alias_index(self) -> dict:
        """
        Case-insensitive lookup mapping every alias AND canonical name to
        its canonical segment name. Used to canonicalize free-text segment
        values returned by the LLM.
        """
        return _build_alias_index(_ASSET_CONFIG.get("segments", []))

    def lookup_block(self) -> str:
        """
        Return a compact text block of all lookup tables for injection
        into LLM enrichment prompts so the model uses canonical labels.
        """
        lines = []
        if self.carriers:
            lines.append("Known carriers: " + ", ".join(self.carriers))
        if self.lines_of_business:
            lines.append("Known lines of business: " + ", ".join(self.lines_of_business))
        if self.countries:
            lines.append("Known countries: " + ", ".join(self.countries))
        if self.regions:
            lines.append("Known regions: " + ", ".join(self.regions))
        if self.segments:
            lines.append("Known segments: " + ", ".join(self.segments))
        return "\n".join(lines)

    def context_block(self) -> str:
        """
        Return a formatted block describing Marsh and the ICG team for
        injection into LLM system prompts as standing background context.
        Loaded from the 'context' section of assets/config.yaml.
        Returns an empty string if the section is absent.
        """
        ctx = _ASSET_CONFIG.get("context", {})
        if not ctx:
            return ""
        parts = []
        marsh = (ctx.get("marsh") or "").strip()
        icg = (ctx.get("icg") or "").strip()
        if marsh:
            parts.append(f"About Marsh:\n{marsh}")
        if icg:
            parts.append(f"About the ICG team:\n{icg}")
        return "\n\n".join(parts)

    # ----------------------------------------------------------------
    # Per-stage token budgets & reasoning effort
    # ----------------------------------------------------------------

    @property
    def default_reasoning_effort(self) -> Optional[str]:
        """
        The reasoning effort ("minimal" | "low" | "medium" | "high") for every
        recap stage, from RECAP_REASONING_EFFORT.

        None when unset (or "none"/"off"): each stage then runs as its tier is
        configured by core.llm.clients, which is exactly the behaviour before
        this setting existed.
        """
        value = _recap_env("REASONING_EFFORT").lower()
        return None if value in _NO_EFFORT else value

    def token_budget(self, stage: str) -> int:
        """
        The max_completion_tokens budget for a named pipeline stage.

        Resolution order:
          1. RECAP_TOKENS_<STAGE> env var (e.g. RECAP_TOKENS_ENRICHMENT_KPI=1500)
          2. Built-in default in _STAGE_TOKEN_DEFAULTS
          3. _FALLBACK_TOKEN_BUDGET if the stage name is unrecognised
        """
        default = _STAGE_TOKEN_DEFAULTS.get(stage, _FALLBACK_TOKEN_BUDGET)
        raw = _recap_env(f"TOKENS_{stage.upper()}")
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    def reasoning_effort_for(self, stage: str) -> Optional[str]:
        """
        The reasoning effort for a named pipeline stage.

        Resolution order:
          1. RECAP_REASONING_EFFORT_<STAGE> env var (e.g.
             RECAP_REASONING_EFFORT_SUBCATEGORY_CLASSIFICATION=low)
          2. RECAP_REASONING_EFFORT (default_reasoning_effort)
          3. None — the stage's tier decides, see recap.llm.llm_client
        """
        value = _recap_env(f"REASONING_EFFORT_{stage.upper()}").lower()
        if value and value not in _NO_EFFORT:
            return value
        return self.default_reasoning_effort

    # ----------------------------------------------------------------
    # Concurrency & rate limiting
    # ----------------------------------------------------------------

    @property
    def max_concurrent_llm_calls(self) -> int:
        return int(os.environ.get("MAX_CONCURRENT_LLM_CALLS", "10"))

    @property
    def max_concurrent_insight_classification(self) -> int:
        return int(os.environ.get("MAX_CONCURRENT_INSIGHT_CLASSIFICATION", "5"))

    # ----------------------------------------------------------------
    # Retry
    # ----------------------------------------------------------------

    @property
    def max_llm_retries(self) -> int:
        return int(os.environ.get("MAX_LLM_RETRIES", "3"))

    @property
    def retry_base_delay(self) -> float:
        return float(os.environ.get("RETRY_BASE_DELAY", "2.0"))

    # ----------------------------------------------------------------
    # Filtering
    # ----------------------------------------------------------------

    @property
    def noise_ambiguity_threshold(self) -> float:
        return float(os.environ.get("NOISE_AMBIGUITY_THRESHOLD", "0.85"))

    # ----------------------------------------------------------------
    # Paths
    # ----------------------------------------------------------------

    @property
    def default_glossary_path(self) -> Path:
        """Default glossary - the compiled assets/glossary.json."""
        return ASSETS / "glossary.json"

    @property
    def default_template_path(self) -> Path:
        """Default QBR recap PPTX template."""
        return ASSETS / "QBR Recap Template.pptx"

    # ----------------------------------------------------------------
    # Recap generation
    # ----------------------------------------------------------------

    @property
    def recap_min_confidence(self) -> float:
        return float(os.environ.get("RECAP_MIN_CONFIDENCE", "0.0"))

    @property
    def recap_max_insights_in_prompt(self) -> int:
        return int(os.environ.get("RECAP_MAX_INSIGHTS", "60"))

    # ----------------------------------------------------------------
    # Logging
    # ----------------------------------------------------------------

    @property
    def log_level(self) -> str:
        return os.environ.get("LOG_LEVEL", "INFO").upper()


# Singleton - import this everywhere
settings = Settings()


# ---------------------------------------------------------------------------
# Where one run writes
# ---------------------------------------------------------------------------

def runs_root() -> Path:
    """Where run directories are created. ``RECAP_RUNS_DIR`` overrides."""
    override = os.getenv("RECAP_RUNS_DIR", "").strip()
    return Path(override) if override else Path("outputs") / "recap"


@dataclass(frozen=True)
class RunPaths:
    """Every file one recap run reads or writes, under one directory."""

    root: Path

    @property
    def inputs(self) -> Path:
        """The decks the user uploaded, copied in so the run is self-contained."""
        return self.root / "inputs"

    @property
    def artefacts(self) -> Path:
        """The per-stage JSON the pipeline writes: extraction, units, insights."""
        return self.root / "data"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def insight_store(self) -> Path:
        return self.artefacts / "insight_store.json"

    def recap_json(self, deck_id: str) -> Path:
        return self.output_dir / f"{deck_id}_recap.json"

    def recap_pptx(self, deck_id: str) -> Path:
        return self.output_dir / f"{deck_id}_recap.pptx"

    def create(self) -> "RunPaths":
        """Make every directory the run writes into. Returns self, so it chains."""
        for directory in (self.inputs, self.artefacts, self.output_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def new_run_paths(run_id: str | None = None) -> RunPaths:
    """A fresh, created run directory.

    The id is a timestamp for the human reading the folder listing plus a random
    suffix for the machine - two runs started in the same second must not share a
    directory, which is the exact failure this layout exists to prevent.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return RunPaths(runs_root() / (run_id or f"{stamp}_{uuid.uuid4().hex[:8]}")).create()
