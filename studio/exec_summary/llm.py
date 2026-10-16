"""The model adapter and the stage cache — the only module that talks to an LLM.

Model routing is configuration (design Section 22, "LLM selection and budgets"):

    EXEC_SUMMARY_DEPLOYMENT   e.g. gpt-5.4-mini   (falls back to the balanced tier's)
    EXEC_SUMMARY_EFFORT       e.g. low            (set it for a reasoning model: a
                                                   reasoning model rejects a temperature)
    EXEC_SUMMARY_VERBOSITY    optional            (low | medium | high)

Structured output uses OpenAI strict JSON-schema mode, so the endpoint itself refuses a
response that does not match :class:`StageOutput`. The answer is cached on disk by
everything that could change it — prompt version, schema version, rule version,
deployment, effort and the exact messages — so a re-run of the same selection costs no
model calls and returns the same deck.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from logger import get_logger
from studio.exec_summary.prompts import PROMPT_VERSION
from studio.exec_summary.schemas import SCHEMA_VERSION, StageOutput

logger = get_logger(__name__)

_OFF = {"off", "0", "false", "no", "none"}


class StageModel(Protocol):
    """Anything that can answer one stage call with a :class:`StageOutput` (or ``None``)."""

    label: str

    def complete(self, stage: str, system: str, user: str) -> Optional[StageOutput]:
        ...


@dataclass(frozen=True)
class NoModel:
    """AI off or unavailable — every stage takes its deterministic fallback."""

    label: str = "none"

    def complete(self, stage: str, system: str, user: str) -> Optional[StageOutput]:
        return None


def exec_tier_config():
    """The balanced tier, with the executive summary's own deployment/effort on top."""
    from dataclasses import replace

    from core.llm.clients import resolve_tier

    base = resolve_tier("balanced")
    deployment = (os.getenv("EXEC_SUMMARY_DEPLOYMENT") or "").strip() or base.deployment
    effort = (os.getenv("EXEC_SUMMARY_EFFORT") or "").strip().lower()
    verbosity = (os.getenv("EXEC_SUMMARY_VERBOSITY") or "").strip().lower() or None
    if effort in _OFF:
        return replace(base, deployment=deployment)
    return replace(base, deployment=deployment, effort=effort, verbosity=verbosity,
                   temperature=None)


@dataclass(frozen=True)
class AzureStageModel:
    """gpt-5.4-mini (or whatever the tier names) through LangChain, strict JSON schema."""

    config: object
    label: str = ""

    def complete(self, stage: str, system: str, user: str) -> Optional[StageOutput]:
        from langchain_core.messages import HumanMessage, SystemMessage

        from core.llm.clients import client_for
        from studio import telemetry

        started = time.perf_counter()
        status, failure, tokens = "ok", "", (0, 0)
        try:
            runnable = client_for(self.config).with_structured_output(
                StageOutput, method="json_schema", strict=True, include_raw=True)
            out = runnable.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            tokens = telemetry.token_counts(out.get("raw"))
            parsed = out.get("parsed")
            if parsed is None:
                status, failure = "empty", str(out.get("parsing_error") or "no parsed output")
            return parsed
        except Exception as exc:  # noqa: BLE001 — a failed call takes the fallback
            status, failure = "error", telemetry.classify_failure(exc)
            logger.warning("exec_summary %s call failed: %s", stage, exc)
            return None
        finally:
            telemetry.record(telemetry.ModelCall(
                node=f"exec_summary.{stage}", phase="exec_summary", tier="exec_summary",
                deployment=str(getattr(self.config, "deployment", "") or ""),
                seconds=time.perf_counter() - started, status=status,
                input_tokens=tokens[0], output_tokens=tokens[1], failure=failure))


def make_stage_model() -> StageModel:
    """The real model when AI is allowed and configured, else :class:`NoModel`."""
    from studio.ai.client import llm_available

    if not llm_available():
        return NoModel()
    config = exec_tier_config()
    effort = getattr(config, "effort", None) or "classic"
    return AzureStageModel(config=config, label=f"{config.deployment}:{effort}")


# ── the stage cache ──────────────────────────────────────────────────────────


def _cache_enabled() -> bool:
    return (os.getenv("STUDIO_COMMENTARY_CACHE", "") or "").strip().lower() not in _OFF


def _cache_dir() -> Path:
    from core.local_paths import local_data_dir

    return local_data_dir() / "cache" / "exec_summary"


def cache_key(model_label: str, rule_version: str, system: str, user: str) -> str:
    raw = "\x1f".join([PROMPT_VERSION, SCHEMA_VERSION, rule_version, model_label, system, user])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cached(key: str) -> Optional[StageOutput]:
    if not _cache_enabled():
        return None
    path = _cache_dir() / f"{key}.json"
    try:
        return StageOutput.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:  # noqa: BLE001 — a bad entry is a miss
        return None


def store(key: str, output: StageOutput) -> None:
    if not _cache_enabled():
        return
    try:
        directory = _cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{key}.json").write_text(output.model_dump_json(), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — an unwritable cache costs nothing
        logger.debug("exec_summary cache write failed: %s", exc)
