"""The 2026-11 Recap gates: what is dropped before grouping and before classification,
and the deterministic chart/table records enrichment is now grounded in.

All pure functions — no model, no deck file.
"""
from __future__ import annotations

from recap.extraction.deterministic import parse_elements, records_to_metrics
from recap.pipeline.pipeline import drop_inert_elements
from recap.schemas.raw_extraction import (
    ElementType,
    RawChart,
    RawChartSeries,
    RawElement,
    RawTable,
    RawTableCell,
)


_ids = iter(range(1, 10_000))


def element(element_type: ElementType, **fields) -> RawElement:
    return RawElement(element_id=f"e{next(_ids)}", deck_id="d", slide_number=2,
                      element_type=element_type, **fields)


GWP_CHART = RawChart(
    title="GWP by country",
    series=[RawChartSeries(series_name="2026", categories=["Germany", "Spain"], values=[12, 8])],
)

GWP_TABLE = RawTable(rows=2, cols=2, cells=[
    RawTableCell(row=0, col=0, text="Country", is_header=True),
    RawTableCell(row=0, col=1, text="GWP", is_header=True),
    RawTableCell(row=1, col=0, text="Germany"),
    RawTableCell(row=1, col=1, text="12"),
])


# ── before grouping ──────────────────────────────────────────────────────────


def test_connectors_and_empty_shapes_never_reach_grouping():
    """They carry nothing, but would anchor proximity clusters and drag unrelated
    text into one mixed-type SCU."""
    kept = [
        element(ElementType.CONNECTOR, text="arrow"),
        element(ElementType.SHAPE),
        element(ElementType.SHAPE, text="   "),
        element(ElementType.TEXT_BOX, text="GWP grew 12% in Germany"),
        element(ElementType.CHART, chart=GWP_CHART),
        element(ElementType.TABLE, table=GWP_TABLE),
        element(ElementType.IMAGE, alt_text="Map of Europe"),
    ]
    useful = drop_inert_elements(2, kept)
    assert [el.element_type for el in useful] == [
        ElementType.TEXT_BOX, ElementType.CHART, ElementType.TABLE, ElementType.IMAGE,
    ]


def test_nothing_is_dropped_from_a_slide_of_real_content():
    kept = [element(ElementType.TEXT_BOX, text="Loss ratio improved to 61%")]
    assert drop_inert_elements(2, kept) == kept


# ── deterministic chart and table records ────────────────────────────────────


def test_chart_and_table_values_are_read_before_any_model_sees_them():
    parsed = parse_elements([
        element(ElementType.CHART, chart=GWP_CHART),
        element(ElementType.TABLE, table=GWP_TABLE),
        element(ElementType.TEXT_BOX, text="prose is not parsed here"),
    ])
    assert parsed["record_count"] == 4  # two chart points, two table cells
    assert records_to_metrics(parsed) == [
        "GWP by country | 2026 | Germany: 12",
        "GWP by country | 2026 | Spain: 8",
        "Country: Germany",
        "GWP: 12",
    ]
