"""The executive summary's thresholds and caps, read once from ``rules.yaml``.

Business rules are configuration, not code (design Section 12): a threshold change is a
YAML diff, and the rule version rides on every finding so a deck says which rules wrote it.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

RULES_PATH = Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True)
class WhitespaceGates:
    material_marsh_premium: float
    min_marsh_growth_pct: float
    max_carrier_sow_pct: float
    max_carrier_premium: float


@dataclass(frozen=True)
class Materiality:
    growth_gap_pp: float
    sow_loss_pp: float
    survey_gap_points: float


@dataclass(frozen=True)
class SurveyGates:
    min_responses: int
    min_peer_carriers: int


@dataclass(frozen=True)
class Shortlist:
    opportunities_per_country: int
    opportunities_per_product: int
    industries_top: int
    industries_bottom: int
    products_per_side: int
    countries_per_side: int
    attributes_per_side: int


@dataclass(frozen=True)
class FindingCaps:
    product_max: int
    opportunity_max: int
    country_max: int
    overall_min: int
    overall_max: int


@dataclass(frozen=True)
class Budgets:
    input_tokens: Dict[str, int]          # per stage
    output_tokens: int
    concurrency: int

    def input_for(self, stage: str) -> int:
        return int(self.input_tokens.get(stage, min(self.input_tokens.values())))


@dataclass(frozen=True)
class ExecConfig:
    rule_version: str
    selection_rule_version: str
    whitespace: WhitespaceGates
    materiality: Materiality
    survey: SurveyGates
    shortlist: Shortlist
    findings: FindingCaps
    budgets: Budgets


def config_from_mapping(raw: Mapping[str, Any]) -> ExecConfig:
    """Build the frozen config from a parsed YAML mapping."""
    return ExecConfig(
        rule_version=str(raw["rule_version"]),
        selection_rule_version=str(raw["selection_rule_version"]),
        whitespace=WhitespaceGates(**{k: float(v) for k, v in raw["whitespace"].items()}),
        materiality=Materiality(**{k: float(v) for k, v in raw["materiality"].items()}),
        survey=SurveyGates(**{k: int(v) for k, v in raw["survey"].items()}),
        shortlist=Shortlist(**{k: int(v) for k, v in raw["shortlist"].items()}),
        findings=FindingCaps(**{k: int(v) for k, v in raw["findings"].items()}),
        budgets=Budgets(input_tokens={str(k): int(v) for k, v in raw["budgets"]["input_tokens"].items()},
                        output_tokens=int(raw["budgets"]["output_tokens"]),
                        concurrency=int(raw["budgets"]["concurrency"])),
    )


@lru_cache(maxsize=4)
def load_config(path: Optional[str] = None) -> ExecConfig:
    """The rules in force — ``rules.yaml`` beside this module unless a path is given."""
    raw = yaml.safe_load(Path(path or RULES_PATH).read_text(encoding="utf-8")) or {}
    return config_from_mapping(raw)
