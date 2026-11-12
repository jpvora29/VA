"""Deterministic chart/table parsing for source-grounded enrichment."""
from __future__ import annotations
from typing import Any, Dict, List
from recap.schemas.raw_extraction import ElementType, RawElement


def parse_elements(elements: List[RawElement]) -> Dict[str, Any]:
    """Return labelled chart/table records before any LLM interpretation."""
    charts: List[Dict[str, Any]] = []
    tables: List[Dict[str, Any]] = []
    for el in elements:
        if el.element_type == ElementType.CHART and el.chart:
            records = []
            for series in el.chart.series:
                for idx, value in enumerate(series.values):
                    category = series.categories[idx] if idx < len(series.categories) else None
                    records.append({"series": series.series_name, "category": category, "value": value})
            charts.append({
                "element_id": el.element_id,
                "title": el.chart.title,
                "chart_type": el.chart.chart_type,
                "category_axis": el.chart.category_axis_label,
                "value_axis": el.chart.value_axis_label,
                "records": records,
            })
        elif el.element_type == ElementType.TABLE and el.table:
            grid = [["" for _ in range(el.table.cols)] for _ in range(el.table.rows)]
            for cell in el.table.cells:
                if 0 <= cell.row < el.table.rows and 0 <= cell.col < el.table.cols:
                    grid[cell.row][cell.col] = cell.text.strip()
            headers = grid[0] if grid else []
            rows = []
            for ri, row in enumerate(grid[1:], start=1):
                if not any(row):
                    continue
                values = []
                for ci, value in enumerate(row):
                    if value:
                        values.append({"row": ri, "column": headers[ci] if ci < len(headers) else None, "value": value})
                rows.append({"row": ri, "cells": values})
            tables.append({"element_id": el.element_id, "rows": el.table.rows, "cols": el.table.cols, "headers": headers, "records": rows})
    record_count = sum(len(c["records"]) for c in charts) + sum(sum(len(r["cells"]) for r in t["records"]) for t in tables)
    return {"charts": charts, "tables": tables, "record_count": record_count, "parser": "deterministic_v1"}


def records_to_metrics(parsed: Dict[str, Any]) -> List[str]:
    """Render deterministic records as labelled metric strings."""
    out: List[str] = []
    for chart in parsed.get("charts", []):
        prefix = chart.get("title") or chart.get("value_axis") or "Chart value"
        for record in chart.get("records", []):
            label = " | ".join(str(x) for x in [prefix, record.get("series"), record.get("category")] if x)
            out.append(f"{label}: {record.get('value')}")
    for table in parsed.get("tables", []):
        for row in table.get("records", []):
            for cell in row.get("cells", []):
                label = cell.get("column") or "Table value"
                out.append(f"{label}: {cell.get('value')}")
    return out
