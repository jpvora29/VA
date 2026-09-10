"""Recap's own settings: the lookup tables, the tuning knobs, and a run's directory.

**Credentials are not here.** The standalone app carried its own Azure endpoint, key
and deployment names; in the merged application the model client comes from
``core.llm.clients``, so Recap reads the same ``.env`` as Studio, the Chatbot and MoM
and there is one place a deployment is configured. See :mod:`recap.llm.llm_client`.

What remains is the two things that ARE Recap's own:

    lookup tables   the canonical carrier / LoB / country / region / segment labels an
                    enrichment prompt asks the model to snap to, plus the standing
                    Marsh + ICG context block. Edited in ``assets/config.yaml``.
    tuning          concurrency, retries, thresholds — read from the environment so a
                    slow tenant can be throttled without a code change.

A run owns a directory (:class:`RunPaths`), the same shape :mod:`mom.config` uses and
for the same reason: two runs writing into one ``outputs/`` folder overwrote each other.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import yaml

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
        """Canonical LoB labels for metadata matching."""
        return _ASSET_CONFIG.get("lines_of_business", [])

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
        """Canonical ICG client segment labels for metadata matching."""
        return _ASSET_CONFIG.get("segments", [])

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
