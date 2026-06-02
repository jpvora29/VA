from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional, Any
import re
from document_builder.helpers.number_formatter import coerce_kpi_number


@dataclass
class TopKPIs:
    total_premium: int | float | str
    yoy: float | str
    gpr_rank: int | str
    rank_delta: float | str
    survey_score: float | str

    def __post_init__(self) -> None:
        for f in fields(self):
            raw = getattr(self, f.name)
            setattr(self, f.name, coerce_kpi_number(raw))


@dataclass
class ReportConfig:
    country: str
    carrier: str
    year: int
    question_results: list[dict[str, Any]]
    filters: dict[str, Any]
    report_summary: str
    top_kpis: Optional[dict[str, Any]]
    filename: str
    output_path: Path

    @staticmethod
    def _safe_filename(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "pitch_report").strip("_")
        return cleaned[:80] or "pitch_report"
