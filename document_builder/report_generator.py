import os

from typing import Any, Optional
from docx import Document

from document_builder.helpers.xml_helper import *
from document_builder.helpers.docx_helper import *
from document_builder.helpers.number_formatter import *

from document_builder.documents.header_banner import add_header
from document_builder.documents.section_heading import add_section_heading
from document_builder.documents.body_content import add_body_content
from config.report_config import *
from document_builder.models import ReportConfig

PITCH_THEMES: dict[str, dict[str, Any]] = {
    "performance_pitch": {
        "label": "Performance Pitch",
        "description": "Build a carrier-facing insurance narrative from filtered market and performance context.",
        "questions": [
            "How is the premium, total policies, rank and compare it with last year?",
            # "How is the score and compare it with last year?",
            # "Which are top and bottom 5 products, my appetite and their share in marsh book also compare it with last year?",
            # "What is the score and top and bottom 3 attributes for each section?",
            # "How is the premium, yoy growth compared to Marsh across each product and their respective change from last year?",
            # "How is the performance in comparison with its peers across each product and compare it with last year?",
            # "Compare the carrier performance with respect to the top 5 carriers?",
        ],
    }
}


def theme_options() -> list[dict[str, str]]:
    return [
        {"label": theme["label"], "value": key} for key, theme in PITCH_THEMES.items()
    ]


def get_theme(theme_key: str) -> dict[str, Any]:
    return PITCH_THEMES.get(theme_key) or PITCH_THEMES["performance_pitch"]


def frame_theme_questions(theme_key: str, filters: dict[str, Any]) -> list[str]:
    theme = get_theme(theme_key)
    carrier = filters.get("carrier") or ""
    country = filters.get("country") or ""
    year = filters.get("year") or ""

    framed_questions = []
    for question in theme["questions"]:
        clean_question = question.strip()
        if clean_question:
            clean_question = clean_question[0].lower() + clean_question[1:]

        framed_questions.append(
            f" For {carrier} in {country} for {year}, {clean_question}"
        )

    return framed_questions


# --- Main Document builder---------------------------------------


def make_top_kpis(top_kpis: Optional[dict[str, Any]]) -> TopKPIs:
    kpis = TopKPIs(
        total_premium=top_kpis.get("total_premium"),
        yoy=top_kpis.get("yoy"),
        gpr_rank=top_kpis.get("gpr_rank"),
        rank_delta=top_kpis.get("rank_delta"),
        survey_score=top_kpis.get("survey_score"),
    )

    return kpis


def build_pitch_report_docx(ctx: ReportConfig) -> Path:
    os.makedirs(ctx.output_path, exist_ok=True)

    doc = Document()

    # Page setup
    section = doc.sections[0]
    section.page_height = PAGE_HEIGHT
    section.page_width = PAGE_WIDTH
    section.top_margin = MARGIN_TOP
    section.bottom_margin = MARGIN_BOTTOM
    section.left_margin = MARGIN_LEFT
    section.right_margin = MARGIN_RIGHT

    styles = doc.styles
    styles["Normal"].font.name = BODY_FONT
    styles["Normal"].font.size = BODY_SIZE

    # --- 1. HEADER BANNER ------------------------
    add_header(doc, ctx.carrier, ctx.country, ctx.year)

    # --- 2a. KPI STRIP - Executive Narrative -----------------------------------
    kpis = make_top_kpis(ctx.top_kpis)
    add_kpi_strip(doc, kpis)

    # --- 2. SECTION HEADING - Executive Narrative ------------------------------
    add_section_heading(doc)

    # --- 3. BODY CONTENT ---------------------------------------
    add_body_content(doc, ctx.report_summary)

    # --- 4. PRODUCT BREAKDOWN ---------------------------------------
    add_product_breakdown_section(doc, ctx.question_results or [], ctx.filters)

    doc.save(ctx.output_path / ctx.filename)
    return ctx.output_path / ctx.filename


if __name__ == "__main__":

    doc = Document()
    question_results = [
        {
            "question": "What is the appetite of ZURICH in 2025 singapore?",
            "pitch_query_result": [],
        }
    ]
    filters = ({"country": "Singpore", "carrier": "ZURICH", "year": "2025"},)
    top_kpis = {
        "total_curr_premium": "USD 57,616,719.76",
        "yoy": "-9.25%",
        "gpr_rank": "14",
        "rank_delta": "-4",
        "survey_score": "",
        "policies": "420",
        "last_year_rank": "10",
    }

    kpis = make_top_kpis(top_kpis)

    add_kpi_strip(doc, kpis)
